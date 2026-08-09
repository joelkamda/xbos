"""Verify the transactional M3.1 obligation engine on one disposable database."""

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


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.domain.finance.obligation_balance_service import ObligationBalanceService
from core.domain.finance.obligation_contract import (
    CreateObligationCommand,
    ObligationIdempotencyConflict,
    ObligationLineCommand,
    ObligationValidationError,
    TransitionObligationCommand,
)
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from database import engine as application_engine


TEST_DATABASE_NAME = "xbos_track_b_m31_obligation_test"
DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TARGET_REVISION = "m30_obligation_foundation_008"
DEVELOPMENT_REVISIONS = {
    TARGET_REVISION,
    "m32_allocation_engine_009",
    "m34_obligation_aging_010",
}
TENANT_ID = 3101
ORG_ID = 3111
NOW = datetime(2026, 8, 9, 10, tzinfo=timezone.utc)
OBLIGATION_ID = UUID("31000000-0000-0000-0000-000000000001")
SECOND_OBLIGATION_ID = UUID("31000000-0000-0000-0000-000000000002")
DEBTOR = UUID("31000000-0000-0000-0000-000000000010")
CREDITOR = UUID("31000000-0000-0000-0000-000000000011")

DEVELOPMENT_COUNTS = {
    "financial_event_type_versions": 20,
    "financial_dimension_types": 0,
    "financial_dimension_values": 0,
    "posting_dimension_policies": 0,
    "idempotency_records": 0,
    "financial_events": 0,
    "outbox_messages": 0,
    "journal_entries": 0,
    "journal_lines": 0,
    "financial_obligations": 0,
    "financial_obligation_lines": 0,
    "value_sources": 0,
    "payment_allocations": 0,
    "allocation_reversals": 0,
}


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _url(database_name: str):
    return _application_url().set(database=database_name)


def _engine(database_name: str, *, autocommit: bool = False):
    options = {"pool_pre_ping": True}
    if autocommit:
        options["isolation_level"] = "AUTOCOMMIT"
    return create_engine(_url(database_name), **options)


def _exists(database_name: str) -> bool:
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database_name}
            ).scalar_one_or_none())
    finally:
        engine.dispose()


def _create() -> None:
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally:
        engine.dispose()


def _drop(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"refusing to drop unapproved database: {database_name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE datname = :name AND pid <> pg_backend_pid()"),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@contextmanager
def _selected_database(database_name: str):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(database_name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _upgrade() -> None:
    with _selected_database(TEST_DATABASE_NAME):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)


def _seed(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public.tenants
                (id, code, name, country_code, country_name, currency, locale,
                 timezone, settings, extra_metadata)
            VALUES (:tenant, 'M31T', 'M3.1 Proof Tenant', 'CM', 'Cameroon',
                    'XAF', 'en-CM', 'Africa/Douala', '{}'::json, '{}'::json)
        """), {"tenant": TENANT_ID})
        connection.execute(text("""
            INSERT INTO public.currency_assets
                (code, asset_kind, display_name, minor_unit_scale,
                 maximum_storage_scale, active, metadata)
            VALUES ('XAF', 'fiat', 'Central African CFA franc', 0, 8, TRUE, '{}'::jsonb)
        """))
        connection.execute(text("""
            INSERT INTO public.organization_units
                (id, tenant_id, unit_type, code, name, timezone_name, active)
            VALUES (:org, :tenant, 'legal_entity', 'M31', 'M3.1 Proof Entity',
                    'Africa/Douala', TRUE)
        """), {"org": ORG_ID, "tenant": TENANT_ID})


def _line(amount: str, source: str) -> ObligationLineCommand:
    return ObligationLineCommand(
        line_number=1,
        line_type="principal",
        description="Obligation principal",
        quantity=Decimal("1"),
        unit_amount=Decimal(amount),
        line_amount=Decimal(amount),
        source_record_id=source,
    )


def _command(
    public_id: UUID = OBLIGATION_ID,
    *,
    amount: str = "1000",
    key: str = "create-1",
    source: str = "obligation-1",
) -> CreateObligationCommand:
    return CreateObligationCommand(
        public_id=public_id,
        tenant_id=TENANT_ID,
        organization_unit_id=ORG_ID,
        debtor_party_id=DEBTOR,
        creditor_party_id=CREDITOR,
        obligation_type="trade_receivable",
        original_amount=Decimal(amount),
        currency_code="XAF",
        due_at=NOW + timedelta(days=30),
        occurred_at=NOW,
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID("31000000-0000-0000-0000-000000000020"),
        actor_service="m31.verifier",
        source_component="m31.verifier",
        source_record_id=source,
        idempotency_scope="m31.create",
        idempotency_key=key,
        lines=(_line(amount, source + "-line"),),
    )


def _expect_rejection(session: Session, action, error_type, code: str) -> None:
    try:
        with session.begin_nested():
            action()
    except error_type as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected {code}, found {getattr(exc, 'code', None)}") from exc
    else:
        raise RuntimeError(f"expected rejection {code}")


def _install_allocations(session: Session, obligation_id: int) -> None:
    source_id = session.execute(text("""
        INSERT INTO public.value_sources (
            tenant_id, organization_unit_id, owner_party_id, source_type,
            source_amount, currency_code, occurred_at, business_date,
            calendar_policy_version, correlation_id, actor_service,
            source_component, source_record_id, idempotency_scope,
            idempotency_key, request_fingerprint
        ) VALUES (
            :tenant, :org, :owner, 'confirmed_value', 1000, 'XAF', :occurred,
            :business_date, 1, :correlation, 'm31.verifier', 'm31.verifier',
            'value-1', 'm31.fixture.value', 'value-1', :fingerprint
        ) RETURNING id
    """), {
        "tenant": TENANT_ID, "org": ORG_ID, "owner": str(DEBTOR), "occurred": NOW,
        "business_date": date(2026, 8, 9),
        "correlation": "31000000-0000-0000-0000-000000000020",
        "fingerprint": "a" * 64,
    }).scalar_one()
    for index, amount in enumerate((Decimal("400"), Decimal("600")), start=1):
        session.execute(text("""
            INSERT INTO public.payment_allocations (
                tenant_id, organization_unit_id, value_source_id, obligation_id,
                allocation_amount, currency_code, occurred_at, business_date,
                calendar_policy_version, correlation_id, actor_service,
                source_component, source_record_id, idempotency_scope,
                idempotency_key, request_fingerprint
            ) VALUES (
                :tenant, :org, :source, :obligation, :amount, 'XAF', :occurred,
                :business_date, 1, :correlation, 'm31.verifier', 'm31.verifier',
                :record, 'm31.fixture.allocation', :record, :fingerprint
            )
        """), {
            "tenant": TENANT_ID, "org": ORG_ID, "source": source_id,
            "obligation": obligation_id, "amount": amount, "occurred": NOW,
            "business_date": date(2026, 8, 9),
            "correlation": "31000000-0000-0000-0000-000000000020",
            "record": f"allocation-{index}", "fingerprint": str(index) * 64,
        })
        yield index


def _verify_engine(engine) -> None:
    command = _command()
    with Session(engine) as session, session.begin():
        created = TransactionalObligationEngine.create(session, command)
        if created.replayed or created.obligation.line_count != 1:
            raise RuntimeError("typed creation did not create one obligation line")
    with Session(engine) as session, session.begin():
        replay = TransactionalObligationEngine.create(session, command)
        if not replay.replayed or replay.obligation.id != created.obligation.id:
            raise RuntimeError("identical command did not replay stable identity")
        _expect_rejection(
            session,
            lambda: TransactionalObligationEngine.create(session, replace(command, original_amount=Decimal("1001"), lines=(_line("1001", "changed-line"),))),
            ObligationIdempotencyConflict,
            "obligation_idempotency_conflict",
        )
        _expect_rejection(
            session,
            lambda: ObligationBalanceService.get(session, tenant_id=TENANT_ID + 1, obligation_public_id=OBLIGATION_ID),
            ObligationValidationError,
            "obligation_not_found",
        )
    try:
        replace(command, original_amount=Decimal("999"))
    except ObligationValidationError as exc:
        if exc.code != "line_total_mismatch":
            raise
    else:
        raise RuntimeError("line-total mismatch was accepted")

    with Session(engine) as session, session.begin():
        balance = ObligationBalanceService.get(session, tenant_id=TENANT_ID, obligation_public_id=OBLIGATION_ID)
        if balance.outstanding_amount != Decimal("1000") or balance.projected_state != "open":
            raise RuntimeError("initial derived balance is incorrect")
        allocation_steps = _install_allocations(session, created.obligation.id)
        next(allocation_steps)
        partial = TransactionalObligationEngine.refresh_satisfaction_state(
            session, tenant_id=TENANT_ID, obligation_public_id=OBLIGATION_ID
        )
        if partial.outstanding_amount != Decimal("600") or partial.stored_state != "partially_satisfied":
            raise RuntimeError("partial balance projection failed")
        next(allocation_steps)
        satisfied = TransactionalObligationEngine.refresh_satisfaction_state(
            session, tenant_id=TENANT_ID, obligation_public_id=OBLIGATION_ID
        )
        if satisfied.outstanding_amount != 0 or satisfied.stored_state != "satisfied":
            raise RuntimeError("satisfied balance projection failed")

    second = _command(SECOND_OBLIGATION_ID, amount="500", key="create-2", source="obligation-2")
    with Session(engine) as session, session.begin():
        second_result = TransactionalObligationEngine.create(session, second)
        transition = TransitionObligationCommand(
            tenant_id=TENANT_ID,
            obligation_public_id=SECOND_OBLIGATION_ID,
            target_state="cancelled",
            expected_row_version=1,
            reason_code="customer_cancelled",
            idempotency_scope="m31.transition",
            idempotency_key="cancel-2",
            actor_service="m31.verifier",
        )
        cancelled = TransactionalObligationEngine.transition(session, transition)
        if cancelled.obligation.obligation_state != "cancelled" or cancelled.obligation.row_version != 2:
            raise RuntimeError("governed cancellation failed")
    with Session(engine) as session, session.begin():
        if not TransactionalObligationEngine.transition(session, transition).replayed:
            raise RuntimeError("transition replay failed")

    rollback_command = _command(
        UUID("31000000-0000-0000-0000-000000000003"), amount="300", key="rollback", source="rollback"
    )
    with Session(engine) as session:
        TransactionalObligationEngine.create(session, rollback_command)
        session.rollback()
    with engine.connect() as connection:
        if connection.execute(text("SELECT count(*) FROM public.financial_obligations")).scalar_one() != 2:
            raise RuntimeError("outer rollback retained an obligation")
        counts = {
            "idempotency": connection.execute(text("SELECT count(*) FROM public.idempotency_records")).scalar_one(),
            "obligations": connection.execute(text("SELECT count(*) FROM public.financial_obligations")).scalar_one(),
            "lines": connection.execute(text("SELECT count(*) FROM public.financial_obligation_lines")).scalar_one(),
            "sources": connection.execute(text("SELECT count(*) FROM public.value_sources")).scalar_one(),
            "allocations": connection.execute(text("SELECT count(*) FROM public.payment_allocations")).scalar_one(),
        }
        if counts != {"idempotency": 3, "obligations": 2, "lines": 2, "sources": 1, "allocations": 2}:
            raise RuntimeError(f"unexpected atomic counts: {counts!r}")
    with engine.connect() as connection:
        transaction = connection.begin()
        savepoint = connection.begin_nested()
        try:
            connection.execute(text("UPDATE public.financial_obligation_lines SET line_amount = 1"))
        except SQLAlchemyError:
            savepoint.rollback()
        else:
            raise RuntimeError("immutable obligation line accepted update")
        transaction.rollback()


def _verify_development() -> None:
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"refusing development verification against {_application_url().database!r}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one_or_none()
        if revision not in DEVELOPMENT_REVISIONS:
            raise RuntimeError(f"unexpected development revision {revision}")
        counts = {name: int(connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one()) for name in DEVELOPMENT_COUNTS}
    if counts != DEVELOPMENT_COUNTS:
        raise RuntimeError(f"development counts differ: {counts!r}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m31_obligation_development=PASS")


def _create_and_verify() -> None:
    _verify_development()
    _create()
    try:
        _upgrade()
        engine = _engine(TEST_DATABASE_NAME)
        try:
            _seed(engine)
            _verify_engine(engine)
        finally:
            engine.dispose()
        _verify_development()
    except Exception:
        print(f"M3.1 verification failed; retained disposable database={TEST_DATABASE_NAME}", file=sys.stderr)
        raise
    _drop(TEST_DATABASE_NAME)
    print(
        "m31_typed_obligation=PASS "
        f"database={TEST_DATABASE_NAME} creation=PASS replay=PASS conflict=PASS "
        "line_total=PASS balances=PASS lifecycle=PASS tenant_isolation=PASS "
        "immutability=PASS rollback=PASS development_empty=PASS dropped=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("verify")
    commands.add_parser("create-and-verify")
    drop = commands.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()
    if args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "verify":
        _verify_development()
    elif args.command == "create-and-verify":
        _create_and_verify()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("database confirmation does not match guarded M3.1 target")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
