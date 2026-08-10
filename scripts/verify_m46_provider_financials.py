"""Read-only development gate and disposable M4.6 provider-financial rehearsal."""
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand, TransitionPaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_contract import CreatePaymentSettlementCommand, TransitionPaymentSettlementCommand
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.provider_financial_contract import (
    CreateProviderSettlementComponentCommand,
    ProviderFinancialIdempotencyConflict,
    ProviderFinancialValidationError,
)
from core.domain.finance.provider_financial_engine import TransactionalProviderFinancialEngine
from core.domain.finance.provider_net_position_service import ProviderNetPositionService
from core.persistence.m46_provider_financials import PARENT_REVISION, TARGET_REVISION, TEST_DATABASE_NAME
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
BASE = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
CORRELATION = UUID("46000000-0000-0000-0000-000000000099")
PAYMENT_TABLES = (
    "canonical_payment_requests", "canonical_payment_intents", "canonical_payment_tenders",
    "payment_tender_transitions", "canonical_payment_attempts",
    "canonical_payment_attempt_transitions", "provider_callback_events",
    "payment_settlements", "payment_settlement_transitions", "payment_settlement_reversals",
)
SIDE_EFFECT_TABLES = (
    "provider_settlement_components", "kernel_source_records", "idempotency_records",
    "financial_events", "outbox_messages", "journal_entries", "journal_lines",
)


def _url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _engine(name, isolation_level=None):
    return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


def _exists(name):
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _create_clone():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally:
        engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        engine.dispose()


@contextmanager
def _migration_database(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _migrate(name, revision, *, downgrade=False):
    with _migration_database(name):
        config = Config(str(ROOT / "alembic.ini"))
        (alembic_command.downgrade if downgrade else alembic_command.upgrade)(config, revision)


def _revision(connection):
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}:
            raise RuntimeError(f"unexpected development revision={revision}")
        tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        if revision == TARGET_REVISION and "provider_settlement_components" not in tables:
            raise RuntimeError("M4.6 table missing at target revision")
        if revision == PARENT_REVISION and "provider_settlement_components" in tables:
            raise RuntimeError("M4.6 table exists at parent revision")
        for table in PAYMENT_TABLES:
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development payment table is not empty={table}")
        for table in SIDE_EFFECT_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development side-effect table is not empty={table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m46_provider_financials_development=PASS")
    return revision


def _status():
    exists = _exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _seed_scope(session):
    tenant = int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    session.execute(text("""INSERT INTO tenant_currency_policies(tenant_id,currency_code,rounding_mode,cash_rounding_increment,active,effective_from,policy_version)
        VALUES(:tenant,'XAF','half_even',0,true,:effective,46)
        ON CONFLICT(tenant_id,currency_code,policy_version) DO UPDATE SET active=true"""), {"tenant": tenant, "effective": BASE-timedelta(days=1)})
    organization = session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:tenant ORDER BY id LIMIT 1"), {"tenant": tenant}).scalar_one_or_none()
    if organization is None:
        organization = session.execute(text("INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active) VALUES(:tenant,'branch','m46-verifier','M4.6 Verifier','Africa/Douala',true) RETURNING id"), {"tenant": tenant}).scalar_one()
    provider = session.execute(text("""INSERT INTO payment_provider_accounts(public_id,tenant_id,organization_unit_id,provider_code,external_account_reference,credential_reference,environment,active)
        VALUES('46000000-0000-0000-0000-000000000010',:tenant,:org,'tranzak','m46-sandbox','secret://m46','sandbox',true)
        ON CONFLICT(provider_code,environment,external_account_reference) DO UPDATE SET active=true RETURNING id,public_id"""), {"tenant": tenant, "org": organization}).mappings().one()
    operational = session.execute(text("""INSERT INTO operational_financial_accounts(public_id,tenant_id,organization_unit_id,account_class,account_type,code,display_name,currency_code,channel_code,aggregation_role,reconciliation_enabled,active,opened_at)
        VALUES('46000000-0000-0000-0000-000000000011',:tenant,:org,'treasury','mobile_money','m46-provider','M4.6 Provider','XAF','xafpay','leaf',true,true,:opened)
        ON CONFLICT(tenant_id,organization_unit_id,code) DO UPDATE SET active=true RETURNING id,public_id"""), {"tenant": tenant, "org": organization, "opened": BASE}).mappings().one()
    session.execute(text("""INSERT INTO accounting_periods(tenant_id,legal_entity_unit_id,period_code,period_start,period_end,period_state)
        VALUES(:tenant,:org,'2026-08','2026-08-01','2026-08-31','open') ON CONFLICT(tenant_id,legal_entity_unit_id,period_code) DO NOTHING"""), {"tenant": tenant, "org": organization})
    roles = (
        ("provider_fee_expense", "m46-fee-expense", "expense", "debit", None),
        ("provider_settlement_receivable_or_payable", "m46-provider-balance", "asset", "debit", int(operational["id"])),
        ("provider_reserve_asset", "m46-reserve", "asset", "debit", int(operational["id"])),
        ("provider_settlement_receivable", "m46-provider-receivable", "asset", "debit", int(operational["id"])),
        ("chargeback_loss_or_receivable", "m46-chargeback", "expense", "debit", None),
    )
    for index, (role, code, account_type, balance, operational_id) in enumerate(roles, 1):
        account_id = session.execute(text("""INSERT INTO ledger_accounts(public_id,tenant_id,legal_entity_unit_id,account_code,account_name,account_type,normal_balance,currency_policy,fixed_currency_code,active,effective_from)
            VALUES(:public,:tenant,:org,:code,:name,:account_type,:balance,'fixed','XAF',true,'2026-01-01')
            ON CONFLICT(tenant_id,legal_entity_unit_id,account_code) DO UPDATE SET active=true RETURNING id"""), {
                "public": f"46000000-0000-0000-0001-{index:012d}", "tenant": tenant, "org": organization,
                "code": code, "name": role.replace("_", " ").title(), "account_type": account_type, "balance": balance,
            }).scalar_one()
        session.execute(text("""INSERT INTO ledger_account_role_bindings(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,ledger_account_id,operational_account_id,effective_from,active)
            VALUES(:tenant,:org,:role,'default','XAF',:account,:operational,'2026-01-01',true)
            ON CONFLICT(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,effective_from) DO UPDATE SET active=true"""), {
                "tenant": tenant, "org": organization, "role": role, "account": account_id, "operational": operational_id,
            })
    return tenant, int(organization), UUID(str(provider["public_id"])), UUID(str(operational["public_id"]))


def _seed_confirmed_settlement(session, tenant, organization, provider, operational):
    intent = CreatePaymentIntentCommand(
        public_id=UUID("46000000-0000-0000-0002-000000000001"), tenant_id=tenant,
        organization_unit_id=organization, requested_amount="100", currency_code="XAF",
        payment_method_policy={"allowed_methods": ["mobile_money"], "max_tenders": 1},
        expires_at=BASE+timedelta(hours=4), occurred_at=BASE, business_date=date(2026,8,10),
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m46.verifier",
        source_component="m46.verifier", source_record_id="intent", idempotency_scope="m46.intent", idempotency_key="intent")
    attempt = CreatePaymentAttemptCommand(
        public_id=UUID("46000000-0000-0000-0003-000000000001"), tenant_id=tenant,
        organization_unit_id=organization, payment_intent_public_id=intent.public_id,
        attempted_amount="100", currency_code="XAF", payment_method_code="mobile_money",
        payment_rail_code="mtn_momo", orchestrator_code="xafpay", provider_account_public_id=provider,
        underlying_provider_code="tranzak", timeout_at=BASE+timedelta(hours=2),
        occurred_at=BASE+timedelta(minutes=1), business_date=date(2026,8,10), calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m46.verifier", source_component="m46.verifier",
        source_record_id="attempt", idempotency_scope="m46.attempt", idempotency_key="attempt")
    TransactionalPaymentIntentEngine.create_intent(session, intent)
    TransactionalPaymentAttemptEngine.create(session, attempt)
    for version, state, minute in ((1, "processing", 2), (2, "succeeded", 3)):
        TransactionalPaymentAttemptEngine.transition(session, TransitionPaymentAttemptCommand(
            tenant_id=tenant, organization_unit_id=organization, payment_attempt_public_id=attempt.public_id,
            expected_row_version=version, target_state=state, reason_code=f"m46_{state}",
            external_attempt_reference="tranzak-m46-attempt", evidence_payload={"provider_status": state},
            occurred_at=BASE+timedelta(minutes=minute), business_date=date(2026,8,10), calendar_policy_version=1,
            correlation_id=CORRELATION, actor_service="m46.verifier", source_component="m46.verifier",
            source_record_id=f"attempt-{state}", idempotency_scope="m46.attempt.transition", idempotency_key=state))
    settlement = CreatePaymentSettlementCommand(
        public_id=UUID("46000000-0000-0000-0004-000000000001"), tenant_id=tenant,
        organization_unit_id=organization, payment_intent_public_id=intent.public_id,
        payment_attempt_public_id=attempt.public_id, operational_account_public_id=operational,
        settlement_direction="incoming", gross_amount="100", fee_amount="0", net_amount="100",
        currency_code="XAF", payment_method_code="mobile_money", payment_rail_code="mtn_momo",
        value_date=date(2026,8,10), occurred_at=BASE+timedelta(minutes=4), business_date=date(2026,8,10),
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m46.verifier",
        source_component="m46.verifier", source_record_id="settlement", idempotency_scope="m46.settlement", idempotency_key="settlement")
    TransactionalPaymentSettlementEngine.create(session, settlement)
    TransactionalPaymentSettlementEngine.transition(session, TransitionPaymentSettlementCommand(
        tenant_id=tenant, organization_unit_id=organization, payment_settlement_public_id=settlement.public_id,
        expected_row_version=1, target_state="confirmed", finality_status="final", availability_state="available",
        reason_code="provider_confirmed", external_settlement_reference="tranzak-m46-settlement",
        evidence_payload={"provider_status": "confirmed"}, occurred_at=BASE+timedelta(minutes=5),
        business_date=date(2026,8,10), calendar_policy_version=1, correlation_id=CORRELATION,
        actor_service="m46.verifier", source_component="m46.verifier", source_record_id="settlement-confirmed",
        idempotency_scope="m46.settlement.transition", idempotency_key="confirmed"))
    return settlement


def _component(tenant, organization, settlement, provider, number, component_type, amount, *, original=None):
    classification = "network_fee" if component_type == "provider_fee" else component_type
    return CreateProviderSettlementComponentCommand(
        public_id=UUID(f"46000000-0000-0000-0005-{number:012d}"), tenant_id=tenant,
        organization_unit_id=organization, payment_settlement_public_id=settlement.public_id,
        provider_account_public_id=provider, original_component_public_id=original,
        component_type=component_type, classification_code=classification, amount=amount, currency_code="XAF",
        provider_event_reference=f"tranzak-m46-component-{number}", value_date=date(2026,8,10),
        evidence_payload={"provider": "tranzak", "component_number": number},
        occurred_at=BASE+timedelta(minutes=10+number), business_date=date(2026,8,10), calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m46.verifier", source_component="m46.verifier",
        source_record_id=f"component-{number}", idempotency_scope="m46.component", idempotency_key=f"component-{number}")


def _exercise(engine):
    with Session(engine) as session, session.begin():
        tenant, organization, provider, operational = _seed_scope(session)
        settlement = _seed_confirmed_settlement(session, tenant, organization, provider, operational)
        fee = _component(tenant, organization, settlement, provider, 1, "provider_fee", "5")
        hold = _component(tenant, organization, settlement, provider, 2, "reserve_hold", "20")
        release = _component(tenant, organization, settlement, provider, 3, "reserve_release", "8", original=hold.public_id)
        loss = _component(tenant, organization, settlement, provider, 4, "chargeback_loss", "3")
        results = [TransactionalProviderFinancialEngine.create(session, command) for command in (fee, hold, release, loss)]
        if any(result.replayed for result in results):
            raise RuntimeError("first provider component emission replayed")
        replay = TransactionalProviderFinancialEngine.create(session, fee)
        if not replay.replayed or not replay.posted_financial_event.replayed:
            raise RuntimeError("component/event/posting replay failed")
        try:
            TransactionalProviderFinancialEngine.create(session, replace(fee, amount=Decimal("6")))
        except ProviderFinancialIdempotencyConflict:
            pass
        else:
            raise RuntimeError("component idempotency conflict was accepted")
        try:
            TransactionalProviderFinancialEngine.create(session, _component(tenant, organization, settlement, provider, 5, "reserve_release", "13", original=hold.public_id))
        except DBAPIError:
            pass
        else:
            raise RuntimeError("reserve release exceeded original capacity")
        try:
            TransactionalProviderFinancialEngine.create(session, replace(_component(tenant, organization, settlement, provider, 6, "provider_fee", "1"), tenant_id=tenant+999))
        except ProviderFinancialValidationError:
            pass
        else:
            raise RuntimeError("cross-tenant provider component was accepted")
        position = ProviderNetPositionService.resolve(session, tenant_id=tenant, payment_settlement_public_id=settlement.public_id)
        if (position.gross_amount, position.fee_amount, position.reserve_held, position.chargeback_loss, position.expected_net) != tuple(map(Decimal, ("100", "5", "12", "3", "80"))):
            raise RuntimeError(f"unexpected provider net position={position}")
        gross = session.execute(text("SELECT gross_amount,fee_amount,net_amount FROM payment_settlements WHERE public_id=:public"), {"public": str(settlement.public_id)}).one()
        if tuple(map(Decimal, gross)) != tuple(map(Decimal, ("100", "0", "100"))):
            raise RuntimeError("gross customer settlement truth was rewritten")

    with engine.connect() as connection:
        expected = {"provider_settlement_components": 4, "financial_events": 4, "outbox_messages": 4, "journal_entries": 4, "journal_lines": 8}
        counts = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in expected}
        if counts != expected:
            raise RuntimeError(f"unexpected M4.6 atomic counts={counts}")
        if connection.execute(text("SELECT count(*) FROM journal_entries je WHERE je.entry_state <> 'posted' OR EXISTS (SELECT 1 FROM journal_lines jl WHERE jl.tenant_id=je.tenant_id AND jl.journal_entry_id=je.id GROUP BY jl.tenant_id,jl.journal_entry_id HAVING sum(jl.transaction_debit_amount) <> sum(jl.transaction_credit_amount))")).scalar_one():
            raise RuntimeError("provider component journal is not posted and balanced")
        try:
            with connection.begin_nested():
                connection.execute(text("""INSERT INTO provider_settlement_components(public_id,tenant_id,organization_unit_id,payment_settlement_id,provider_account_id,operational_account_id,component_type,classification_code,amount,currency_code,provider_event_reference,value_date,evidence_hash,evidence_payload,occurred_at,business_date,calendar_policy_version,correlation_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
                    SELECT gen_random_uuid(),tenant_id,organization_unit_id,payment_settlement_id,provider_account_id,operational_account_id,'provider_fee','bypass',1,currency_code,'m46-direct-bypass',value_date,evidence_hash,evidence_payload,occurred_at,business_date,calendar_policy_version,correlation_id,actor_service,source_component,'direct-bypass','m46.direct','direct-bypass',request_fingerprint,metadata FROM provider_settlement_components LIMIT 1"""))
        except DBAPIError:
            pass
        else:
            raise RuntimeError("direct SQL component bypass succeeded")
        try:
            with connection.begin_nested():
                connection.execute(text("UPDATE provider_settlement_components SET amount=1 WHERE component_type='provider_fee'"))
        except DBAPIError:
            pass
        else:
            raise RuntimeError("provider component immutability bypass succeeded")

    before = None
    with engine.connect() as connection:
        before = tuple(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ("provider_settlement_components", "financial_events", "outbox_messages", "journal_entries"))
    with Session(engine) as session:
        transaction = session.begin()
        tenant = int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
        organization = int(session.execute(text("SELECT organization_unit_id FROM payment_settlements LIMIT 1")).scalar_one())
        provider = UUID(str(session.execute(text("SELECT public_id FROM payment_provider_accounts WHERE provider_code='tranzak' LIMIT 1")).scalar_one()))
        settlement_public = UUID(str(session.execute(text("SELECT public_id FROM payment_settlements LIMIT 1")).scalar_one()))
        synthetic = type("Settlement", (), {"public_id": settlement_public})()
        TransactionalProviderFinancialEngine.create(session, _component(tenant, organization, synthetic, provider, 9, "provider_fee", "1"))
        transaction.rollback()
    with engine.connect() as connection:
        after = tuple(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ("provider_settlement_components", "financial_events", "outbox_messages", "journal_entries"))
    if after != before:
        raise RuntimeError(f"outer transaction rollback leaked side effects before={before} after={after}")


def _run():
    _verify_development()
    _create_clone()
    engine = None
    try:
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        engine = _engine(TEST_DATABASE_NAME)
        with engine.connect() as connection:
            if _revision(connection) != TARGET_REVISION:
                raise RuntimeError("disposable database did not reach M4.6")
        engine.dispose(); engine = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        engine = _engine(TEST_DATABASE_NAME)
        _exercise(engine)
        engine.dispose(); engine = None
        _drop(TEST_DATABASE_NAME)
        _verify_development()
        print(f"m46_provider_financials=PASS database={TEST_DATABASE_NAME} fee=PASS reserve_hold=PASS reserve_release=PASS adjustment=PASS net_position=PASS gross_immutable=PASS replay=PASS conflict=PASS capacity=PASS tenant_scope=PASS direct_sql=PASS posting=PASS rollback=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if engine is not None:
            engine.dispose()
        print(f"M4.6 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("verify")
    subparsers.add_parser("create-and-verify")
    drop = subparsers.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()
    if args.command == "status":
        return 0 if _status() else 1
    if args.command == "verify":
        _verify_development()
    elif args.command == "create-and-verify":
        _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
