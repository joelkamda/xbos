"""Read-only development gate and disposable M4.3 settlement rehearsal."""

from __future__ import annotations

import argparse
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
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand, TransitionPaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand, PaymentCommandIdempotencyConflict
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_contract import (
    CreatePaymentSettlementCommand, PaymentSettlementValidationError,
    ReversePaymentSettlementCommand, TransitionPaymentSettlementCommand,
)
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.payment_settlement_repository import PaymentSettlementRepository
from core.persistence.m40_payment_foundation import FOUNDATION_TABLES
from core.persistence.m43_payment_settlements import (
    FORBIDDEN_SIDE_EFFECT_TABLES, M43_COLUMNS, M43_TABLES, M43_TRIGGERS,
    PARENT_REVISION, TARGET_REVISION, TEST_DATABASE_NAME,
)
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
BASE = datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)


def _url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _engine(name, *, isolation_level=None):
    return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


def _database_exists(name):
    engine = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally: engine.dispose()


def _create_clone():
    if _database_exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose(); admin = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally: admin.dispose()


def _drop_database(name):
    if name != TEST_DATABASE_NAME: raise RuntimeError(f"unsafe disposable database target={name}")
    admin = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally: admin.dispose()


@contextmanager
def _migration_database(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try: yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous


def _migrate(name, revision, *, downgrade=False):
    with _migration_database(name):
        config = Config(str(ROOT / "alembic.ini"))
        (alembic_command.downgrade if downgrade else alembic_command.upgrade)(config, revision)


def _revision(connection): return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _schema(connection, expected):
    tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
    columns = set(connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='payment_settlements'")).scalars())
    triggers = set(connection.execute(text("SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal")).scalars())
    if expected:
        if set(M43_TABLES)-tables or set(M43_COLUMNS)-columns or set(M43_TRIGGERS)-triggers:
            raise RuntimeError("M4.3 schema inventory is incomplete")
    elif set(M43_TABLES)&tables or set(M43_COLUMNS)&columns or set(M43_TRIGGERS)&triggers:
        raise RuntimeError("M4.3 schema remains at parent revision")


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}: raise RuntimeError(f"unexpected development revision={revision}")
        for table in FOUNDATION_TABLES:
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one(): raise RuntimeError(f"development payment table is not empty={table}")
        for table in ("idempotency_records", "value_sources", "financial_events", "outbox_messages", "journal_entries", "journal_lines"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one(): raise RuntimeError(f"development side-effect table is not empty={table}")
        _schema(connection, revision == TARGET_REVISION)
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={revision}"); print("m43_payment_settlements_development=PASS")
    return revision


def _status():
    exists = _database_exists(TEST_DATABASE_NAME); print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}"); return not exists


def _seed_scope(session):
    tenant = int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    organization = session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:t ORDER BY id LIMIT 1"), {"t": tenant}).scalar_one_or_none()
    if organization is None:
        organization = session.execute(text("INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active) VALUES(:t,'branch','m43-verifier','M4.3 Verifier','Africa/Douala',true) RETURNING id"), {"t": tenant}).scalar_one()
    provider = session.execute(text("""
        INSERT INTO payment_provider_accounts(tenant_id,organization_unit_id,provider_code,external_account_reference,credential_reference,environment,active)
        VALUES(:t,:o,'mtn_momo','m43-sandbox-account','secret://m43','sandbox',true)
        ON CONFLICT(provider_code,environment,external_account_reference) DO UPDATE SET active=true RETURNING id,public_id
    """), {"t": tenant, "o": organization}).mappings().one()
    mobile = session.execute(text("""
        INSERT INTO operational_financial_accounts(public_id,tenant_id,organization_unit_id,account_class,account_type,code,display_name,currency_code,channel_code,aggregation_role,reconciliation_enabled,active,opened_at)
        VALUES('43000000-0000-0000-0000-000000000010',:t,:o,'treasury','mobile_money','m43-mobile','M4.3 Mobile','XAF','mtn_momo','leaf',true,true,:opened)
        ON CONFLICT(tenant_id,organization_unit_id,code) DO UPDATE SET active=true RETURNING id,public_id
    """), {"t": tenant, "o": organization, "opened": BASE}).mappings().one()
    cash = session.execute(text("""
        INSERT INTO operational_financial_accounts(public_id,tenant_id,organization_unit_id,account_class,account_type,code,display_name,currency_code,channel_code,aggregation_role,reconciliation_enabled,active,opened_at)
        VALUES('43000000-0000-0000-0000-000000000011',:t,:o,'treasury','cash','m43-cash','M4.3 Cash','XAF','cash','leaf',true,true,:opened)
        ON CONFLICT(tenant_id,organization_unit_id,code) DO UPDATE SET active=true RETURNING id,public_id
    """), {"t": tenant, "o": organization, "opened": BASE}).mappings().one()
    return tenant, int(organization), UUID(str(provider["public_id"])), UUID(str(mobile["public_id"])), UUID(str(cash["public_id"]))


def _intent(tenant, organization, number, amount="100", methods=None):
    return CreatePaymentIntentCommand(
        public_id=UUID(f"43000000-0000-0000-0000-{number:012d}"), tenant_id=tenant, organization_unit_id=organization,
        requested_amount=Decimal(amount), currency_code="XAF",
        payment_method_policy={"allowed_methods": methods or ["mobile_money"], "max_tenders": 1},
        expires_at=BASE+timedelta(hours=3), occurred_at=BASE, business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=UUID("43000000-0000-0000-0000-000000000099"), actor_service="m43.verifier",
        source_component="m43.verifier", source_record_id=f"intent-{number}", idempotency_scope="m43.intent", idempotency_key=f"intent-{number}")


def _attempt(tenant, organization, provider, intent_number, number, amount="100"):
    occurred=BASE+timedelta(minutes=number)
    return CreatePaymentAttemptCommand(
        public_id=UUID(f"43000000-0000-0000-0001-{number:012d}"), tenant_id=tenant, organization_unit_id=organization,
        payment_intent_public_id=UUID(f"43000000-0000-0000-0000-{intent_number:012d}"), attempted_amount=Decimal(amount), currency_code="XAF",
        payment_method_code="mobile_money", payment_rail_code="mtn_momo", orchestrator_code="xbos_direct",
        provider_account_public_id=provider, underlying_provider_code="mtn_momo", timeout_at=occurred+timedelta(minutes=10),
        occurred_at=occurred, business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=UUID("43000000-0000-0000-0000-000000000099"), actor_service="m43.verifier",
        source_component="m43.verifier", source_record_id=f"attempt-{number}", idempotency_scope="m43.attempt", idempotency_key=f"attempt-{number}")


def _attempt_transition(command, version, state, key, minute, evidence=None, failure=None):
    return TransitionPaymentAttemptCommand(
        tenant_id=command.tenant_id, organization_unit_id=command.organization_unit_id,
        payment_attempt_public_id=command.public_id, expected_row_version=version, target_state=state,
        reason_code=key, external_attempt_reference=f"m43-attempt-ref-{command.public_id.int % 1000}", failure_code=failure,
        evidence_payload=evidence or {}, occurred_at=BASE+timedelta(minutes=minute), business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=command.correlation_id, actor_service="m43.verifier", source_component="m43.verifier",
        source_record_id=key, idempotency_scope="m43.attempt.transition", idempotency_key=key)


def _settlement(tenant, organization, intent_number, number, account, *, attempt=None, direction="incoming", method="mobile_money", rail="mtn_momo", amount="100"):
    return CreatePaymentSettlementCommand(
        public_id=UUID(f"43000000-0000-0000-0002-{number:012d}"), tenant_id=tenant, organization_unit_id=organization,
        payment_intent_public_id=UUID(f"43000000-0000-0000-0000-{intent_number:012d}"),
        payment_attempt_public_id=attempt.public_id if attempt else None, operational_account_public_id=account,
        settlement_direction=direction, gross_amount=Decimal(amount), fee_amount=Decimal("0"), net_amount=Decimal(amount),
        currency_code="XAF", payment_method_code=method, payment_rail_code=rail,
        value_date=date(2026,8,10), occurred_at=BASE+timedelta(minutes=30+number), business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=UUID("43000000-0000-0000-0000-000000000099"), actor_service="m43.verifier",
        source_component="m43.verifier", source_record_id=f"settlement-{number}", idempotency_scope="m43.settlement", idempotency_key=f"settlement-{number}")


def _settlement_transition(command, state, key, *, reference=None, failure=None):
    return TransitionPaymentSettlementCommand(
        tenant_id=command.tenant_id, organization_unit_id=command.organization_unit_id,
        payment_settlement_public_id=command.public_id, expected_row_version=1, target_state=state,
        finality_status="final" if state=="confirmed" else "rejected",
        availability_state="available" if state=="confirmed" else "unavailable", reason_code=key,
        failure_code=failure, external_settlement_reference=reference,
        evidence_payload={"provider_status": state, "evidence_id": key},
        occurred_at=command.occurred_at+timedelta(minutes=1), business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=command.correlation_id, actor_service="m43.verifier", source_component="m43.verifier",
        source_record_id=key, idempotency_scope="m43.settlement.transition", idempotency_key=key)


def _reversal(command, number, amount):
    return ReversePaymentSettlementCommand(
        public_id=UUID(f"43000000-0000-0000-0003-{number:012d}"), tenant_id=command.tenant_id,
        organization_unit_id=command.organization_unit_id, payment_settlement_public_id=command.public_id,
        reversal_amount=Decimal(amount), currency_code="XAF", reason_code="provider_reversal",
        occurred_at=command.occurred_at+timedelta(minutes=10+number), business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=command.correlation_id, actor_service="m43.verifier", source_component="m43.verifier",
        source_record_id=f"reversal-{number}", idempotency_scope="m43.reversal", idempotency_key=f"reversal-{number}")


def _exercise(engine):
    with Session(engine) as session, session.begin():
        tenant, organization, provider, mobile, cash = _seed_scope(session)
        intents=[_intent(tenant,organization,1,"100"),_intent(tenant,organization,2,"50"),_intent(tenant,organization,3,"25",["cash"])]
        for intent in intents: TransactionalPaymentIntentEngine.create_intent(session,intent)
        attempts=[_attempt(tenant,organization,provider,1,1,"100"),_attempt(tenant,organization,provider,2,2,"50")]
        for index, attempt in enumerate(attempts, start=1):
            TransactionalPaymentAttemptEngine.create(session,attempt)
            TransactionalPaymentAttemptEngine.transition(session,_attempt_transition(attempt,1,"processing",f"attempt_{index}_processing",10+index))
            TransactionalPaymentAttemptEngine.transition(session,_attempt_transition(attempt,2,"succeeded",f"attempt_{index}_succeeded",20+index,{"provider_status":"success"}))

        incoming=_settlement(tenant,organization,1,1,mobile,attempt=attempts[0])
        created=TransactionalPaymentSettlementEngine.create(session,incoming); replay=TransactionalPaymentSettlementEngine.create(session,incoming)
        if created.replayed or not replay.replayed: raise RuntimeError("settlement creation replay failed")
        try: TransactionalPaymentSettlementEngine.create(session,replace(incoming,gross_amount=Decimal("99"),net_amount=Decimal("99")))
        except PaymentCommandIdempotencyConflict: pass
        else: raise RuntimeError("settlement idempotency conflict was accepted")
        confirmed=_settlement_transition(incoming,"confirmed","incoming_confirmed",reference="provider-settlement-001")
        result=TransactionalPaymentSettlementEngine.transition(session,confirmed); replayed=TransactionalPaymentSettlementEngine.transition(session,confirmed)
        if result.replayed or not replayed.replayed: raise RuntimeError("settlement transition replay failed")

        failed=_settlement(tenant,organization,2,2,mobile,attempt=attempts[1],amount="50")
        TransactionalPaymentSettlementEngine.create(session,failed)
        TransactionalPaymentSettlementEngine.transition(session,_settlement_transition(failed,"failed","incoming_failed",failure="provider_rejected"))

        outgoing=_settlement(tenant,organization,3,3,cash,direction="outgoing",method="cash",rail="cash",amount="25")
        TransactionalPaymentSettlementEngine.create(session,outgoing)
        TransactionalPaymentSettlementEngine.transition(session,_settlement_transition(outgoing,"confirmed","cash_confirmed"))

        partial=_reversal(incoming,1,"40"); full=_reversal(incoming,2,"60")
        TransactionalPaymentSettlementEngine.reverse(session,partial)
        partial_replay=TransactionalPaymentSettlementEngine.reverse(session,partial)
        if not partial_replay.replayed: raise RuntimeError("settlement reversal replay failed")
        TransactionalPaymentSettlementEngine.reverse(session,full)
        try: TransactionalPaymentSettlementEngine.reverse(session,_reversal(incoming,3,"1"))
        except PaymentSettlementValidationError as exc:
            if exc.code not in {"settlement_not_reversible","reversal_capacity_exceeded"}: raise
        else: raise RuntimeError("over-capacity reversal was accepted")
        if PaymentSettlementRepository.find_settlement(session,tenant_id=tenant+100000,public_id=incoming.public_id) is not None:
            raise RuntimeError("cross-tenant settlement lookup succeeded")

    with engine.connect() as connection:
        counts={"settlements":connection.execute(text("SELECT count(*) FROM payment_settlements")).scalar_one(),
                "transitions":connection.execute(text("SELECT count(*) FROM payment_settlement_transitions")).scalar_one(),
                "reversals":connection.execute(text("SELECT count(*) FROM payment_settlement_reversals")).scalar_one()}
        if counts!={"settlements":3,"transitions":8,"reversals":2}: raise RuntimeError(f"unexpected settlement counts={counts}")
        row=connection.execute(text("SELECT settlement_state,reversed_amount,value_date,recorded_at::date AS recorded_date FROM payment_settlements WHERE public_id=:id"),{"id":str(incoming.public_id)}).mappings().one()
        if row["settlement_state"]!="reversed" or Decimal(row["reversed_amount"])!=Decimal("100") or row["value_date"]==row["recorded_date"]:
            raise RuntimeError("settlement reversal or date semantics failed")
        failed_row=connection.execute(text("SELECT settlement_state,failure_code,evidence_payload FROM payment_settlements WHERE public_id=:id"),{"id":str(failed.public_id)}).mappings().one()
        if failed_row["settlement_state"]!="failed" or failed_row["failure_code"]!="provider_rejected" or not failed_row["evidence_payload"]:
            raise RuntimeError("failed settlement evidence was not preserved")
        for statement in (
            f"UPDATE payment_settlements SET gross_amount=1 WHERE public_id='{incoming.public_id}'",
            "UPDATE payment_settlement_transitions SET reason_code='changed' WHERE sequence_number=1",
            f"DELETE FROM payment_settlements WHERE public_id='{outgoing.public_id}'",
        ):
            try:
                with connection.begin_nested(): connection.exec_driver_sql(statement)
            except DBAPIError: pass
            else: raise RuntimeError("direct SQL settlement bypass succeeded")
        populated={table:connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FORBIDDEN_SIDE_EFFECT_TABLES}
        populated={k:v for k,v in populated.items() if v}
        if populated: raise RuntimeError(f"M4.3 created forbidden side effects={populated}")


def _create_and_verify():
    if _verify_development()!=PARENT_REVISION: raise RuntimeError(f"development must start at {PARENT_REVISION}")
    _create_clone(); disposable=None
    try:
        _migrate(TEST_DATABASE_NAME,TARGET_REVISION); disposable=_engine(TEST_DATABASE_NAME)
        with disposable.connect() as c:
            if _revision(c)!=TARGET_REVISION: raise RuntimeError("disposable did not reach M4.3")
            _schema(c,True)
        disposable.dispose(); disposable=None
        _migrate(TEST_DATABASE_NAME,PARENT_REVISION,downgrade=True); disposable=_engine(TEST_DATABASE_NAME)
        with disposable.connect() as c:
            if _revision(c)!=PARENT_REVISION: raise RuntimeError("disposable did not downgrade to M4.2")
            _schema(c,False)
        disposable.dispose(); disposable=None
        _migrate(TEST_DATABASE_NAME,TARGET_REVISION); disposable=_engine(TEST_DATABASE_NAME); _exercise(disposable)
        disposable.dispose(); disposable=None; _drop_database(TEST_DATABASE_NAME); _verify_development()
        print("m43_payment_settlements=PASS database="+TEST_DATABASE_NAME+" inbound=PASS outbound=PASS lifecycle=PASS provider_identity=PASS value_date=PASS failed_evidence=PASS replay=PASS conflict=PASS tenant_scope=PASS partial_full_reversal=PASS reversal_capacity=PASS immutability=PASS direct_sql=PASS side_effects=0 upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if disposable is not None: disposable.dispose()
        print(f"M4.3 verification failed; retained disposable database={TEST_DATABASE_NAME}"); raise


def main():
    parser=argparse.ArgumentParser(); commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("status"); commands.add_parser("verify"); commands.add_parser("create-and-verify")
    drop=commands.add_parser("drop"); drop.add_argument("--confirm-database-name",required=True); args=parser.parse_args()
    if args.command=="status": return 0 if _status() else 1
    if args.command=="verify": _verify_development()
    elif args.command=="create-and-verify": _create_and_verify()
    else:
        if args.confirm_database_name!=TEST_DATABASE_NAME: raise RuntimeError("exact disposable database confirmation is required")
        _drop_database(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__=="__main__": raise SystemExit(main())
