"""Single disposable acceptance rehearsal for M5.1 payables and disbursements."""

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

from core.domain.finance.allocation_contract import AllocationValidationError, CreateValueSourceCommand
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.payable_balance_service import SupplierPayableBalanceService
from core.domain.finance.payable_contract import DisbursePayablesCommand, OpenPayableCommand, PayableLifecycleError
from core.domain.finance.payable_engine import TransactionalPayableLifecycleEngine
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_contract import CreatePaymentSettlementCommand, TransitionPaymentSettlementCommand
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.value_application_contract import (
    ApplyUnappliedValueCommand, ReceiveAndApplyValueCommand, ValueApplicationInstruction,
)
from database import engine as application_engine


DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m51_payables_test"
TARGET_REVISION = "m46_provider_financials_015"
TENANT = 5101
ORG = 5111
PAYER = UUID("51000000-0000-0000-0000-000000000010")
SUPPLIER = UUID("51000000-0000-0000-0000-000000000011")
OTHER_SUPPLIER = UUID("51000000-0000-0000-0000-000000000012")
CORRELATION = UUID("51000000-0000-0000-0000-000000000099")
P1 = UUID("51000000-0000-0000-0000-000000000101")
P2 = UUID("51000000-0000-0000-0000-000000000102")
P3 = UUID("51000000-0000-0000-0000-000000000103")
ACCOUNT = UUID("51000000-0000-0000-0000-000000000150")
BASE = datetime(2026, 8, 10, 10, tzinfo=timezone.utc)

EMPTY_TABLES = (
    "canonical_payment_requests", "canonical_payment_intents", "canonical_payment_tenders",
    "payment_tender_transitions", "canonical_payment_attempts", "canonical_payment_attempt_transitions",
    "provider_callback_events", "payment_settlements", "payment_settlement_transitions",
    "payment_settlement_reversals", "provider_settlement_components", "payment_provider_accounts",
    "idempotency_records", "kernel_source_records", "financial_events", "outbox_messages",
    "journal_entries", "journal_lines", "financial_obligations", "financial_obligation_lines",
    "value_sources", "payment_allocations", "allocation_reversals", "financial_dimension_types",
    "financial_dimension_values", "posting_dimension_policies",
)


def _application_url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _url(name): return _application_url().set(database=name)
def _engine(name, *, autocommit=False):
    return create_engine(_url(name), pool_pre_ping=True, **({"isolation_level": "AUTOCOMMIT"} if autocommit else {}))


def _exists(name):
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally: engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally: engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME: raise RuntimeError(f"refusing unapproved database: {name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally: engine.dispose()


@contextmanager
def _selected(name):
    previous = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = _url(name).render_as_string(hide_password=False)
    try: yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous


def _upgrade():
    with _selected(TEST_DATABASE_NAME): alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)


def _seed(engine):
    with engine.begin() as connection:
        connection.execute(text("""
          INSERT INTO tenants(id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
          VALUES(:tenant,'M51T','M5.1 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)
        """), {"tenant": TENANT})
        connection.execute(text("""
          INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata)
          VALUES('XAF','fiat','CFA Franc',0,8,TRUE,'{}'::jsonb)
        """))
        connection.execute(text("""
          INSERT INTO organization_units(id,tenant_id,unit_type,code,name,timezone_name,active)
          VALUES(:org,:tenant,'legal_entity','M51','M5.1 Entity','Africa/Douala',TRUE)
        """), {"org": ORG, "tenant": TENANT})
        connection.execute(text("""
          INSERT INTO operational_financial_accounts(
            public_id,tenant_id,organization_unit_id,account_class,account_type,code,display_name,
            currency_code,channel_code,aggregation_role,reconciliation_enabled,active,opened_at
          ) VALUES(:public_id,:tenant,:org,'treasury','cash','m51-disbursement','M5.1 Disbursement Cash',
                   'XAF','cash','leaf',TRUE,TRUE,:opened)
        """), {"public_id": str(ACCOUNT), "tenant": TENANT, "org": ORG, "opened": BASE})


def _payable(public_id, amount, key, supplier=SUPPLIER):
    return OpenPayableCommand(CreateObligationCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=ORG,
        debtor_party_id=PAYER, creditor_party_id=supplier, obligation_type="trade_payable",
        original_amount=Decimal(amount), currency_code="XAF", due_at=BASE + timedelta(days=30),
        occurred_at=BASE, business_date=BASE.date(), calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m51.verifier", source_component="m51.verifier",
        source_record_id=key, idempotency_scope="m51.payable", idempotency_key=key,
        lines=(ObligationLineCommand(1, "principal", "Supplier payable", 1, amount, amount, key + "-line"),),
    ))


def _intent(number, amount):
    return CreatePaymentIntentCommand(
        public_id=UUID(f"51000000-0000-0000-0001-{number:012d}"), tenant_id=TENANT,
        organization_unit_id=ORG, requested_amount=Decimal(amount), currency_code="XAF",
        payment_method_policy={"allowed_methods": ["cash"], "max_tenders": 1},
        expires_at=BASE + timedelta(days=1), occurred_at=BASE, business_date=BASE.date(),
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m51.verifier",
        source_component="m51.verifier", source_record_id=f"intent-{number}",
        idempotency_scope="m51.intent", idempotency_key=f"intent-{number}",
    )


def _settlement(number, amount):
    return CreatePaymentSettlementCommand(
        public_id=UUID(f"51000000-0000-0000-0002-{number:012d}"), tenant_id=TENANT,
        organization_unit_id=ORG, payment_intent_public_id=_intent(number, amount).public_id,
        operational_account_public_id=ACCOUNT, settlement_direction="outgoing",
        gross_amount=Decimal(amount), fee_amount=Decimal("0"), net_amount=Decimal(amount),
        currency_code="XAF", payment_method_code="cash", payment_rail_code="cash",
        value_date=BASE.date(), occurred_at=BASE + timedelta(minutes=number), business_date=BASE.date(),
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m51.verifier",
        source_component="m51.verifier", source_record_id=f"settlement-{number}",
        idempotency_scope="m51.settlement", idempotency_key=f"settlement-{number}",
    )


def _transition(settlement, number, state):
    return TransitionPaymentSettlementCommand(
        tenant_id=TENANT, organization_unit_id=ORG, payment_settlement_public_id=settlement.public_id,
        expected_row_version=1, target_state=state,
        finality_status="final" if state == "confirmed" else "rejected",
        availability_state="available" if state == "confirmed" else "unavailable",
        reason_code=f"settlement_{state}", failure_code="provider_rejected" if state == "failed" else None,
        evidence_payload={"status": state, "proof": f"m51-{number}"},
        occurred_at=settlement.occurred_at + timedelta(minutes=1), business_date=BASE.date(),
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m51.verifier",
        source_component="m51.verifier", source_record_id=f"transition-{number}-{state}",
        idempotency_scope="m51.settlement.transition", idempotency_key=f"transition-{number}-{state}",
    )


def _create_settlement(session, number, amount, state="confirmed"):
    intent = _intent(number, amount); TransactionalPaymentIntentEngine.create_intent(session, intent)
    settlement = _settlement(number, amount); TransactionalPaymentSettlementEngine.create(session, settlement)
    if state in {"confirmed", "failed"}: TransactionalPaymentSettlementEngine.transition(session, _transition(settlement, number, state))
    return settlement


def _application(source, targets, key, occurred):
    instructions = tuple(ValueApplicationInstruction(
        allocation_public_id=UUID(f"51000000-0000-0000-0004-{key * 10 + index:012d}"),
        obligation_public_id=target, source_record_id=f"a-{key}-{index}",
        idempotency_key=f"a-{key}-{index}", exact_amount=Decimal(amount),
    ) for index, (target, amount) in enumerate(targets, 1))
    return ApplyUnappliedValueCommand(
        tenant_id=TENANT, value_source_public_id=source, occurred_at=occurred,
        business_date=occurred.date(), calendar_policy_version=1, correlation_id=CORRELATION,
        source_component="m51.verifier", idempotency_scope="m51.application",
        actor_service="m51.verifier", applications=instructions,
    )


def _disbursement(settlement, source, amount, targets, key, payee=SUPPLIER):
    value = CreateValueSourceCommand(
        public_id=source, tenant_id=TENANT, organization_unit_id=ORG, owner_party_id=PAYER,
        source_type="disbursement", source_amount=Decimal(amount), currency_code="XAF",
        payment_settlement_public_id=settlement.public_id, occurred_at=settlement.occurred_at + timedelta(minutes=2),
        business_date=BASE.date(), calendar_policy_version=1, correlation_id=CORRELATION,
        actor_service="m51.verifier", source_component="m51.verifier", source_record_id=f"d-{key}",
        idempotency_scope="m51.disbursement", idempotency_key=f"d-{key}",
        metadata={"payee_party_id": str(payee)},
    )
    application = _application(value.public_id, targets, key, value.occurred_at)
    return DisbursePayablesCommand(ReceiveAndApplyValueCommand(value, application))


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != TARGET_REVISION: raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20:
            raise RuntimeError("canonical event catalog count differs")
        for table in EMPTY_TABLES:
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count: raise RuntimeError(f"development table not empty: {table}={count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={revision}")
    print("m51_payables_development=PASS canonical_head_unchanged=PASS development_empty=PASS")


def _exercise(engine):
    s1 = UUID("51000000-0000-0000-0000-000000000301")
    s2 = UUID("51000000-0000-0000-0000-000000000302")
    with Session(engine) as session, session.begin():
        for command in (_payable(P1, "100", "p1"), _payable(P2, "30", "p2"), _payable(P3, "25", "p3", OTHER_SUPPLIER)):
            TransactionalPayableLifecycleEngine.open(session, command)

        settlement1 = _create_settlement(session, 1, "40")
        first = _disbursement(settlement1, s1, "40", ((P1, "40"),), 1)
        created = TransactionalPayableLifecycleEngine.disburse(session, first)
        replay = TransactionalPayableLifecycleEngine.disburse(session, first)
        if created.replayed or not replay.replayed: raise RuntimeError("disbursement replay semantics failed")

        settlement2 = _create_settlement(session, 2, "90")
        batch = _disbursement(settlement2, s2, "90", ((P1, "60"), (P2, "30")), 2)
        TransactionalPayableLifecycleEngine.disburse(session, batch)

        pending = _create_settlement(session, 3, "25", state="pending")
        try: TransactionalPayableLifecycleEngine.disburse(session, _disbursement(pending, UUID(int=513), "25", ((P3, "25"),), 3, OTHER_SUPPLIER))
        except PayableLifecycleError as exc:
            if exc.code != "confirmed_outgoing_settlement_required": raise
        else: raise RuntimeError("pending settlement funded disbursement")

        failed = _create_settlement(session, 4, "25", state="failed")
        try: TransactionalPayableLifecycleEngine.disburse(session, _disbursement(failed, UUID(int=514), "25", ((P3, "25"),), 4, OTHER_SUPPLIER))
        except PayableLifecycleError as exc:
            if exc.code != "confirmed_outgoing_settlement_required": raise
        else: raise RuntimeError("failed settlement funded disbursement")

        confirmed = _create_settlement(session, 5, "10")
        try: TransactionalPayableLifecycleEngine.disburse(session, _disbursement(confirmed, UUID(int=515), "9", ((P3, "9"),), 5, OTHER_SUPPLIER))
        except PayableLifecycleError as exc:
            if exc.code != "settlement_amount_mismatch": raise
        else: raise RuntimeError("settlement amount mismatch was accepted")

        try: TransactionalPayableLifecycleEngine.disburse(session, _disbursement(confirmed, UUID(int=516), "10", ((P3, "10"),), 6, SUPPLIER))
        except PayableLifecycleError as exc:
            if exc.code != "payee_mismatch": raise
        else: raise RuntimeError("cross-supplier disbursement was accepted")

    with Session(engine) as session:
        states = dict(session.execute(text("SELECT public_id,obligation_state FROM financial_obligations WHERE tenant_id=:tenant"), {"tenant": TENANT}).all())
        if states[P1] != "satisfied" or states[P2] != "satisfied" or states[P3] != "open":
            raise RuntimeError(f"payable lifecycle states differ: {states}")
        first_balance = SupplierPayableBalanceService.get(session, tenant_id=TENANT, supplier_party_id=SUPPLIER, currency_code="XAF")
        other_balance = SupplierPayableBalanceService.get(session, tenant_id=TENANT, supplier_party_id=OTHER_SUPPLIER, currency_code="XAF")
        if first_balance.outstanding_amount != 0 or other_balance.outstanding_amount != Decimal("25"):
            raise RuntimeError("supplier payable positions differ")
        try: TransactionalPayableLifecycleEngine.repository.payable_authority(session, tenant_id=TENANT + 1, public_id=P3)
        except PayableLifecycleError as exc:
            if exc.code != "payable_not_found": raise
        else: raise RuntimeError("tenant isolation failed")

        try:
            from core.domain.finance.payable_contract import ApplyDisbursementCommand
            TransactionalPayableLifecycleEngine.apply_existing(session, ApplyDisbursementCommand(
                _application(s1, ((P3, "1"),), 7, BASE + timedelta(hours=1))
            ))
        except PayableLifecycleError as exc:
            if exc.code != "payee_mismatch": raise
        except AllocationValidationError:
            raise RuntimeError("payee guard ran after allocation capacity")
        else: raise RuntimeError("persisted disbursement crossed supplier boundary")

    with engine.connect() as connection:
        if connection.execute(text("SELECT count(*) FROM value_sources")).scalar_one() != 2:
            raise RuntimeError("failed disbursement left value-source facts")
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE value_sources SET metadata='{}'::jsonb WHERE public_id=:id"), {"id": str(s1)})
    except DBAPIError: pass
    else: raise RuntimeError("direct SQL disbursement mutation bypass succeeded")


def _create_and_verify():
    _development_verify(); _create(); engine = None
    try:
        _upgrade(); engine = _engine(TEST_DATABASE_NAME); _seed(engine); _exercise(engine)
        engine.dispose(); engine = None; _drop(TEST_DATABASE_NAME); _development_verify()
        print(
            "m51_payables=PASS database=xbos_track_b_m51_payables_test payable_lifecycle=PASS "
            "partial_disbursement=PASS later_disbursement=PASS batch=PASS pending_failed_rejected=PASS "
            "settlement_authority=PASS payer_payee=PASS tenant_scope=PASS capacity=PASS idempotency=PASS "
            "direct_sql=PASS rollback=PASS canonical_head_unchanged=PASS dropped=true"
        )
    except Exception:
        if engine is not None: engine.dispose()
        print(f"M5.1 verification failed; retained disposable database={TEST_DATABASE_NAME}", file=sys.stderr); raise


def main():
    parser = argparse.ArgumentParser(); commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status"); commands.add_parser("verify"); commands.add_parser("create-and-verify")
    drop = commands.add_parser("drop"); drop.add_argument("--confirm-database-name", required=True); args = parser.parse_args()
    if args.command == "status": print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "verify": _development_verify()
    elif args.command == "drop": _drop(args.confirm_database_name); print(f"dropped={args.confirm_database_name}")
    else: _create_and_verify()
    return 0


if __name__ == "__main__": raise SystemExit(main())
