"""Verify schema-neutral M3.3 receipt and unapplied-value workflows."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from core.domain.finance.allocation_contract import CreateValueSourceCommand, ReverseAllocationCommand
from core.domain.finance.allocation_engine import TransactionalAllocationEngine
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand, ObligationIdempotencyConflict
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from core.domain.finance.value_application_contract import ApplyUnappliedValueCommand, ReceiveAndApplyValueCommand, ValueApplicationInstruction
from core.domain.finance.value_application_engine import TransactionalValueApplicationEngine
from core.domain.finance.value_source_balance_service import ValueSourceBalanceService
from database import engine as application_engine

TEST_DATABASE_NAME="xbos_track_b_m33_value_application_test"
DEVELOPMENT_DATABASE_NAME="xbos_track_b_dev"
TARGET_REVISION="m32_allocation_engine_009"
CANONICAL_HEAD="m34_obligation_aging_010"
DEVELOPMENT_REVISIONS={TARGET_REVISION,CANONICAL_HEAD}
TENANT=3301; ORG=3311; NOW=datetime(2026,8,9,14,tzinfo=timezone.utc)
CORRELATION=UUID("33000000-0000-0000-0000-000000000099")


def _application_url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _url(name): return _application_url().set(database=name)
def _engine(name,autocommit=False): return create_engine(_url(name),pool_pre_ping=True,**({"isolation_level":"AUTOCOMMIT"} if autocommit else {}))


def _exists(name):
    engine=_engine("postgres",True)
    try:
        with engine.connect() as c: return bool(c.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"),{"name":name}).scalar_one_or_none())
    finally: engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine=_engine("postgres",True)
    try:
        with engine.connect() as c: c.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally: engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME: raise RuntimeError(f"refusing unapproved database: {name}")
    engine=_engine("postgres",True)
    try:
        with engine.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),{"name":name})
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally: engine.dispose()


@contextmanager
def _selected(name):
    previous=os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"]=_url(name).render_as_string(hide_password=False)
    try: yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL",None)
        else: os.environ["DATABASE_URL"]=previous


def _upgrade():
    with _selected(TEST_DATABASE_NAME): alembic_command.upgrade(Config(str(ROOT/"alembic.ini")),TARGET_REVISION)


def _seed(engine):
    with engine.begin() as c:
        c.execute(text("""INSERT INTO tenants (id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
          VALUES (:tenant,'M33T','M3.3 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)"""),{"tenant":TENANT})
        c.execute(text("""INSERT INTO currency_assets (code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata)
          VALUES ('XAF','fiat','Central African CFA franc',0,8,TRUE,'{}'::jsonb)"""))
        c.execute(text("""INSERT INTO organization_units (id,tenant_id,unit_type,code,name,timezone_name,active)
          VALUES (:org,:tenant,'legal_entity','M33','M3.3 Entity','Africa/Douala',TRUE)"""),{"org":ORG,"tenant":TENANT})


def _obligation(public_id,amount,key):
    return CreateObligationCommand(public_id=public_id,tenant_id=TENANT,organization_unit_id=ORG,
      debtor_party_id=UUID("33000000-0000-0000-0000-000000000010"),creditor_party_id=UUID("33000000-0000-0000-0000-000000000011"),
      obligation_type="trade_receivable",original_amount=Decimal(amount),currency_code="XAF",due_at=NOW+timedelta(days=30),
      occurred_at=NOW,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=CORRELATION,
      actor_service="m33.verifier",source_component="m33.verifier",source_record_id=key,
      idempotency_scope="m33.obligation",idempotency_key=key,
      lines=(ObligationLineCommand(1,"principal","Principal",Decimal("1"),Decimal(amount),Decimal(amount),key+"-line"),))


def _source(public_id,amount,key,source_type="payment"):
    return CreateValueSourceCommand(public_id=public_id,tenant_id=TENANT,organization_unit_id=ORG,
      owner_party_id=UUID("33000000-0000-0000-0000-000000000010"),source_type=source_type,source_amount=Decimal(amount),
      currency_code="XAF",occurred_at=NOW,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=CORRELATION,
      actor_service="m33.verifier",source_component="m33.verifier",source_record_id=key,
      idempotency_scope="m33.receipt",idempotency_key=key)


def _instruction(allocation_id,obligation_id,key,amount=None):
    return ValueApplicationInstruction(allocation_public_id=allocation_id,obligation_public_id=obligation_id,
      exact_amount=Decimal(amount) if amount else None,source_record_id=key,idempotency_key=key)


def _batch(source_id,instructions,key="apply"):
    return ApplyUnappliedValueCommand(tenant_id=TENANT,value_source_public_id=source_id,occurred_at=NOW,
      business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=CORRELATION,
      source_component="m33.verifier",idempotency_scope=f"m33.{key}",applications=tuple(instructions),actor_service="m33.verifier")


def _exercise(engine):
    o1=UUID("33000000-0000-0000-0000-000000000101"); o2=UUID("33000000-0000-0000-0000-000000000102")
    deposit=UUID("33000000-0000-0000-0000-000000000201")
    a1=UUID("33000000-0000-0000-0000-000000000301"); a2=UUID("33000000-0000-0000-0000-000000000302")
    with Session(engine) as session,session.begin():
        TransactionalObligationEngine.create(session,_obligation(o1,"600","o1"))
        TransactionalObligationEngine.create(session,_obligation(o2,"300","o2"))
        receipt=ReceiveAndApplyValueCommand(_source(deposit,"1000","deposit","customer_deposit"))
        result=TransactionalValueApplicationEngine.receive(session,receipt)
        assert result.disposition=="unapplied" and result.balance.available_amount==Decimal("1000")

        first_batch=_batch(deposit,(_instruction(a1,o1,"a1"),),"apply1")
        first=TransactionalValueApplicationEngine.apply_existing(session,first_batch)
        assert first.disposition=="overpayment_residual" and first.balance.available_amount==Decimal("400")
        replay=TransactionalValueApplicationEngine.apply_existing(session,first_batch)
        assert replay.replayed and replay.outcomes[0].allocation.public_id==a1
        altered=_batch(deposit,(_instruction(a1,o1,"a1","500"),),"apply1")
        try: TransactionalValueApplicationEngine.apply_existing(session,altered)
        except ObligationIdempotencyConflict: pass
        else: raise RuntimeError("altered application replay did not conflict")

        second=TransactionalValueApplicationEngine.apply_existing(session,_batch(deposit,(_instruction(a2,o2,"a2","300"),),"apply2"))
        assert second.balance.available_amount==Decimal("100") and second.balance.disposition=="partially_applied"

        reversal=ReverseAllocationCommand(public_id=UUID("33000000-0000-0000-0000-000000000401"),tenant_id=TENANT,
          organization_unit_id=ORG,payment_allocation_public_id=a2,reversal_amount=Decimal("100"),currency_code="XAF",
          reason_code="customer_refund",occurred_at=NOW,business_date=date(2026,8,9),calendar_policy_version=1,
          correlation_id=CORRELATION,actor_service="m33.verifier",source_component="m33.verifier",source_record_id="r1",
          idempotency_scope="m33.reverse",idempotency_key="r1")
        TransactionalAllocationEngine.reverse(session,reversal)
        reopened=ValueSourceBalanceService.get(session,tenant_id=TENANT,value_source_public_id=deposit)
        assert reopened.available_amount==Decimal("200")

        source_count=session.execute(text("SELECT count(*) FROM value_sources")).scalar_one()
        allocation_count=session.execute(text("SELECT count(*) FROM payment_allocations")).scalar_one()
        assert (source_count,allocation_count)==(1,2)

    # Receive and auto-apply an overpayment atomically.
    o3=UUID("33000000-0000-0000-0000-000000000103"); source2=UUID("33000000-0000-0000-0000-000000000202")
    a3=UUID("33000000-0000-0000-0000-000000000303")
    with Session(engine) as session,session.begin():
        TransactionalObligationEngine.create(session,_obligation(o3,"100","o3"))
        command=ReceiveAndApplyValueCommand(_source(source2,"150","overpay"),_batch(source2,(_instruction(a3,o3,"a3"),),"overpay"))
        result=TransactionalValueApplicationEngine.receive(session,command)
        assert result.disposition=="overpayment_residual" and result.balance.available_amount==Decimal("50")

    # One new receipt splits atomically across two obligations.
    o4=UUID("33000000-0000-0000-0000-000000000104"); o5=UUID("33000000-0000-0000-0000-000000000105")
    source3=UUID("33000000-0000-0000-0000-000000000203")
    with Session(engine) as session,session.begin():
        TransactionalObligationEngine.create(session,_obligation(o4,"50","o4"))
        TransactionalObligationEngine.create(session,_obligation(o5,"100","o5"))
        split=_batch(source3,(
          _instruction(UUID("33000000-0000-0000-0000-000000000304"),o4,"a4","50"),
          _instruction(UUID("33000000-0000-0000-0000-000000000305"),o5,"a5")),"split")
        result=TransactionalValueApplicationEngine.receive(session,ReceiveAndApplyValueCommand(_source(source3,"150","split"),split))
        assert result.balance.disposition=="fully_applied" and [o.applied_amount for o in result.outcomes]==[Decimal("50"),Decimal("100")]

    # Caller rollback removes receipt, allocations, and their idempotency records.
    transient=UUID("33000000-0000-0000-0000-000000000299")
    with Session(engine) as session:
        tx=session.begin(); TransactionalValueApplicationEngine.receive(session,ReceiveAndApplyValueCommand(_source(transient,"10","rollback"))); tx.rollback()
        assert session.execute(text("SELECT count(*) FROM value_sources WHERE public_id=:id"),{"id":str(transient)}).scalar_one()==0

    # Tenant scope never leaks a value source.
    with Session(engine) as session:
        try: ValueSourceBalanceService.get(session,tenant_id=TENANT+1,value_source_public_id=deposit)
        except Exception as exc:
            if getattr(exc,"code",None)!="value_source_not_found": raise
        else: raise RuntimeError("tenant isolation failed")


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected {DEVELOPMENT_DATABASE_NAME}")
    config=Config(str(ROOT/"alembic.ini")); heads=ScriptDirectory.from_config(config).get_heads()
    if heads != [CANONICAL_HEAD]: raise RuntimeError(f"canonical heads differ: {heads}")
    zero_tables=("financial_dimension_types","financial_dimension_values","posting_dimension_policies","idempotency_records",
      "financial_events","outbox_messages","journal_entries","journal_lines","financial_obligations","financial_obligation_lines",
      "value_sources","payment_allocations","allocation_reversals","allocation_scope_policies")
    with application_engine.connect() as c:
        revision=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision not in DEVELOPMENT_REVISIONS: raise RuntimeError(f"unexpected development revision: {revision}")
        if c.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one()!=20: raise RuntimeError("catalog count differs")
        for table in zero_tables:
            count=c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count: raise RuntimeError(f"development table is not empty: {table}={count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={revision}"); print("m33_value_application_development=PASS")


def _create_and_verify():
    _development_verify(); _create(); engine=None
    try:
        _upgrade(); engine=_engine(TEST_DATABASE_NAME); _seed(engine); _exercise(engine); engine.dispose(); engine=None
        _drop(TEST_DATABASE_NAME); _development_verify()
        print("m33_value_application=PASS database=xbos_track_b_m33_value_application_test canonical_head_unchanged=PASS deposit=PASS later_application=PASS receive_apply=PASS overpayment=PASS split=PASS replay=PASS conflict=PASS reversal_reopens=PASS tenant_isolation=PASS rollback=PASS dropped=true")
    except Exception:
        if engine is not None: engine.dispose()
        print(f"M3.3 verification failed; retained disposable database={TEST_DATABASE_NAME}",file=sys.stderr); raise


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("status"); sub.add_parser("verify"); sub.add_parser("create-and-verify")
    drop=sub.add_parser("drop"); drop.add_argument("--confirm-database-name",required=True); args=parser.parse_args()
    if args.command=="status": print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command=="verify": _development_verify()
    elif args.command=="drop": _drop(args.confirm_database_name); print(f"dropped={args.confirm_database_name}")
    else: _create_and_verify()
    return 0


if __name__=="__main__": raise SystemExit(main())
