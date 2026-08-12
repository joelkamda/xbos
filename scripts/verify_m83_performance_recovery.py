"""Production-shaped PostgreSQL evidence for M8.3 performance and recovery."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from core.domain.finance.allocation_contract import AllocateValueCommand, CreateValueSourceCommand
from core.domain.finance.allocation_engine import TransactionalAllocationEngine
from core.domain.finance.atomic_posting_engine import AtomicPostedFinancialEventEngine
from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import EXPECTED_HEAD, validate_frozen_m4_manifest, validate_release_manifest as m6_manifest
from core.domain.finance.m7_acceptance import validate_release_manifest as m7_manifest
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.performance_recovery_contract import FinancialRecoveryFingerprint, PerformanceRecoveryEvidence, QueryPlanEvidence
from core.domain.finance.performance_recovery_service import validate_operator_runbook, validate_recovery_evidence
from database import engine as application_engine
from scripts.verify_m21_canonical_event_engine import ORG_ONE, TENANT_ONE, _event_command, _install_fixtures
from scripts.verify_m24_canonical_balanced_posting import _install_posting_fixtures
from scripts.verify_m43_payment_settlements import _attempt, _attempt_transition, _intent, _seed_scope, _settlement, _settlement_transition
from scripts import verify_m64_reconciliation_controls as m64

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
VOLUME_DATABASE_NAME = "xbos_track_b_m83_volume_test"
RESTORE_DATABASE_NAME = "xbos_track_b_m83_restore_test"
ROLLBACK_DATABASE_NAME = "xbos_track_b_m83_rollback_test"
APPROVED_DATABASES = {VOLUME_DATABASE_NAME, RESTORE_DATABASE_NAME, ROLLBACK_DATABASE_NAME}
PARENT_REVISION = "m63_reconciliation_close_019"
EVENT_COUNT = 600
OBLIGATION_COUNT = 120
PAYMENT_COUNT = 40
BASE = datetime(2026, 8, 12, 8, tzinfo=timezone.utc)
BACKUP_PATH = Path(tempfile.gettempdir()) / "xbos_track_b_m83_volume_test.backup"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _url():
    value = make_url(application_engine.url)
    if value.host not in LOCAL_HOSTS: raise RuntimeError(f"refusing non-local PostgreSQL host={value.host!r}")
    return value


def _engine(name, autocommit=False):
    options={"pool_pre_ping":True}
    if autocommit: options["isolation_level"]="AUTOCOMMIT"
    return create_engine(_url().set(database=name),**options)


def _exists(name):
    selected=_engine("postgres",True)
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"),{"name":name}).scalar_one_or_none())
    finally: selected.dispose()


def _create_clone(name):
    if name not in APPROVED_DATABASES: raise RuntimeError(f"unsafe database name={name}")
    if _exists(name): raise RuntimeError(f"disposable database already exists={name}")
    application_engine.dispose(); selected=_engine("postgres",True)
    try:
        with selected.connect() as connection: connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally: selected.dispose()


def _create_clean(name):
    if name not in APPROVED_DATABASES or _exists(name): raise RuntimeError(f"unsafe or existing restore target={name}")
    selected=_engine("postgres",True)
    try:
        with selected.connect() as connection: connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
    finally: selected.dispose()


def _drop(name):
    if name not in APPROVED_DATABASES: raise RuntimeError(f"unsafe disposable database target={name}")
    selected=_engine("postgres",True)
    try:
        with selected.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),{"name":name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally: selected.dispose()


@contextmanager
def _selected_database(name):
    previous=os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"]=_url().set(database=name).render_as_string(hide_password=False)
    try: yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL",None)
        else: os.environ["DATABASE_URL"]=previous


def _migrate(name, revision, *, downgrade=False):
    with _selected_database(name):
        (alembic_command.downgrade if downgrade else alembic_command.upgrade)(Config(str(ROOT/"alembic.ini")),revision)


def _development():
    if _url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"development database must be={DEVELOPMENT_DATABASE_NAME}")
    releases=(m2_manifest(ROOT).checked_components,m3_manifest(ROOT).checked_components,validate_frozen_m4_manifest(ROOT),m5_manifest(ROOT),m6_manifest(ROOT).checked_components,m7_manifest(ROOT).checked_components)
    validate_operator_runbook(ROOT)
    empty=("financial_events","journal_entries","financial_obligations","value_sources","payment_allocations","canonical_payment_attempts","payment_settlements","reconciliation_windows","reconciliation_controls")
    with application_engine.connect() as connection:
        database=connection.execute(text("SELECT current_database()" )).scalar_one(); revision=connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database!=DEVELOPMENT_DATABASE_NAME or revision!=EXPECTED_HEAD: raise RuntimeError(f"unexpected development authority={database}:{revision}")
        for table in empty:
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one(): raise RuntimeError(f"development financial table not empty={table}")
    print(f"database={database}"); print(f"revision={revision}")
    print("release_manifests="+",".join(f"m{i+2}:{count}" for i,count in enumerate(releases)))
    print("m83_performance_recovery_development=PASS manifests=PASS development_empty=PASS schema_neutral=PASS")


def _uuid(kind, number): return UUID(f"83000000-0000-0000-{kind:04d}-{number:012d}")


def _payment_fixture(tenant, organization, provider, account, number, offset):
    """Build one deterministic, temporally valid payment lifecycle.

    The accepted M4.3 fixture helpers use their ``number`` argument as both an
    identity component and a minute offset.  M8.3 deliberately starts payment
    identities at 1000, so their original timestamps would place attempts well
    beyond the intent expiry.  Preserve the proven command shapes and stable
    identities while assigning a bounded M8.3 rehearsal timeline explicitly.
    """
    occurred=BASE+timedelta(minutes=offset*6)
    business_date=occurred.date()
    intent=replace(
        _intent(tenant,organization,number,"25"),
        occurred_at=occurred,
        expires_at=occurred+timedelta(minutes=30),
        business_date=business_date,
    )
    attempt=replace(
        _attempt(tenant,organization,provider,number,number,"25"),
        occurred_at=occurred+timedelta(minutes=1),
        timeout_at=occurred+timedelta(minutes=20),
        business_date=business_date,
    )
    processing=replace(
        _attempt_transition(attempt,1,"processing",f"m83-{number}-processing",number+1),
        occurred_at=occurred+timedelta(minutes=2),
        business_date=business_date,
    )
    succeeded=replace(
        _attempt_transition(attempt,2,"succeeded",f"m83-{number}-succeeded",number+2,{"provider_status":"success"}),
        occurred_at=occurred+timedelta(minutes=3),
        business_date=business_date,
    )
    settlement=replace(
        _settlement(tenant,organization,number,number,account,attempt=attempt,amount="25"),
        occurred_at=occurred+timedelta(minutes=4),
        value_date=business_date,
        business_date=business_date,
    )
    confirmed=replace(
        _settlement_transition(settlement,"confirmed",f"m83-{number}-confirmed",reference=f"m83-provider-{number}"),
        occurred_at=occurred+timedelta(minutes=5),
        business_date=business_date,
    )
    return intent,attempt,processing,succeeded,settlement,confirmed


def _seed_volume(selected):
    _install_fixtures(selected); _install_posting_fixtures(selected)
    with selected.begin() as connection:
        connection.execute(text("""INSERT INTO kernel_source_records(id,tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,source_occurred_at,metadata)
            SELECT 8300000+n,:tenant,:org,'m83.volume','commercial_transaction','volume-'||n,:at+(n||' seconds')::interval,'{}'::jsonb FROM generate_series(1,:count) n"""),{"tenant":TENANT_ONE,"org":ORG_ONE,"at":BASE,"count":EVENT_COUNT})
    started=time.perf_counter()
    with Session(selected) as session, session.begin():
        for number in range(1,EVENT_COUNT+1):
            command=_event_command(public_id=_uuid(1,number),source_record_id=8300000+number,amount=Decimal(100+(number%17)),
                occurred_at=BASE+timedelta(seconds=number),business_date=date(2026,8,12),correlation_id=_uuid(9,number),
                idempotency_key=f"m83:event:{number}",metadata={"fixture":"m83","sequence":number},actor_service="m83.verifier",
                posting_context={"posting_profile_code":"commercial_recognition"})
            AtomicPostedFinancialEventEngine.emit_and_post(session,command)
    event_seconds=time.perf_counter()-started

    debtor=_uuid(10,1); creditor=_uuid(10,2)
    with Session(selected) as session, session.begin():
        for number in range(1,OBLIGATION_COUNT+1):
            public=_uuid(2,number); source_public=_uuid(3,number); allocation_public=_uuid(4,number); amount=Decimal(50+(number%11))
            obligation=CreateObligationCommand(public_id=public,tenant_id=TENANT_ONE,organization_unit_id=ORG_ONE,debtor_party_id=debtor,creditor_party_id=creditor,obligation_type="trade_receivable",original_amount=amount,currency_code="XAF",due_at=BASE+timedelta(days=30),occurred_at=BASE,business_date=date(2026,8,12),calendar_policy_version=1,correlation_id=_uuid(11,number),
                actor_service="m83.verifier",source_component="m83.volume",source_record_id=f"obligation-{number}",idempotency_scope="m83.obligation",idempotency_key=f"obligation-{number}",
                lines=(ObligationLineCommand(1,"principal","Volume principal",Decimal(1),amount,amount,f"line-{number}"),))
            source=CreateValueSourceCommand(public_id=source_public,tenant_id=TENANT_ONE,organization_unit_id=ORG_ONE,owner_party_id=debtor,source_type="payment",source_amount=amount,currency_code="XAF",occurred_at=BASE,business_date=date(2026,8,12),calendar_policy_version=1,correlation_id=_uuid(11,number),
                actor_service="m83.verifier",source_component="m83.volume",source_record_id=f"source-{number}",idempotency_scope="m83.source",idempotency_key=f"source-{number}")
            TransactionalObligationEngine.create(session,obligation); TransactionalAllocationEngine.create_value_source(session,source)
            allocation=AllocateValueCommand(public_id=allocation_public,tenant_id=TENANT_ONE,organization_unit_id=ORG_ONE,value_source_public_id=source_public,obligation_public_id=public,allocation_amount=amount,currency_code="XAF",occurred_at=BASE,business_date=date(2026,8,12),calendar_policy_version=1,correlation_id=_uuid(11,number),
                actor_service="m83.verifier",source_component="m83.volume",source_record_id=f"allocation-{number}",idempotency_scope="m83.allocate",idempotency_key=f"allocation-{number}")
            TransactionalAllocationEngine.allocate(session,allocation)

    with Session(selected) as session, session.begin():
        tenant,org,provider,mobile,_cash=_seed_scope(session)
        for offset,number in enumerate(range(1000,1000+PAYMENT_COUNT)):
            intent,attempt,processing,succeeded,settlement,confirmed=_payment_fixture(tenant,org,provider,mobile,number,offset)
            TransactionalPaymentIntentEngine.create_intent(session,intent); TransactionalPaymentAttemptEngine.create(session,attempt)
            TransactionalPaymentAttemptEngine.transition(session,processing)
            TransactionalPaymentAttemptEngine.transition(session,succeeded)
            TransactionalPaymentSettlementEngine.create(session,settlement)
            TransactionalPaymentSettlementEngine.transition(session,confirmed)
    # Establish representative reconciliation/close/control history using its accepted verifier.
    m64._exercise(selected)
    return event_seconds


def _walk_plan(node, nodes, indexes):
    nodes.append(str(node.get("Node Type","")))
    if node.get("Index Name"): indexes.append(str(node["Index Name"]))
    for child in node.get("Plans",[]): _walk_plan(child,nodes,indexes)


def _plan(connection,name,relation,sql,parameters):
    connection.execute(text("SET LOCAL enable_seqscan=off"))
    payload=connection.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "+sql),parameters).scalar_one()
    if isinstance(payload,str): payload=json.loads(payload)
    report=payload[0]; nodes=[]; indexes=[]; _walk_plan(report["Plan"],nodes,indexes)
    return QueryPlanEvidence(name,relation,tuple(nodes),tuple(indexes),str(report.get("Planning Time","0")),str(report.get("Execution Time","0")),int(report["Plan"].get("Actual Rows",0)))


TABLES=("tenants","organization_units","idempotency_records","financial_events","outbox_messages","journal_entries","journal_lines","journal_entry_event_links","financial_obligations","financial_obligation_lines","value_sources","payment_allocations","canonical_payment_intents","canonical_payment_attempts","payment_settlements","payment_settlement_transitions","reconciliation_windows","reconciliation_window_revisions","reconciliation_window_governance_events","reconciliation_controls","reconciliation_evidence_references")


def _fingerprint(selected):
    counts={}; digests={}
    with selected.connect() as connection:
        revision=str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
        existing=set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        for table in TABLES:
            if table not in existing: continue
            row=connection.execute(text(f"SELECT count(*) AS count, md5(COALESCE(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) AS digest FROM {table} t")).mappings().one()
            counts[table]=int(row["count"]); digests[table]=str(row["digest"])
        totals={
            "event_amount":str(connection.execute(text("SELECT COALESCE(sum(amount),0) FROM financial_events")).scalar_one()),
            "journal_debit":str(connection.execute(text("SELECT COALESCE(sum(transaction_debit_amount),0) FROM journal_lines")).scalar_one()),
            "journal_credit":str(connection.execute(text("SELECT COALESCE(sum(transaction_credit_amount),0) FROM journal_lines")).scalar_one()),
            "obligation_original":str(connection.execute(text("SELECT COALESCE(sum(original_amount),0) FROM financial_obligations")).scalar_one()),
            "allocation_amount":str(connection.execute(text("SELECT COALESCE(sum(allocation_amount),0) FROM payment_allocations")).scalar_one()),
            "settlement_net":str(connection.execute(text("SELECT COALESCE(sum(net_amount),0) FROM payment_settlements")).scalar_one()),
        }
        if totals["journal_debit"]!=totals["journal_credit"]: raise RuntimeError("production-shaped journals are unbalanced")
    return FinancialRecoveryFingerprint(revision,counts,digests,totals)


def _tool_environment():
    url=_url(); env=os.environ.copy()
    for key,value in (("PGHOST",url.host),("PGPORT",str(url.port or 5432)),("PGUSER",url.username),("PGPASSWORD",url.password or "")):
        if value is not None: env[key]=value
    return env


def _run_tool(arguments):
    executable=shutil.which(arguments[0])
    if not executable: raise RuntimeError(f"required PostgreSQL tool not found={arguments[0]}")
    completed=subprocess.run([executable,*arguments[1:]],env=_tool_environment(),capture_output=True,text=True,timeout=300)
    if completed.returncode: raise RuntimeError(f"PostgreSQL tool failed={arguments[0]}: {completed.stderr.strip()[-1000:]}")


def _backup_restore():
    if BACKUP_PATH.exists(): raise RuntimeError(f"temporary backup already exists={BACKUP_PATH}")
    _run_tool(["pg_dump","--format=custom","--no-owner","--no-privileges","--file",str(BACKUP_PATH),VOLUME_DATABASE_NAME])
    if not BACKUP_PATH.is_file() or BACKUP_PATH.stat().st_size==0: raise RuntimeError("backup artifact is empty")
    _create_clean(RESTORE_DATABASE_NAME)
    _run_tool(["pg_restore","--exit-on-error","--no-owner","--no-privileges","--dbname",RESTORE_DATABASE_NAME,str(BACKUP_PATH)])


def _exercise():
    _create_clone(VOLUME_DATABASE_NAME); volume=_engine(VOLUME_DATABASE_NAME); restore=None
    try:
        elapsed=_seed_volume(volume)
        with volume.begin() as connection:
            connection.execute(text("ANALYZE"))
            payment_tenant=int(connection.execute(text("SELECT tenant_id FROM payment_settlements WHERE external_settlement_reference='m83-provider-1000'")).scalar_one())
            reconciliation_tenant=int(connection.execute(text("SELECT tenant_id FROM reconciliation_series ORDER BY id LIMIT 1")).scalar_one())
            event_id=int(connection.execute(text("SELECT id FROM financial_events WHERE tenant_id=:tenant AND source_record_id=8300001"),{"tenant":TENANT_ONE}).scalar_one())
            if connection.execute(text("SELECT count(*) FROM financial_events WHERE tenant_id<>:tenant AND source_record_id BETWEEN 8300001 AND 8300000+:count"),{"tenant":TENANT_ONE,"count":EVENT_COUNT}).scalar_one():
                raise RuntimeError("production-shaped event fixture crossed tenant authority")
            plans=(
                _plan(connection,"event_source_trace","financial_events","SELECT id FROM financial_events WHERE tenant_id=:tenant AND source_record_id=:source",{"tenant":TENANT_ONE,"source":8300001}),
                _plan(connection,"journal_event_trace","journal_entry_event_links","SELECT journal_entry_id FROM journal_entry_event_links WHERE tenant_id=:tenant AND financial_event_id=:event",{"tenant":TENANT_ONE,"event":event_id}),
                _plan(connection,"obligation_party_balance","financial_obligations","SELECT id FROM financial_obligations WHERE tenant_id=:tenant AND debtor_party_id=:party AND currency_code='XAF' AND obligation_state='satisfied' ORDER BY due_at",{"tenant":TENANT_ONE,"party":str(_uuid(10,1))}),
                _plan(connection,"provider_settlement_identity","payment_settlements","SELECT id FROM payment_settlements WHERE tenant_id=:tenant AND payment_rail_code='mtn_momo' AND external_settlement_reference=:reference",{"tenant":payment_tenant,"reference":"m83-provider-1000"}),
                _plan(connection,"reconciliation_series_order","reconciliation_windows","SELECT id FROM reconciliation_windows WHERE tenant_id=:tenant AND reconciliation_series_id=(SELECT id FROM reconciliation_series WHERE tenant_id=:tenant ORDER BY id LIMIT 1) ORDER BY window_end,id",{"tenant":reconciliation_tenant}),
            )
            if any(plan.actual_rows < 1 for plan in plans): raise RuntimeError("representative query plan returned no evidence rows")
        before=_fingerprint(volume); _backup_restore(); restore=_engine(RESTORE_DATABASE_NAME); after=_fingerprint(restore)
        _create_clone(ROLLBACK_DATABASE_NAME); _migrate(ROLLBACK_DATABASE_NAME,PARENT_REVISION,downgrade=True); _migrate(ROLLBACK_DATABASE_NAME,EXPECTED_HEAD)
        rollback_engine=_engine(ROLLBACK_DATABASE_NAME)
        try:
            with rollback_engine.connect() as connection: rollback_head=str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
        finally: rollback_engine.dispose()
        evidence=PerformanceRecoveryEvidence(before.table_counts,plans,before,after,rollback_head,after.canonical_head)
        validate_recovery_evidence(evidence)
        print("fixture_sizes="+",".join(f"{k}:{v}" for k,v in sorted(before.table_counts.items())))
        print(f"event_write_seconds={elapsed:.6f}")
        for plan in plans: print(f"query_plan={plan.name} indexes={','.join(plan.index_names)} planning_ms={plan.planning_time_ms} execution_ms={plan.execution_time_ms} rows={plan.actual_rows}")
        print(f"backup_bytes={BACKUP_PATH.stat().st_size} financial_fingerprint={before.semantic_fingerprint}")
        volume.dispose(); volume=None; restore.dispose(); restore=None
        for name in (VOLUME_DATABASE_NAME,RESTORE_DATABASE_NAME,ROLLBACK_DATABASE_NAME): _drop(name)
        BACKUP_PATH.unlink(); _development()
        print("m83_performance_recovery=PASS performance=PASS volume=PASS index_verification=PASS query_plans=PASS backup=PASS restore=PASS financial_equivalence=PASS rollback_rehearsal=PASS operator_recovery=PASS tenant_scope=PASS financial_invariants=PASS schema_neutral=PASS dropped=true backup_cleaned=true")
    except Exception:
        if volume is not None: volume.dispose()
        if restore is not None: restore.dispose()
        print(f"M8.3 verification failed; retained databases={','.join(name for name in APPROVED_DATABASES if _exists(name))} backup={BACKUP_PATH if BACKUP_PATH.exists() else 'none'}")
        raise


def _status():
    present=[name for name in APPROVED_DATABASES if _exists(name)]
    print(f"databases={','.join(present) if present else 'none'} backup_exists={str(BACKUP_PATH.exists()).lower()}")
    return not present and not BACKUP_PATH.exists()


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("status"); sub.add_parser("verify"); sub.add_parser("create-and-verify")
    drop=sub.add_parser("drop"); drop.add_argument("--confirm-database-name",required=True)
    args=parser.parse_args()
    if args.command=="status": return 0 if _status() else 1
    if args.command=="verify": _development()
    elif args.command=="create-and-verify": _development(); _exercise()
    else:
        if args.confirm_database_name not in APPROVED_DATABASES: raise RuntimeError("exact disposable database confirmation required")
        _drop(args.confirm_database_name); print(f"dropped={args.confirm_database_name}")
    return 0


if __name__=="__main__": raise SystemExit(main())
