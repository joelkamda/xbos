"""Read-only development gate and disposable M4.2 payment-attempt rehearsal."""

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

from core.domain.finance.payment_attempt_contract import (
    CreatePaymentAttemptCommand,
    PaymentAttemptValidationError,
    TransitionPaymentAttemptCommand,
)
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_attempt_repository import PaymentAttemptRepository
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand, PaymentCommandIdempotencyConflict
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.persistence.m40_payment_foundation import FOUNDATION_TABLES
from core.persistence.m42_payment_attempts import (
    FORBIDDEN_SIDE_EFFECT_TABLES,
    M42_COLUMNS,
    M42_TABLES,
    M42_TRIGGERS,
    PARENT_REVISION,
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


@contextmanager
def _migration_database(database_name: str):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=database_name).render_as_string(
        hide_password=False
    )
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _migrate(database_name: str, revision: str, *, downgrade: bool = False) -> None:
    with _migration_database(database_name):
        config = Config(str(ROOT / "alembic.ini"))
        if downgrade:
            alembic_command.downgrade(config, revision)
        else:
            alembic_command.upgrade(config, revision)


def _revision(connection) -> str:
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _schema(connection, *, expected: bool) -> None:
    tables = set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        ).scalars()
    )
    columns = set(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='canonical_payment_attempts'"
            )
        ).scalars()
    )
    triggers = set(
        connection.execute(
            text(
                "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND NOT t.tgisinternal"
            )
        ).scalars()
    )
    if expected:
        if set(M42_TABLES) - tables or set(M42_COLUMNS) - columns or set(M42_TRIGGERS) - triggers:
            raise RuntimeError("M4.2 schema inventory is incomplete")
    elif set(M42_TABLES) & tables or set(M42_COLUMNS) & columns or set(M42_TRIGGERS) & triggers:
        raise RuntimeError("M4.2 schema remains at parent revision")


def _verify_development() -> str:
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}:
            raise RuntimeError(f"unexpected development revision={revision}")
        for table in FOUNDATION_TABLES:
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development payment table is not empty={table}")
        for table in ("idempotency_records", "financial_events", "outbox_messages", "value_sources"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development side-effect table is not empty={table}")
        _schema(connection, expected=revision == TARGET_REVISION)
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m42_payment_attempts_development=PASS")
    return revision


def _status() -> bool:
    exists = _database_exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _seed_scope(session) -> tuple[int, int, int]:
    tenant_id = session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO currency_assets (
                code, asset_kind, display_name, minor_unit_scale, maximum_storage_scale, active
            ) VALUES ('XAF', 'fiat', 'Central African CFA franc', 0, 8, true)
            ON CONFLICT (code) DO NOTHING
            """
        )
    )
    organization_id = session.execute(
        text("SELECT id FROM organization_units WHERE tenant_id=:tenant ORDER BY id LIMIT 1"),
        {"tenant": tenant_id},
    ).scalar_one_or_none()
    if organization_id is None:
        organization_id = session.execute(
            text(
                """
                INSERT INTO organization_units (
                    tenant_id, unit_type, code, name, timezone_name, active
                ) VALUES (:tenant, 'branch', 'm42-verifier', 'M4.2 Verifier', 'Africa/Douala', true)
                RETURNING id
                """
            ),
            {"tenant": tenant_id},
        ).scalar_one()
    provider_id = session.execute(
        text(
            """
            INSERT INTO payment_provider_accounts (
                tenant_id, organization_unit_id, provider_code,
                external_account_reference, credential_reference,
                environment, active
            ) VALUES (
                :tenant, :organization, 'mtn_momo',
                'm42-sandbox-account', 'secret://m42-sandbox',
                'sandbox', true
            )
            ON CONFLICT (provider_code, environment, external_account_reference)
            DO UPDATE SET active=true
            RETURNING id
            """
        ),
        {"tenant": tenant_id, "organization": organization_id},
    ).scalar_one()
    return int(tenant_id), int(organization_id), int(provider_id)


def _intent(tenant: int, organization: int) -> CreatePaymentIntentCommand:
    return CreatePaymentIntentCommand(
        public_id=UUID("42000000-0000-0000-0000-000000000001"),
        tenant_id=tenant,
        organization_unit_id=organization,
        requested_amount=Decimal("100"),
        currency_code="XAF",
        payment_method_policy={"allowed_methods": ["mobile_money"], "max_tenders": 1},
        expires_at=BASE + timedelta(hours=2),
        occurred_at=BASE,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("42000000-0000-0000-0000-000000000002"),
        actor_service="m42.verifier",
        source_component="m42.verifier",
        source_record_id="intent-1",
        idempotency_scope="m42.intent_seed",
        idempotency_key="intent-1",
    )


def _attempt(
    tenant: int,
    organization: int,
    provider_public_id: UUID,
    *,
    number: int,
    retry_of: UUID | None = None,
) -> CreatePaymentAttemptCommand:
    occurred = BASE + timedelta(minutes=(number - 1) * 10 + 1)
    return CreatePaymentAttemptCommand(
        public_id=UUID(f"42000000-0000-0000-0000-{100 + number:012d}"),
        tenant_id=tenant,
        organization_unit_id=organization,
        payment_intent_public_id=UUID("42000000-0000-0000-0000-000000000001"),
        attempted_amount=Decimal("100"),
        currency_code="XAF",
        payment_method_code="mobile_money",
        payment_rail_code="mtn_momo",
        orchestrator_code="xbos_direct",
        provider_account_public_id=provider_public_id,
        underlying_provider_code="mtn_momo",
        retry_of_attempt_public_id=retry_of,
        timeout_at=occurred + timedelta(minutes=5),
        occurred_at=occurred,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("42000000-0000-0000-0000-000000000002"),
        actor_service="m42.verifier",
        source_component="m42.verifier",
        source_record_id=f"attempt-{number}",
        idempotency_scope="m42.attempt",
        idempotency_key=f"attempt-{number}",
    )


def _transition(
    attempt: CreatePaymentAttemptCommand,
    *,
    version: int,
    state: str,
    key: str,
    occurred: datetime,
    reference: str | None = None,
    failure: str | None = None,
    evidence=None,
) -> TransitionPaymentAttemptCommand:
    return TransitionPaymentAttemptCommand(
        tenant_id=attempt.tenant_id,
        organization_unit_id=attempt.organization_unit_id,
        payment_attempt_public_id=attempt.public_id,
        expected_row_version=version,
        target_state=state,
        reason_code=key,
        external_attempt_reference=reference,
        failure_code=failure,
        evidence_payload=evidence or {},
        occurred_at=occurred,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=attempt.correlation_id,
        actor_service="m42.verifier",
        source_component="m42.verifier",
        source_record_id=key,
        idempotency_scope="m42.attempt_transition",
        idempotency_key=key,
    )


def _exercise(engine) -> None:
    with Session(engine) as session, session.begin():
        tenant, organization, provider_id = _seed_scope(session)
        provider_public_id = UUID(
            str(
                session.execute(
                    text("SELECT public_id FROM payment_provider_accounts WHERE id=:id"),
                    {"id": provider_id},
                ).scalar_one()
            )
        )
        TransactionalPaymentIntentEngine.create_intent(session, _intent(tenant, organization))

        first = _attempt(tenant, organization, provider_public_id, number=1)
        created = TransactionalPaymentAttemptEngine.create(session, first)
        replayed = TransactionalPaymentAttemptEngine.create(session, first)
        if created.replayed or not replayed.replayed:
            raise RuntimeError("attempt creation replay failed")
        try:
            TransactionalPaymentAttemptEngine.create(
                session, replace(first, attempted_amount=Decimal("99"))
            )
        except PaymentCommandIdempotencyConflict:
            pass
        else:
            raise RuntimeError("attempt creation conflict was accepted")

        TransactionalPaymentAttemptEngine.transition(
            session,
            _transition(
                first,
                version=1,
                state="processing",
                key="attempt_1_processing",
                occurred=first.occurred_at + timedelta(seconds=10),
                reference="mtn-ref-001",
            ),
        )
        failed = _transition(
            first,
            version=2,
            state="failed",
            key="attempt_1_failed",
            occurred=first.occurred_at + timedelta(minutes=1),
            reference="mtn-ref-001",
            failure="provider_declined",
            evidence={"provider_status": "declined", "code": "51"},
        )
        failure_result = TransactionalPaymentAttemptEngine.transition(session, failed)
        failure_replay = TransactionalPaymentAttemptEngine.transition(session, failed)
        if failure_result.replayed or not failure_replay.replayed:
            raise RuntimeError("attempt transition replay failed")

        second = _attempt(
            tenant, organization, provider_public_id, number=2, retry_of=first.public_id
        )
        TransactionalPaymentAttemptEngine.create(session, second)
        TransactionalPaymentAttemptEngine.transition(
            session,
            _transition(
                second,
                version=1,
                state="processing",
                key="attempt_2_processing",
                occurred=second.occurred_at + timedelta(seconds=10),
                reference="mtn-ref-002",
            ),
        )
        early = _transition(
            second,
            version=2,
            state="expired",
            key="attempt_2_early_expiry",
            occurred=second.timeout_at - timedelta(seconds=1),
            evidence={"clock": "early"},
        )
        try:
            TransactionalPaymentAttemptEngine.transition(session, early)
        except PaymentAttemptValidationError as exc:
            if exc.code != "attempt_timeout_not_reached":
                raise
        else:
            raise RuntimeError("attempt expired before timeout")
        TransactionalPaymentAttemptEngine.transition(
            session,
            _transition(
                second,
                version=2,
                state="expired",
                key="attempt_2_expired",
                occurred=second.timeout_at,
                evidence={"timeout_at": second.timeout_at.isoformat()},
            ),
        )

        third = _attempt(
            tenant, organization, provider_public_id, number=3, retry_of=second.public_id
        )
        TransactionalPaymentAttemptEngine.create(session, third)
        TransactionalPaymentAttemptEngine.transition(
            session,
            _transition(
                third,
                version=1,
                state="processing",
                key="attempt_3_processing",
                occurred=third.occurred_at + timedelta(seconds=10),
                reference="mtn-ref-003",
            ),
        )
        conflicting_reference = _transition(
            third,
            version=2,
            state="succeeded",
            key="attempt_3_wrong_reference",
            occurred=third.occurred_at + timedelta(minutes=1),
            reference="mtn-ref-changed",
            evidence={"provider_status": "success"},
        )
        try:
            TransactionalPaymentAttemptEngine.transition(session, conflicting_reference)
        except PaymentAttemptValidationError as exc:
            if exc.code != "external_reference_conflict":
                raise
        else:
            raise RuntimeError("external attempt reference was rewritten")
        TransactionalPaymentAttemptEngine.transition(
            session,
            _transition(
                third,
                version=2,
                state="succeeded",
                key="attempt_3_succeeded",
                occurred=third.occurred_at + timedelta(minutes=1),
                reference="mtn-ref-003",
                evidence={"provider_status": "success", "provider_time": "12:22:00Z"},
            ),
        )
        if PaymentAttemptRepository.find_attempt(
            session, tenant_id=tenant + 100000, public_id=first.public_id
        ) is not None:
            raise RuntimeError("cross-tenant attempt lookup succeeded")

    with engine.connect() as connection:
        counts = {
            "intents": connection.execute(text("SELECT count(*) FROM canonical_payment_intents")).scalar_one(),
            "attempts": connection.execute(text("SELECT count(*) FROM canonical_payment_attempts")).scalar_one(),
            "transitions": connection.execute(text("SELECT count(*) FROM canonical_payment_attempt_transitions")).scalar_one(),
            "idempotency": connection.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one(),
        }
        if counts != {"intents": 1, "attempts": 3, "transitions": 9, "idempotency": 10}:
            raise RuntimeError(f"unexpected M4.2 atomic counts={counts}")
        failed = connection.execute(
            text(
                "SELECT attempt_state, failure_code, external_attempt_reference "
                "FROM canonical_payment_attempts WHERE public_id=:public_id"
            ),
            {"public_id": str(UUID("42000000-0000-0000-0000-000000000101"))},
        ).mappings().one()
        if dict(failed) != {
            "attempt_state": "failed",
            "failure_code": "provider_declined",
            "external_attempt_reference": "mtn-ref-001",
        }:
            raise RuntimeError("failed attempt evidence was not preserved")
        for statement in (
            "UPDATE canonical_payment_attempts SET attempt_state='processing' WHERE public_id='42000000-0000-0000-0000-000000000101'",
            "UPDATE canonical_payment_attempt_transitions SET reason_code='changed' WHERE payment_attempt_id=(SELECT id FROM canonical_payment_attempts WHERE public_id='42000000-0000-0000-0000-000000000101')",
        ):
            try:
                with connection.begin_nested():
                    connection.exec_driver_sql(statement)
            except DBAPIError:
                pass
            else:
                raise RuntimeError("direct SQL bypass succeeded")
        side_effects = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in FORBIDDEN_SIDE_EFFECT_TABLES
        }
        populated = {table: count for table, count in side_effects.items() if count}
        if populated:
            raise RuntimeError(f"M4.2 created forbidden side effects={populated}")


def _create_and_verify() -> None:
    if _verify_development() != PARENT_REVISION:
        raise RuntimeError(f"development must start at {PARENT_REVISION}")
    _create_clone()
    disposable = None
    try:
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        disposable = _engine(TEST_DATABASE_NAME)
        with disposable.connect() as connection:
            if _revision(connection) != TARGET_REVISION:
                raise RuntimeError("disposable did not reach M4.2")
            _schema(connection, expected=True)
        disposable.dispose()
        disposable = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        disposable = _engine(TEST_DATABASE_NAME)
        with disposable.connect() as connection:
            if _revision(connection) != PARENT_REVISION:
                raise RuntimeError("disposable did not downgrade to M4.0")
            _schema(connection, expected=False)
        disposable.dispose()
        disposable = None
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        disposable = _engine(TEST_DATABASE_NAME)
        _exercise(disposable)
        disposable.dispose()
        disposable = None
        _drop_database(TEST_DATABASE_NAME)
        _verify_development()
        print(
            "m42_payment_attempts=PASS "
            f"database={TEST_DATABASE_NAME} multiple_attempts=PASS provider_reference=PASS "
            "failure_preservation=PASS timeout=PASS retry=PASS replay=PASS conflict=PASS "
            "tenant_scope=PASS append_only_evidence=PASS direct_sql=PASS side_effects=0 "
            "upgrade_downgrade_upgrade=PASS dropped=true"
        )
    except Exception:
        if disposable is not None:
            disposable.dispose()
        print(f"M4.2 verification failed; retained disposable database={TEST_DATABASE_NAME}")
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
