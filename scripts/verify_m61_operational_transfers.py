from __future__ import annotations

import argparse
import json
import os
import sys
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine as application_engine
from core.domain.finance.operational_balance_contract import (
    CreateOperationalAccountCommand, OperationalBalanceQuery,
    RecordActualBalanceCommand, RecordBalanceAnchorCommand,
)
from core.domain.finance.operational_balance_engine import TransactionalOperationalBalanceEngine
from core.domain.finance.operational_balance_service import OperationalBalanceService
from core.domain.finance.operational_transfer_contract import (
    ReconciliationSeriesQuery, RecordOperationalTransferCommand, ReverseOperationalTransferCommand,
)
from core.domain.finance.operational_transfer_engine import TransactionalOperationalTransferEngine
from core.domain.finance.reconciliation_series_service import ReconciliationSeriesService

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m61_transfers_test"
PARENT_REVISION = "m60_operational_balance_authority_016"
TARGET_REVISION = "m61_transfers_reconciliation_017"
BASE = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
CORRELATION = UUID("61000000-0000-0000-0000-000000000099")
SOURCE_PUBLIC = UUID("61000000-0000-0000-0000-000000000001")
DESTINATION_PUBLIC = UUID("61000000-0000-0000-0000-000000000002")
TRANSFER_PUBLIC = UUID("61000000-0000-0000-0001-000000000001")

FINANCIAL_EMPTY_TABLES = (
    "idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
    "operational_account_authorities", "operational_account_balance_anchors",
    "operational_account_balance_observations",
)


def _url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _engine(name, isolation_level=None): return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


def _exists(name):
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally:
        selected.dispose()


def _create_clone():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally:
        selected.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        selected.dispose()


@contextmanager
def _migration_database(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous


def _migrate(name, revision, *, downgrade=False):
    with _migration_database(name):
        action = alembic_command.downgrade if downgrade else alembic_command.upgrade
        action(Config(str(ROOT / "alembic.ini")), revision)


def _revision(connection): return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}:
            raise RuntimeError(f"unexpected development revision={revision}")
        view_exists = bool(connection.execute(text("SELECT 1 FROM pg_views WHERE schemaname='public' AND viewname='operational_account_reconciliation_series'")).scalar_one_or_none())
        if view_exists != (revision == TARGET_REVISION):
            raise RuntimeError("M6.1 reconciliation-series view does not match revision")
        for table in FINANCIAL_EMPTY_TABLES:
            if connection.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one():
                raise RuntimeError(f"development financial table is not empty={table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m61_operational_transfers_development=PASS")
    return revision


def _status():
    exists = _exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _account(tenant, org, public_id, code, account_type, key):
    return CreateOperationalAccountCommand(
        public_id=public_id, tenant_id=tenant, organization_unit_id=org,
        account_class="treasury", account_type=account_type, code=code, display_name=code.replace("-", " ").title(),
        currency_code="XAF", aggregation_role="leaf", opened_at=BASE-timedelta(hours=1),
        correlation_id=CORRELATION, source_component="m61.verifier", source_record_id=key,
        idempotency_scope="m61.account", idempotency_key=key, actor_service="m61.verifier",
    )


def _anchor(tenant, org, account_public, number):
    return RecordBalanceAnchorCommand(
        public_id=UUID(f"61000000-0000-0000-0003-{number:012d}"), tenant_id=tenant,
        organization_unit_id=org, operational_account_public_id=account_public,
        anchor_balance="100", currency_code="XAF", anchor_at=BASE,
        provenance="opening_import", evidence_payload={"approved_opening": str(account_public)},
        occurred_at=BASE, business_date=date(2026,8,10), calendar_policy_version=1,
        correlation_id=CORRELATION, source_component="m61.verifier", source_record_id=f"anchor-{number}",
        idempotency_scope="m61.anchor", idempotency_key=f"anchor-{number}", actor_service="m61.verifier",
    )


def _transfer(tenant, org, *, amount="25", key="transfer-1", public_id=TRANSFER_PUBLIC):
    return RecordOperationalTransferCommand(
        public_id=public_id, tenant_id=tenant, organization_unit_id=org,
        source_operational_account_public_id=SOURCE_PUBLIC,
        destination_operational_account_public_id=DESTINATION_PUBLIC,
        amount=amount, currency_code="XAF", occurred_at=BASE+timedelta(minutes=1),
        value_at=BASE+timedelta(minutes=2), business_date=date(2026,8,10), calendar_policy_version=1,
        provenance="operator_authorized", transfer_purpose="treasury_sweep",
        evidence_payload={"authorization": "m61-approved"}, source_record_id=1,
        idempotency_scope="m61.transfer", idempotency_key=key, correlation_id=CORRELATION,
        actor_service="m61.verifier", metadata={"neutral_pattern": "cash_account_to_safe_account"},
    )


def _reversal(tenant, org, source_record_id):
    return ReverseOperationalTransferCommand(
        public_id=UUID("61000000-0000-0000-0002-000000000001"), tenant_id=tenant,
        organization_unit_id=org, original_transfer_public_id=TRANSFER_PUBLIC,
        amount="10", currency_code="XAF", occurred_at=BASE+timedelta(minutes=3),
        value_at=BASE+timedelta(minutes=3), business_date=date(2026,8,10), calendar_policy_version=1,
        reversal_reason="authorization_voided", evidence_payload={"approval": "m61-reversal"},
        source_record_id=source_record_id, idempotency_scope="m61.reversal", idempotency_key="reversal-1",
        correlation_id=CORRELATION, causation_id=TRANSFER_PUBLIC, actor_service="m61.verifier",
    )


def _expect(code, action):
    try: action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected error={code}, found={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error was not raised={code}")


def _seed(session):
    tenant = int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
    org = session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:tenant ORDER BY id LIMIT 1"), {"tenant": tenant}).scalar_one_or_none()
    if org is None:
        org = session.execute(text("INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active) VALUES(:tenant,'branch','m61-verifier','M6.1 Verifier','Africa/Douala',true) RETURNING id"), {"tenant": tenant}).scalar_one()
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    session.execute(text("""INSERT INTO tenant_currency_policies(tenant_id,currency_code,rounding_mode,cash_rounding_increment,active,effective_from,policy_version)
        VALUES(:tenant,'XAF','half_even',0,true,:effective,61)
        ON CONFLICT(tenant_id,currency_code,policy_version) DO UPDATE SET active=true"""), {"tenant": tenant, "effective": BASE-timedelta(days=1)})
    transfer_source = session.execute(text("""INSERT INTO kernel_source_records(tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,source_occurred_at)
        VALUES(:tenant,:org,'m61.verifier','value_transfer','transfer-1',:at) RETURNING id"""), {"tenant": tenant, "org": org, "at": BASE}).scalar_one()
    reversal_source = session.execute(text("""INSERT INTO kernel_source_records(tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,source_occurred_at)
        VALUES(:tenant,:org,'m61.verifier','financial_event_reversal','reversal-1',:at) RETURNING id"""), {"tenant": tenant, "org": org, "at": BASE}).scalar_one()
    source = TransactionalOperationalBalanceEngine.create_account(session, _account(tenant, int(org), SOURCE_PUBLIC, "m61-drawer", "cash", "source"))
    destination = TransactionalOperationalBalanceEngine.create_account(session, _account(tenant, int(org), DESTINATION_PUBLIC, "m61-safe", "cash", "destination"))
    TransactionalOperationalBalanceEngine.record_anchor(session, _anchor(tenant, int(org), source.public_id, 1))
    TransactionalOperationalBalanceEngine.record_anchor(session, _anchor(tenant, int(org), destination.public_id, 2))
    session.execute(text("""INSERT INTO accounting_periods(tenant_id,legal_entity_unit_id,period_code,period_start,period_end,period_state)
        VALUES(:tenant,:org,'2026-08','2026-08-01','2026-08-31','open')
        ON CONFLICT(tenant_id,legal_entity_unit_id,period_code) DO NOTHING"""), {"tenant": tenant, "org": org})
    for number, (role, operational_id) in enumerate((("source_operational_asset", source.id), ("target_operational_asset", destination.id)), 1):
        ledger_id = session.execute(text("""INSERT INTO ledger_accounts(public_id,tenant_id,legal_entity_unit_id,account_code,account_name,account_type,normal_balance,currency_policy,fixed_currency_code,active,effective_from)
            VALUES(:public,:tenant,:org,:code,:name,'asset','debit','fixed','XAF',true,'2026-01-01') RETURNING id"""), {
                "public": f"61000000-0000-0000-0004-{number:012d}", "tenant": tenant, "org": org,
                "code": f"m61-{number}", "name": role.replace("_", " ").title(),
            }).scalar_one()
        session.execute(text("""INSERT INTO ledger_account_role_bindings(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,ledger_account_id,operational_account_id,effective_from,active)
            VALUES(:tenant,:org,:role,'default','XAF',:ledger,:operational,'2026-01-01',true)"""), {
                "tenant": tenant, "org": org, "role": role, "ledger": ledger_id, "operational": operational_id,
            })
    return tenant, int(org), int(transfer_source), int(reversal_source), source, destination


def _exercise(selected_engine):
    with Session(selected_engine) as session, session.begin():
        tenant, org, transfer_source, reversal_source, source, destination = _seed(session)
        command = replace(_transfer(tenant, org), source_record_id=transfer_source)
        first = TransactionalOperationalTransferEngine.record(session, command)
        replay = TransactionalOperationalTransferEngine.record(session, command)
        if not replay.replayed or replay.financial_event_result.event.id != first.financial_event_result.event.id:
            raise RuntimeError("transfer replay did not resolve the same event")
        _expect("idempotency_conflict", lambda: TransactionalOperationalTransferEngine.record(session, replace(command, amount=Decimal("26"))))
        _expect("operational_account_not_found", lambda: TransactionalOperationalTransferEngine.record(session, replace(
            command, tenant_id=tenant+100000, public_id=UUID("61000000-0000-0000-0000-000000000001"),
            idempotency_key="cross-tenant",
        )))
        _expect("account_organization_mismatch", lambda: TransactionalOperationalTransferEngine.record(session, replace(
            command, organization_unit_id=org+100000, public_id=UUID("61000000-0000-0000-0000-000000000002"),
            idempotency_key="cross-org",
        )))
        _expect("account_currency_mismatch", lambda: TransactionalOperationalTransferEngine.record(session, replace(
            command, currency_code="USD", public_id=UUID("61000000-0000-0000-0000-000000000003"),
            idempotency_key="currency",
        )))
        reversal = TransactionalOperationalTransferEngine.reverse(session, _reversal(tenant, org, reversal_source))
        _expect("reversal_capacity_exceeded", lambda: TransactionalOperationalTransferEngine.reverse(session, replace(
            _reversal(tenant, org, reversal_source), amount=Decimal("20"),
            public_id=UUID("61000000-0000-0000-0000-000000000004"),
            idempotency_key="reversal-over-capacity",
        )))
        source_position = OperationalBalanceService.resolve(session, OperationalBalanceQuery(tenant, org, source.public_id, BASE+timedelta(minutes=4)))
        destination_position = OperationalBalanceService.resolve(session, OperationalBalanceQuery(tenant, org, destination.public_id, BASE+timedelta(minutes=4)))
        if source_position.expected_balance != Decimal("85") or destination_position.expected_balance != Decimal("115"):
            raise RuntimeError(f"transfer expected-balance direction failed source={source_position} destination={destination_position}")
        TransactionalOperationalBalanceEngine.record_actual(session, RecordActualBalanceCommand(
            public_id=UUID("61000000-0000-0000-0005-000000000001"), tenant_id=tenant,
            organization_unit_id=org, operational_account_public_id=source.public_id,
            actual_balance="85", currency_code="XAF", observed_at=BASE+timedelta(minutes=4),
            provenance="operator_counted", evidence_payload={"count_sheet": "m61"},
            occurred_at=BASE+timedelta(minutes=4), business_date=date(2026,8,10), calendar_policy_version=1,
            correlation_id=CORRELATION, source_component="m61.verifier", source_record_id="actual",
            idempotency_scope="m61.actual", idempotency_key="actual", actor_service="m61.verifier",
        ))
        series = ReconciliationSeriesService.resolve(session, ReconciliationSeriesQuery(
            tenant, org, source.public_id, BASE+timedelta(minutes=5)
        ))
        if [entry.fact_kind for entry in series.entries] != ["balance_anchor", "transfer", "transfer_reversal", "actual_observation"]:
            raise RuntimeError(f"unexpected reconciliation series={[entry.fact_kind for entry in series.entries]}")
        if [entry.effect_amount for entry in series.entries[1:3]] != [Decimal("-25"), Decimal("10")]:
            raise RuntimeError("reconciliation transfer direction failed")
        if series.entries[2].original_fact_public_id != TRANSFER_PUBLIC:
            raise RuntimeError("transfer reversal lineage missing")
        original_event_id = first.financial_event_result.event.id
        reversal_event_id = reversal.financial_event_result.event.id
        try:
            with session.begin_nested():
                session.execute(text("UPDATE financial_events SET amount=999 WHERE id=:id"), {"id": original_event_id})
        except DBAPIError:
            pass
        else:
            raise RuntimeError("accepted transfer mutation was allowed")
        row = session.execute(text("SELECT * FROM financial_events WHERE id=:id"), {"id": original_event_id}).mappings().one()
        invalid = dict(row)
        invalid.update(
            public_id="61000000-0000-0000-0006-000000000001", idempotency_key="direct-invalid",
            evidence_hash=None, metadata="{}",
            classification_snapshot=json.dumps(row["classification_snapshot"], sort_keys=True),
            posting_context=json.dumps(row["posting_context"], sort_keys=True),
        )
        try:
            with session.begin_nested():
                session.execute(text("""INSERT INTO financial_events(public_id,tenant_id,organization_unit_id,event_type_code,event_version,amount,currency_code,economic_role,
                    source_operational_account_id,target_operational_account_id,source_record_id,occurred_at,business_date,calendar_policy_version,
                    actor_service,idempotency_scope,idempotency_key,correlation_id,classification_snapshot,posting_context,evidence_hash,metadata)
                    VALUES(:public_id,:tenant_id,:organization_unit_id,:event_type_code,:event_version,:amount,:currency_code,:economic_role,
                    :source_operational_account_id,:target_operational_account_id,:source_record_id,:occurred_at,:business_date,:calendar_policy_version,
                    :actor_service,:idempotency_scope,:idempotency_key,:correlation_id,CAST(:classification_snapshot AS JSONB),CAST(:posting_context AS JSONB),
                    :evidence_hash,CAST(:metadata AS JSONB))"""), invalid)
        except DBAPIError:
            pass
        else:
            raise RuntimeError("direct SQL transfer without evidence was allowed")
        if reversal_event_id == original_event_id:
            raise RuntimeError("reversal overwrote original event")

    with selected_engine.connect() as connection:
        counts = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in (
            "financial_events", "outbox_messages", "journal_entries", "journal_entry_event_links",
        )}
        if counts != {"financial_events": 2, "outbox_messages": 2, "journal_entries": 2, "journal_entry_event_links": 2}:
            raise RuntimeError(f"unexpected transfer atomic counts={counts}")
        journal = connection.execute(text("""SELECT count(*) entries,
            count(DISTINCT je.id) journals,
            count(DISTINCT link.financial_event_id) linked_events,
            count(*) FILTER (WHERE la.account_type<>'asset') non_asset,
            count(*) FILTER (WHERE jl.account_role NOT IN ('source_operational_asset','target_operational_asset')) invalid_role,
            sum(jl.transaction_debit_amount) debit,sum(jl.transaction_credit_amount) credit
            FROM financial_events fe
            JOIN journal_entry_event_links link
              ON link.tenant_id=fe.tenant_id AND link.financial_event_id=fe.id
             AND link.allocation_role='primary_event_posting'
            JOIN journal_entries je
              ON je.tenant_id=link.tenant_id AND je.id=link.journal_entry_id
            JOIN journal_lines jl
              ON jl.tenant_id=je.tenant_id AND jl.journal_entry_id=je.id
            JOIN ledger_accounts la
              ON la.tenant_id=jl.tenant_id AND la.id=jl.ledger_account_id
            WHERE fe.id IN (:original_event_id,:reversal_event_id)"""), {
                "original_event_id": original_event_id, "reversal_event_id": reversal_event_id,
            }).mappings().one()
        if (journal["non_asset"] or journal["invalid_role"] or journal["debit"] != journal["credit"]
                or journal["entries"] != 4 or journal["journals"] != 2 or journal["linked_events"] != 2):
            raise RuntimeError(f"transfer posting is not balanced asset-to-asset={dict(journal)}")
        before = connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one()
    with Session(selected_engine) as session:
        transaction = session.begin()
        tenant = int(session.execute(text("SELECT tenant_id FROM financial_events WHERE public_id=:public"), {"public": str(TRANSFER_PUBLIC)}).scalar_one())
        org = int(session.execute(text("SELECT organization_unit_id FROM financial_events WHERE public_id=:public"), {"public": str(TRANSFER_PUBLIC)}).scalar_one())
        source_record = session.execute(text("INSERT INTO kernel_source_records(tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,source_occurred_at) VALUES(:tenant,:org,'m61.verifier','value_transfer','rollback',:at) RETURNING id"), {"tenant": tenant, "org": org, "at": BASE}).scalar_one()
        TransactionalOperationalTransferEngine.record(session, replace(
            _transfer(tenant, org, key="rollback", public_id=UUID("61000000-0000-0000-0007-000000000001")),
            source_record_id=source_record,
        ))
        session.flush(); transaction.rollback()
    with selected_engine.connect() as connection:
        if connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one() != before:
            raise RuntimeError("outer rollback leaked transfer effects")


def _run():
    _verify_development(); _create_clone(); selected = None
    try:
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        selected = _engine(TEST_DATABASE_NAME)
        with selected.connect() as connection:
            if _revision(connection) != TARGET_REVISION: raise RuntimeError("disposable database did not reach M6.1")
        selected.dispose(); selected = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        selected = _engine(TEST_DATABASE_NAME); _exercise(selected); selected.dispose(); selected = None
        _drop(TEST_DATABASE_NAME); _verify_development()
        print(f"m61_operational_transfers=PASS database={TEST_DATABASE_NAME} bilateral=PASS non_pnl=PASS expected_balance=PASS replay=PASS conflict=PASS reversal=PASS series=PASS tenant_scope=PASS immutability=PASS direct_sql=PASS posting=PASS rollback=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if selected is not None: selected.dispose()
        print(f"M6.1 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status"); sub.add_parser("verify"); sub.add_parser("create-and-verify")
    drop = sub.add_parser("drop"); drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()
    if args.command == "status": return 0 if _status() else 1
    if args.command == "verify": _verify_development()
    elif args.command == "create-and-verify": _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME: raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
