"""Single disposable acceptance rehearsal for grouped M5.0 receivable lifecycles."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from core.domain.finance.aging_contract import AsOfAgingQuery
from core.domain.finance.allocation_contract import AllocationValidationError, CreateValueSourceCommand
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.receivable_balance_service import CustomerReceivableBalanceService
from core.domain.finance.receivable_contract import (
    AgeReceivablesCommand,
    ApplyCustomerValueCommand,
    IssueCustomerValueCommand,
    OpenReceivableCommand,
    ReceiveReceivablePaymentCommand,
    ReceivableLifecycleError,
)
from core.domain.finance.receivable_engine import TransactionalReceivableLifecycleEngine
from core.domain.finance.value_application_contract import (
    ApplyUnappliedValueCommand,
    ReceiveAndApplyValueCommand,
    ValueApplicationInstruction,
)
from database import engine as application_engine


DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m50_receivables_test"
TARGET_REVISION = "m46_provider_financials_015"
TENANT = 5001
ORG = 5011
CUSTOMER = UUID("50000000-0000-0000-0000-000000000010")
MERCHANT = UUID("50000000-0000-0000-0000-000000000011")
OTHER_CUSTOMER = UUID("50000000-0000-0000-0000-000000000012")
CORRELATION = UUID("50000000-0000-0000-0000-000000000099")
R1 = UUID("50000000-0000-0000-0000-000000000101")
R2 = UUID("50000000-0000-0000-0000-000000000102")
R3 = UUID("50000000-0000-0000-0000-000000000103")
P1 = UUID("50000000-0000-0000-0000-000000000201")
P2 = UUID("50000000-0000-0000-0000-000000000202")
CREDIT = UUID("50000000-0000-0000-0000-000000000203")
DEPOSIT = UUID("50000000-0000-0000-0000-000000000204")
ADVANCE = UUID("50000000-0000-0000-0000-000000000205")

EMPTY_TABLES = (
    "canonical_payment_requests", "canonical_payment_intents", "canonical_payment_tenders",
    "payment_tender_transitions", "canonical_payment_attempts",
    "canonical_payment_attempt_transitions", "provider_callback_events", "payment_settlements",
    "payment_settlement_transitions", "payment_settlement_reversals",
    "provider_settlement_components", "payment_provider_accounts", "idempotency_records",
    "kernel_source_records", "financial_events", "outbox_messages", "journal_entries",
    "journal_lines", "financial_obligations", "financial_obligation_lines", "value_sources",
    "payment_allocations", "allocation_reversals", "financial_dimension_types",
    "financial_dimension_values", "posting_dimension_policies",
)


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _url(database_name):
    return _application_url().set(database=database_name)


def _engine(database_name, *, autocommit=False):
    options = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    return create_engine(_url(database_name), pool_pre_ping=True, **options)


def _exists(database_name):
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database_name}
            ).scalar_one_or_none())
    finally:
        engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally:
        engine.dispose()


def _drop(database_name):
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"refusing unapproved database: {database_name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@contextmanager
def _selected(database_name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(database_name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _upgrade():
    with _selected(TEST_DATABASE_NAME):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)


def _seed(engine):
    with engine.begin() as connection:
        connection.execute(text("""
          INSERT INTO tenants(id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
          VALUES(:tenant,'M50T','M5.0 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)
        """), {"tenant": TENANT})
        connection.execute(text("""
          INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata)
          VALUES('XAF','fiat','CFA Franc',0,8,TRUE,'{}'::jsonb)
        """))
        connection.execute(text("""
          INSERT INTO organization_units(id,tenant_id,unit_type,code,name,timezone_name,active)
          VALUES(:org,:tenant,'legal_entity','M50','M5.0 Entity','Africa/Douala',TRUE)
        """), {"org": ORG, "tenant": TENANT})


def _receivable(public_id, amount, key, base, due_days, customer=CUSTOMER):
    return OpenReceivableCommand(CreateObligationCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=ORG,
        debtor_party_id=customer, creditor_party_id=MERCHANT, obligation_type="trade_receivable",
        original_amount=Decimal(amount), currency_code="XAF", due_at=base + timedelta(days=due_days),
        occurred_at=base, business_date=base.date(), calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m50.verifier", source_component="m50.verifier",
        source_record_id=key, idempotency_scope="m50.receivable", idempotency_key=key,
        lines=(ObligationLineCommand(1, "principal", "Customer receivable", 1, amount, amount, key + "-line"),),
    ))


def _value(public_id, kind, amount, key, occurred, owner=CUSTOMER):
    return CreateValueSourceCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=ORG, owner_party_id=owner,
        source_type=kind, source_amount=Decimal(amount), currency_code="XAF",
        occurred_at=occurred, business_date=occurred.date(), calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m50.verifier", source_component="m50.verifier",
        source_record_id=key, idempotency_scope="m50.value", idempotency_key=key,
    )


def _application(source, obligation, allocation, amount, key, occurred):
    return ApplyUnappliedValueCommand(
        tenant_id=TENANT, value_source_public_id=source, occurred_at=occurred,
        business_date=occurred.date(), calendar_policy_version=1, correlation_id=CORRELATION,
        source_component="m50.verifier", idempotency_scope="m50.application",
        actor_service="m50.verifier", applications=(ValueApplicationInstruction(
            allocation_public_id=allocation, obligation_public_id=obligation,
            source_record_id=key, idempotency_key=key, exact_amount=Decimal(amount) if amount else None,
        ),),
    )


def _receive_payment(source, amount, target, allocation, apply_amount, key, occurred, owner=CUSTOMER):
    value = _value(source, "payment", amount, key + "-source", occurred, owner)
    application = _application(source, target, allocation, apply_amount, key + "-apply", occurred)
    return ReceiveReceivablePaymentCommand(ReceiveAndApplyValueCommand(value, application))


def _issue_and_apply(session, source_id, kind, amount, target, allocation_id, key, occurred):
    TransactionalReceivableLifecycleEngine.issue_customer_value(
        session, IssueCustomerValueCommand(_value(source_id, kind, amount, key + "-source", occurred))
    )
    return TransactionalReceivableLifecycleEngine.apply_customer_value(
        session, ApplyCustomerValueCommand(_application(
            source_id, target, allocation_id, amount, key + "-apply", occurred
        ))
    )


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != TARGET_REVISION:
            raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20:
            raise RuntimeError("canonical event catalog count differs")
        for table in EMPTY_TABLES:
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count:
                raise RuntimeError(f"development table not empty: {table}={count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m50_receivables_development=PASS canonical_head_unchanged=PASS development_empty=PASS")


def _exercise(engine):
    base = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        for command in (
            _receivable(R1, "100", "r1", base, 5),
            _receivable(R2, "80", "r2", base, 30),
            _receivable(R3, "50", "r3", base, 1),
        ):
            TransactionalReceivableLifecycleEngine.open(session, command)

        partial = _receive_payment(
            P1, "40", R1, UUID("50000000-0000-0000-0000-000000000301"), "40", "p1",
            base + timedelta(days=2),
        )
        partial_result = TransactionalReceivableLifecycleEngine.receive_payment(session, partial)
        replay = TransactionalReceivableLifecycleEngine.receive_payment(session, partial)
        if partial_result.replayed or not replay.replayed:
            raise RuntimeError("payment replay semantics failed")

        later = _receive_payment(
            P2, "90", R1, UUID("50000000-0000-0000-0000-000000000302"), None, "p2",
            base + timedelta(days=4),
        )
        later_result = TransactionalReceivableLifecycleEngine.receive_payment(session, later)
        if later_result.balance.available_amount != Decimal("30"):
            raise RuntimeError("overpayment residual differs")

        _issue_and_apply(session, CREDIT, "customer_credit", "20", R2,
                         UUID("50000000-0000-0000-0000-000000000303"), "credit", base + timedelta(days=5))
        _issue_and_apply(session, DEPOSIT, "customer_deposit", "25", R2,
                         UUID("50000000-0000-0000-0000-000000000304"), "deposit", base + timedelta(days=6))
        _issue_and_apply(session, ADVANCE, "customer_advance", "15", R2,
                         UUID("50000000-0000-0000-0000-000000000305"), "advance", base + timedelta(days=7))
        residual = TransactionalReceivableLifecycleEngine.apply_customer_value(
            session, ApplyCustomerValueCommand(_application(
                P2, R2, UUID("50000000-0000-0000-0000-000000000306"), "20",
                "overpayment-apply", base + timedelta(days=8),
            ))
        )
        if residual.balance.available_amount != Decimal("10"):
            raise RuntimeError("overpayment reapplication differs")

    with Session(engine) as session:
        states = dict(session.execute(text("""
          SELECT public_id,obligation_state FROM financial_obligations
          WHERE tenant_id=:tenant ORDER BY public_id
        """), {"tenant": TENANT}).all())
        if states[R1] != "satisfied" or states[R2] != "satisfied" or states[R3] != "open":
            raise RuntimeError(f"receivable lifecycle states differ: {states}")
        position = CustomerReceivableBalanceService.get(
            session, tenant_id=TENANT, customer_party_id=CUSTOMER, currency_code="XAF"
        )
        if (position.receivable_outstanding, position.customer_value_available, position.net_customer_due) != (
            Decimal("50"), Decimal("10"), Decimal("40")
        ):
            raise RuntimeError(f"customer financial position differs: {position}")
        aged = TransactionalReceivableLifecycleEngine.age(
            session, AgeReceivablesCommand(AsOfAgingQuery(
                TENANT, base + timedelta(days=19), (base + timedelta(days=19)).date()
            ))
        )
        if len(aged.rows) != 1 or aged.rows[0].obligation_public_id != R3:
            raise RuntimeError(f"receivable aging population differs: {aged.rows}")
        if aged.rows[0].bucket_code != "past_due_1_30" or aged.rows[0].outstanding_amount != Decimal("50"):
            raise RuntimeError("receivable aging bucket or balance differs")
        try:
            TransactionalReceivableLifecycleEngine.repository.receivable_authority(
                session, tenant_id=TENANT + 1, public_id=R3
            )
        except ReceivableLifecycleError as exc:
            if exc.code != "receivable_not_found":
                raise
        else:
            raise RuntimeError("tenant isolation failed")

    before = None
    with engine.connect() as connection:
        before = connection.execute(text("SELECT count(*) FROM value_sources")).scalar_one()
    session = Session(engine)
    transaction = session.begin()
    try:
        wrong = _receive_payment(
            UUID("50000000-0000-0000-0000-000000000299"), "5", R3,
            UUID("50000000-0000-0000-0000-000000000399"), "5", "wrong-customer",
            base + timedelta(days=9), owner=OTHER_CUSTOMER,
        )
        try:
            TransactionalReceivableLifecycleEngine.receive_payment(session, wrong)
        except ReceivableLifecycleError as exc:
            if exc.code != "customer_mismatch":
                raise
        else:
            raise RuntimeError("cross-customer payment was accepted")
    finally:
        transaction.rollback()
        session.close()
    with engine.connect() as connection:
        if connection.execute(text("SELECT count(*) FROM value_sources")).scalar_one() != before:
            raise RuntimeError("failed customer-scope command did not roll back")

    with Session(engine) as session, session.begin():
        try:
            TransactionalReceivableLifecycleEngine.apply_customer_value(
                session, ApplyCustomerValueCommand(_application(
                    P2, R3, UUID("50000000-0000-0000-0000-000000000398"), "11",
                    "over-capacity", base + timedelta(days=10),
                ))
            )
        except AllocationValidationError as exc:
            if exc.code != "source_capacity_exceeded":
                raise
        else:
            raise RuntimeError("unapplied-value capacity was exceeded")

    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE value_sources SET source_amount=source_amount+1 WHERE public_id=:id"), {"id": str(P2)})
    except DBAPIError:
        pass
    else:
        raise RuntimeError("direct SQL mutation bypass succeeded")


def _create_and_verify():
    _development_verify()
    _create()
    engine = None
    try:
        _upgrade()
        engine = _engine(TEST_DATABASE_NAME)
        _seed(engine)
        _exercise(engine)
        engine.dispose()
        engine = None
        _drop(TEST_DATABASE_NAME)
        _development_verify()
        print(
            "m50_receivables=PASS database=xbos_track_b_m50_receivables_test "
            "partial_payment=PASS later_repayment=PASS aging=PASS customer_credit=PASS "
            "deposit=PASS advance=PASS overpayment=PASS tenant_scope=PASS customer_scope=PASS "
            "idempotency=PASS capacity=PASS direct_sql=PASS rollback=PASS canonical_head_unchanged=PASS dropped=true"
        )
    except Exception:
        if engine is not None:
            engine.dispose()
        print(f"M5.0 verification failed; retained disposable database={TEST_DATABASE_NAME}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("verify")
    subparsers.add_parser("create-and-verify")
    drop = subparsers.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    arguments = parser.parse_args()
    if arguments.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif arguments.command == "verify":
        _development_verify()
    elif arguments.command == "drop":
        _drop(arguments.confirm_database_name)
        print(f"dropped={arguments.confirm_database_name}")
    else:
        _create_and_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
