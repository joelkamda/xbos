"""Disposable transactional verification for M4.1 payment commands."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.payment_intent_contract import (
    CreatePaymentIntentCommand,
    CreatePaymentRequestCommand,
    PaymentCommandIdempotencyConflict,
    PaymentCommandValidationError,
)
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_intent_repository import PaymentIntentRepository
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from core.persistence.m40_payment_foundation import FOUNDATION_TABLES
from core.persistence.m41_payment_commands import (
    FORBIDDEN_SIDE_EFFECT_TABLES,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
)
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
BASE = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _engine(database_name: str, *, isolation_level: str | None = None):
    return create_engine(
        _url().set(database=database_name),
        isolation_level=isolation_level,
        pool_pre_ping=True,
    )


def _database_exists(database_name: str) -> bool:
    admin = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"),
                    {"name": database_name},
                ).scalar_one_or_none()
            )
    finally:
        admin.dispose()


def _create_clone() -> None:
    if _database_exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    admin = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"'
            )
    finally:
        admin.dispose()


def _drop_database(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={database_name}")
    admin = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        admin.dispose()


def _status() -> bool:
    exists = _database_exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _revision(connection) -> str:
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _verify_development() -> None:
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision != TARGET_REVISION:
            raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        counts = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in FOUNDATION_TABLES
        }
        populated = {table: count for table, count in counts.items() if count}
        if populated:
            raise RuntimeError(f"development M4 tables are not empty={populated}")
        for table in ("idempotency_records", "financial_events", "outbox_messages", "value_sources"):
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count:
                raise RuntimeError(f"development table is not empty={table}:{count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m41_payment_commands_development=PASS")


def _seed_scope(connection) -> tuple[int, int, str]:
    tenant_id = connection.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one_or_none()
    if tenant_id is None:
        raise RuntimeError("development clone has no tenant authority")
    connection.execute(
        text(
            """
            INSERT INTO currency_assets (
                code, asset_kind, display_name, minor_unit_scale, maximum_storage_scale, active
            ) VALUES ('XAF', 'fiat', 'Central African CFA franc', 0, 8, true)
            ON CONFLICT (code) DO NOTHING
            """
        )
    )
    organization_id = connection.execute(
        text(
            "SELECT id FROM organization_units WHERE tenant_id=:tenant_id ORDER BY id LIMIT 1"
        ),
        {"tenant_id": tenant_id},
    ).scalar_one_or_none()
    if organization_id is None:
        organization_id = connection.execute(
            text(
                """
                INSERT INTO organization_units (
                    tenant_id, unit_type, code, name, timezone_name, active
                ) VALUES (
                    :tenant_id, 'branch', 'm41-verifier', 'M4.1 Verifier', 'Africa/Douala', true
                ) RETURNING id
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one()
    return int(tenant_id), int(organization_id), "XAF"


def _request(tenant_id: int, organization_id: int) -> CreatePaymentRequestCommand:
    return CreatePaymentRequestCommand(
        public_id=UUID("41000000-0000-0000-0000-000000000001"),
        tenant_id=tenant_id,
        organization_unit_id=organization_id,
        payer_party_id=UUID("41000000-0000-0000-0000-000000000010"),
        purpose_code="invoice.collection",
        requested_amount=Decimal("100"),
        currency_code="XAF",
        expires_at=BASE + timedelta(days=1),
        occurred_at=BASE,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("41000000-0000-0000-0000-000000000020"),
        actor_service="m41.verifier",
        source_component="m41.verifier",
        source_record_id="request-1",
        idempotency_scope="m41.payment_request",
        idempotency_key="request-1",
        metadata={"channel": "verification"},
    )


def _intent(
    tenant_id: int,
    organization_id: int,
    *,
    suffix: int,
    amount: str,
    request_public_id: UUID | None,
) -> CreatePaymentIntentCommand:
    return CreatePaymentIntentCommand(
        public_id=UUID(f"41000000-0000-0000-0000-{suffix:012d}"),
        tenant_id=tenant_id,
        organization_unit_id=organization_id,
        requested_amount=Decimal(amount),
        currency_code="XAF",
        payment_method_policy={
            "allowed_methods": ["cash", "mobile_money"],
            "allow_mixed_tender": True,
            "max_tenders": 2,
        },
        payment_request_public_id=request_public_id,
        expires_at=BASE + timedelta(hours=12),
        occurred_at=BASE + timedelta(minutes=suffix),
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("41000000-0000-0000-0000-000000000020"),
        actor_service="m41.verifier",
        source_component="m41.verifier",
        source_record_id=f"intent-{suffix}",
        idempotency_scope="m41.payment_intent",
        idempotency_key=f"intent-{suffix}",
        metadata={"verification_case": suffix},
    )


def _obligation(tenant_id: int, organization_id: int) -> CreateObligationCommand:
    return CreateObligationCommand(
        public_id=UUID("41000000-0000-0000-0000-000000000030"),
        tenant_id=tenant_id,
        organization_unit_id=organization_id,
        debtor_party_id=UUID("41000000-0000-0000-0000-000000000031"),
        creditor_party_id=UUID("41000000-0000-0000-0000-000000000032"),
        obligation_type="receivable",
        original_amount=Decimal("50"),
        currency_code="XAF",
        due_at=BASE + timedelta(days=30),
        occurred_at=BASE,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("41000000-0000-0000-0000-000000000020"),
        actor_service="m41.verifier",
        source_component="m41.verifier",
        source_record_id="obligation-1",
        idempotency_scope="m41.obligation_seed",
        idempotency_key="obligation-1",
        lines=(
            ObligationLineCommand(
                line_number=1,
                line_type="principal",
                description="M4.1 obligation-linked intent authority",
                quantity=Decimal("1"),
                unit_amount=Decimal("50"),
                line_amount=Decimal("50"),
                source_record_id="obligation-1-line",
            ),
        ),
    )


def _exercise(engine) -> None:
    with Session(engine) as session, session.begin():
        tenant_id, organization_id, _ = _seed_scope(session)
        request_command = _request(tenant_id, organization_id)
        created_request = TransactionalPaymentIntentEngine.create_request(session, request_command)
        replayed_request = TransactionalPaymentIntentEngine.create_request(session, request_command)
        if created_request.replayed or not replayed_request.replayed:
            raise RuntimeError("payment request replay semantics failed")
        try:
            TransactionalPaymentIntentEngine.create_request(
                session, replace(request_command, requested_amount=Decimal("101"))
            )
        except PaymentCommandIdempotencyConflict:
            pass
        else:
            raise RuntimeError("payment request idempotency conflict was accepted")

        first = _intent(
            tenant_id,
            organization_id,
            suffix=101,
            amount="60",
            request_public_id=request_command.public_id,
        )
        second = _intent(
            tenant_id,
            organization_id,
            suffix=102,
            amount="40",
            request_public_id=request_command.public_id,
        )
        first_result = TransactionalPaymentIntentEngine.create_intent(session, first)
        first_replay = TransactionalPaymentIntentEngine.create_intent(session, first)
        TransactionalPaymentIntentEngine.create_intent(session, second)
        if first_result.replayed or not first_replay.replayed:
            raise RuntimeError("payment intent replay semantics failed")

        over_capacity = _intent(
            tenant_id,
            organization_id,
            suffix=103,
            amount="1",
            request_public_id=request_command.public_id,
        )
        try:
            TransactionalPaymentIntentEngine.create_intent(session, over_capacity)
        except PaymentCommandValidationError as exc:
            if exc.code != "payment_request_capacity_exceeded":
                raise
        else:
            raise RuntimeError("payment request over-capacity intent was accepted")

        standalone = _intent(
            tenant_id,
            organization_id,
            suffix=104,
            amount="25",
            request_public_id=None,
        )
        standalone_result = TransactionalPaymentIntentEngine.create_intent(session, standalone)
        if standalone_result.payment_intent.payment_request_id is not None:
            raise RuntimeError("standalone intent acquired a fake payment request")

        obligation_command = _obligation(tenant_id, organization_id)
        TransactionalObligationEngine.create(session, obligation_command)
        obligation_intent = _intent(
            tenant_id,
            organization_id,
            suffix=105,
            amount="30",
            request_public_id=None,
        )
        obligation_intent = replace(
            obligation_intent,
            financial_obligation_public_id=obligation_command.public_id,
        )
        obligation_result = TransactionalPaymentIntentEngine.create_intent(
            session, obligation_intent
        )
        if obligation_result.payment_intent.financial_obligation_public_id != obligation_command.public_id:
            raise RuntimeError("obligation-linked intent lost its origin authority")
        if PaymentIntentRepository.find_request(
            session, tenant_id=tenant_id + 100000, public_id=request_command.public_id
        ) is not None:
            raise RuntimeError("cross-tenant payment request lookup succeeded")

    with engine.connect() as connection:
        counts = {
            "requests": connection.execute(text("SELECT count(*) FROM canonical_payment_requests")).scalar_one(),
            "intents": connection.execute(text("SELECT count(*) FROM canonical_payment_intents")).scalar_one(),
            "idempotency": connection.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one(),
        }
        if counts != {"requests": 1, "intents": 4, "idempotency": 6}:
            raise RuntimeError(f"unexpected M4.1 atomic counts={counts}")
        rollback_reservation = connection.execute(
            text(
                "SELECT count(*) FROM idempotency_records "
                "WHERE scope='m41.payment_intent' AND idempotency_key='intent-103'"
            )
        ).scalar_one()
        if rollback_reservation:
            raise RuntimeError("failed command retained its idempotency reservation")
        side_effects = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in FORBIDDEN_SIDE_EFFECT_TABLES
        }
        populated = {table: count for table, count in side_effects.items() if count}
        if populated:
            raise RuntimeError(f"M4.1 created forbidden side effects={populated}")


def _create_and_verify() -> None:
    _verify_development()
    _create_clone()
    disposable = None
    try:
        disposable = _engine(TEST_DATABASE_NAME)
        with disposable.connect() as connection:
            if _revision(connection) != TARGET_REVISION:
                raise RuntimeError("disposable clone revision differs")
        _exercise(disposable)
        disposable.dispose()
        disposable = None
        _drop_database(TEST_DATABASE_NAME)
        _verify_development()
        print(
            "m41_payment_commands=PASS "
            f"database={TEST_DATABASE_NAME} request=PASS linked_intent=PASS "
            "obligation_intent=PASS standalone=PASS replay=PASS conflict=PASS capacity=PASS "
            "tenant_scope=PASS rollback=PASS side_effects=0 dropped=true"
        )
    except Exception:
        if disposable is not None:
            disposable.dispose()
        print(f"M4.1 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("verify")
    commands.add_parser("create-and-verify")
    drop = commands.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    arguments = parser.parse_args()
    if arguments.command == "status":
        return 0 if _status() else 1
    if arguments.command == "verify":
        _verify_development()
    elif arguments.command == "create-and-verify":
        _create_and_verify()
    else:
        if arguments.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation is required")
        _drop_database(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
