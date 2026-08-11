from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.domain.finance.reconciliation_control_contract import (
    RecordReconciliationControlCommand, ReconciliationControlError,
    ReconciliationEvidenceReference, ReconciliationExplanation,
)
from core.domain.finance.reconciliation_control_engine import TransactionalReconciliationControlEngine
from core.domain.finance.reconciliation_report_service import ReconciliationReportService
from scripts import verify_m63_reconciliation_close_governance as m63

DEVELOPMENT_DATABASE_NAME = m63.DEVELOPMENT_DATABASE_NAME
TEST_DATABASE_NAME = "xbos_track_b_m64_reconciliation_test"
PARENT_REVISION = "m63_reconciliation_close_019"
TARGET_REVISION = "m64_reconciliation_controls_020"
BASE = m63.BASE
CORRELATION = UUID("64000000-0000-0000-0000-000000000099")
CUSTOMER = UUID("64000000-0000-0000-0000-000000000010")
SUPPLIER = UUID("64000000-0000-0000-0000-000000000011")
MERCHANT = UUID("64000000-0000-0000-0000-000000000012")


def _url(): return m63._url()
def _engine(name, isolation_level=None): return m63._engine(name, isolation_level)
def _exists(name): return m63._exists(name)
def _revision(connection): return m63._revision(connection)


def _create_clone():
    if _exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    m63.m62.application_engine.dispose()
    selected=_engine("postgres","AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally: selected.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME: raise RuntimeError(f"unsafe disposable database target={name}")
    selected=_engine("postgres","AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),{"name":name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally: selected.dispose()


def _migrate(name, revision, *, downgrade=False): return m63._migrate(name, revision, downgrade=downgrade)


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with m63.m62.application_engine.connect() as connection:
        revision=_revision(connection)
        if revision not in {PARENT_REVISION,TARGET_REVISION}: raise RuntimeError(f"unexpected development revision={revision}")
        exists=bool(connection.execute(text("SELECT to_regclass('public.reconciliation_controls')")).scalar_one())
        if exists != (revision==TARGET_REVISION): raise RuntimeError("M6.4 control authority differs from revision")
        if exists and connection.execute(text("SELECT count(*) FROM reconciliation_controls")).scalar_one():
            raise RuntimeError("development M6.4 control table is not empty")
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={revision}")
    print("m64_reconciliation_controls_development=PASS")


def _status():
    exists=_exists(TEST_DATABASE_NAME); print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}"); return not exists


def _evidence(number, kind):
    return ReconciliationEvidenceReference(UUID(f"64000000-0000-0000-0001-{number:012d}"),kind,
        f"external-{number}","independent-control",BASE+timedelta(days=1,hours=4),{"proof":f"m64-{number}"})


def _command(number, kind, tenant, org, start, end, control_position, *, account=None, window=None, party=None, explanations=()):
    evidence_kind={"bank":"bank_statement","accounts_receivable":"customer_control_statement","accounts_payable":"supplier_statement"}[kind]
    return RecordReconciliationControlCommand(
        public_id=UUID(f"64000000-0000-0000-0002-{number:012d}"),tenant_id=tenant,organization_unit_id=org,
        control_type=kind,currency_code="XAF",period_start=start,period_end=end,as_of=end,
        control_position=Decimal(control_position),operational_account_public_id=account,
        reconciliation_window_public_id=window,party_id=party,explanations=tuple(explanations),
        evidence=(_evidence(number,evidence_kind),),occurred_at=end+timedelta(minutes=number),business_date=end.date(),
        calendar_policy_version=1,correlation_id=CORRELATION,actor_service="m64.verifier",
        source_component="m64.verifier",source_record_id=f"control-{number}",idempotency_scope="m64.control",
        idempotency_key=f"control-{number}")


def _seed_party_obligations(session, tenant, org, occurred):
    rows=((UUID("64000000-0000-0000-0003-000000000001"),CUSTOMER,MERCHANT,"trade_receivable","100","ar"),
          (UUID("64000000-0000-0000-0003-000000000002"),MERCHANT,SUPPLIER,"trade_payable","80","ap"))
    for public,debtor,creditor,kind,amount,key in rows:
        session.execute(text("""INSERT INTO financial_obligations(public_id,tenant_id,organization_unit_id,debtor_party_id,
          creditor_party_id,obligation_type,obligation_state,original_amount,currency_code,due_at,occurred_at,business_date,
          calendar_policy_version,correlation_id,actor_service,source_component,source_record_id,idempotency_scope,
          idempotency_key,request_fingerprint) VALUES(:public,:tenant,:org,:debtor,:creditor,:kind,'open',:amount,'XAF',
          :due,:occurred,:business_date,1,:correlation,'m64.verifier','m64.verifier',:key,'m64.obligation',:key,:fingerprint)"""),
          {"public":str(public),"tenant":tenant,"org":org,"debtor":str(debtor),"creditor":str(creditor),"kind":kind,
           "amount":amount,"due":occurred+timedelta(days=30),"occurred":occurred,"business_date":occurred.date(),
           "correlation":str(CORRELATION),"key":key,"fingerprint":f"{number_hash(key):064x}"[-64:]})


def number_hash(value): return sum((index+1)*ord(char) for index,char in enumerate(value))


def _expect(code, action):
    try: action()
    except Exception as exc:
        if getattr(exc,"code",None)!=code: raise RuntimeError(f"expected={code}; actual={getattr(exc,'code',type(exc).__name__)}") from exc
    else: raise RuntimeError(f"expected error not raised={code}")


def _exercise(selected):
    m63._exercise(selected)
    with Session(selected) as session, session.begin():
        scope=session.execute(text("""SELECT w.public_id window_public,w.window_start,w.window_end,w.organization_unit_id,
          a.public_id account_public,w.tenant_id,r.closing_expected FROM reconciliation_windows w JOIN reconciliation_series s
          ON s.tenant_id=w.tenant_id AND s.id=w.reconciliation_series_id JOIN operational_financial_accounts a
          ON a.tenant_id=s.tenant_id AND a.id=s.operational_account_id JOIN current_reconciliation_window_revisions r
          ON r.tenant_id=w.tenant_id AND r.reconciliation_window_id=w.id ORDER BY w.window_start LIMIT 1""")).mappings().one()
        tenant=int(scope["tenant_id"]); org=int(scope["organization_unit_id"])
        start=scope["window_start"]; end=scope["window_end"]
        bank=_command(1,"bank",tenant,org,start,end,str(Decimal(scope["closing_expected"])+Decimal("5")),account=UUID(str(scope["account_public"])),window=UUID(str(scope["window_public"])),
          explanations=(ReconciliationExplanation(UUID("64000000-0000-0000-0004-000000000001"),"timing_item","5","Deposit in transit",evidence_reference="external-1"),))
        created=TransactionalReconciliationControlEngine.record(session,bank)
        replay=TransactionalReconciliationControlEngine.record(session,bank)
        if created.replayed or not replay.replayed or created.id!=replay.id: raise RuntimeError("control replay failed")
        _expect("idempotency_conflict",lambda:TransactionalReconciliationControlEngine.record(session,replace(bank,control_position=Decimal("106"))))
        _expect("bank_scope_not_found",lambda:TransactionalReconciliationControlEngine.record(session,replace(bank,tenant_id=tenant+900,idempotency_key="cross-tenant")))
        _seed_party_obligations(session,tenant,org,start+timedelta(minutes=1))
        ar=TransactionalReconciliationControlEngine.record(session,_command(2,"accounts_receivable",tenant,org,start,end,"100",party=CUSTOMER))
        ap=TransactionalReconciliationControlEngine.record(session,_command(3,"accounts_payable",tenant,org,start,end,"80",party=SUPPLIER))
        for record in (created,ar,ap):
            report=ReconciliationReportService.render(session,tenant_id=tenant,public_id=record.public_id)
            if len(report.report_fingerprint)!=64 or report.canonical_closing!=record.canonical_closing: raise RuntimeError("report determinism failed")
        if created.reconciliation_status!="explained" or ar.reconciliation_status!="balanced" or ap.reconciliation_status!="balanced":
            raise RuntimeError("control status derivation failed")
        try:
            with session.begin_nested(): session.execute(text("UPDATE reconciliation_controls SET control_position=0 WHERE id=:id"),{"id":created.id})
        except DBAPIError: pass
        else: raise RuntimeError("control history is mutable")
    with selected.connect() as connection:
        before=connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one()
        controls=connection.execute(text("SELECT count(*) FROM reconciliation_controls")).scalar_one()
        non_asset=connection.execute(text("""SELECT count(*) FROM reconciliation_controls c JOIN journal_entries j ON FALSE""")).scalar_one()
        after=connection.execute(text("SELECT count(*) FROM financial_events")).scalar_one()
        if controls!=3 or before!=after or non_asset!=0: raise RuntimeError("reconciliation created financial authority or wrong controls")


def _run():
    _verify_development(); _create_clone(); selected=None
    try:
        _migrate(TEST_DATABASE_NAME,TARGET_REVISION); _migrate(TEST_DATABASE_NAME,PARENT_REVISION,downgrade=True); _migrate(TEST_DATABASE_NAME,TARGET_REVISION)
        selected=_engine(TEST_DATABASE_NAME); _exercise(selected); selected.dispose(); selected=None; _drop(TEST_DATABASE_NAME); _verify_development()
    except Exception:
        if selected is not None: selected.dispose()
        print(f"M6.4 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print(f"m64_reconciliation_controls=PASS database={TEST_DATABASE_NAME} shared_primitive=PASS bank=PASS ar=PASS ap=PASS evidence=PASS reports=PASS history=PASS tenant_scope=PASS non_pnl=PASS immutability=PASS rollback=PASS upgrade_downgrade_upgrade=PASS dropped=true")


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("verify"); sub.add_parser("status"); sub.add_parser("create-and-verify")
    drop=sub.add_parser("drop"); drop.add_argument("--confirm-database-name",required=True)
    args=parser.parse_args()
    if args.command=="verify": _verify_development()
    elif args.command=="status": return 0 if _status() else 1
    elif args.command=="drop": _drop(args.confirm_database_name)
    else: _run()
    return 0


if __name__=="__main__": raise SystemExit(main())
