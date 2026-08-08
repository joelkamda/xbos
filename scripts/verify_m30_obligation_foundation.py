"""Rehearse and verify the empty M3.0 obligation/allocation foundation."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from core.persistence.m30_obligation_foundation import (
    DEVELOPMENT_DATABASE_NAME,
    FOUNDATION_TABLES,
    PARENT_REVISION,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
    expected_development_counts,
)
from database import engine as application_engine


EXPECTED_COLUMNS = {
    "financial_obligations": {
        "public_id", "tenant_id", "organization_unit_id", "debtor_party_id",
        "creditor_party_id", "obligation_type", "obligation_state",
        "original_amount", "currency_code", "due_at", "business_date",
        "occurred_at", "recorded_at", "correlation_id", "actor_user_id",
        "actor_service",
        "idempotency_scope", "idempotency_key", "request_fingerprint",
    },
    "financial_obligation_lines": {
        "public_id", "tenant_id", "organization_unit_id", "obligation_id",
        "line_number", "line_type", "quantity", "unit_amount", "line_amount",
        "currency_code", "occurred_at", "recorded_at", "business_date",
        "calendar_policy_version", "correlation_id", "actor_user_id",
        "actor_service",
    },
    "value_sources": {
        "public_id", "tenant_id", "organization_unit_id", "owner_party_id",
        "source_type", "source_amount", "currency_code",
        "payment_settlement_public_id", "idempotency_scope", "idempotency_key",
        "occurred_at", "recorded_at", "business_date", "correlation_id",
        "actor_user_id", "actor_service",
    },
    "payment_allocations": {
        "public_id", "tenant_id", "organization_unit_id", "value_source_id",
        "obligation_id", "allocation_amount", "currency_code",
        "idempotency_scope", "idempotency_key",
        "cross_organization_policy_code", "cross_organization_policy_version",
        "occurred_at", "recorded_at", "business_date", "correlation_id",
        "actor_user_id", "actor_service",
    },
    "allocation_reversals": {
        "public_id", "tenant_id", "organization_unit_id",
        "payment_allocation_id", "reversal_amount", "currency_code",
        "reason_code", "idempotency_scope", "idempotency_key",
        "occurred_at", "recorded_at", "business_date", "correlation_id",
        "actor_user_id", "actor_service",
    },
}


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _database_url(database_name: str):
    return _application_url().set(database=database_name)


def _engine(database_name: str, *, autocommit: bool = False):
    options = {"pool_pre_ping": True}
    if autocommit:
        options["isolation_level"] = "AUTOCOMMIT"
    return create_engine(_database_url(database_name), **options)


def _exists(database_name: str) -> bool:
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": database_name},
                ).scalar_one_or_none()
            )
    finally:
        engine.dispose()


def _create(database_name: str) -> None:
    if _exists(database_name):
        raise RuntimeError(f"disposable database already exists: {database_name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}" TEMPLATE template0'))
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
    os.environ["DATABASE_URL"] = _database_url(database_name).render_as_string(
        hide_password=False
    )
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _alembic_config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _upgrade(database_name: str, revision: str = TARGET_REVISION) -> None:
    with _selected_database(database_name):
        alembic_command.upgrade(_alembic_config(), revision)


def _downgrade(database_name: str) -> None:
    with _selected_database(database_name):
        alembic_command.downgrade(_alembic_config(), PARENT_REVISION)


def _revision(connection) -> str | None:
    return connection.execute(
        text("SELECT version_num FROM public.alembic_version")
    ).scalar_one_or_none()


def _table_names(connection) -> set[str]:
    return set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
    )


def _verify_schema(database_name: str) -> None:
    engine = _engine(database_name)
    try:
        with engine.connect() as connection:
            revision = _revision(connection)
            if revision != TARGET_REVISION:
                raise RuntimeError(f"expected revision {TARGET_REVISION}, found {revision}")
            tables = _table_names(connection)
            missing = set(FOUNDATION_TABLES) - tables
            if missing:
                raise RuntimeError(f"missing M3.0 tables: {sorted(missing)}")
            for table, expected in EXPECTED_COLUMNS.items():
                columns = set(
                    connection.execute(
                        text("SELECT column_name FROM information_schema.columns "
                             "WHERE table_schema = 'public' AND table_name = :table"),
                        {"table": table},
                    ).scalars()
                )
                if not expected.issubset(columns):
                    raise RuntimeError(
                        f"{table} missing columns: {sorted(expected - columns)}"
                    )
                count = connection.execute(
                    text(f"SELECT count(*) FROM public.{table}")
                ).scalar_one()
                if count != 0:
                    raise RuntimeError(f"expected empty {table}, found {count}")
            trigger_count = connection.execute(
                text("SELECT count(*) FROM pg_trigger t "
                     "JOIN pg_class c ON c.oid = t.tgrelid "
                     "JOIN pg_namespace n ON n.oid = c.relnamespace "
                     "WHERE n.nspname = 'public' AND NOT t.tgisinternal "
                     "AND c.relname = ANY(:tables)"),
                {"tables": list(FOUNDATION_TABLES)},
            ).scalar_one()
            if trigger_count != 7:
                raise RuntimeError(f"expected 7 M3.0 guard triggers, found {trigger_count}")
    finally:
        engine.dispose()


def _verify_downgrade(database_name: str) -> None:
    engine = _engine(database_name)
    try:
        with engine.connect() as connection:
            if _revision(connection) != PARENT_REVISION:
                raise RuntimeError("M3.0 downgrade did not restore the M2 revision")
            remaining = set(FOUNDATION_TABLES) & _table_names(connection)
            if remaining:
                raise RuntimeError(f"M3.0 downgrade retained tables: {sorted(remaining)}")
    finally:
        engine.dispose()


def _verify_development() -> None:
    selected = _application_url().database
    if selected != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"refusing development verification against {selected!r}")
    expected = expected_development_counts()
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision != TARGET_REVISION:
            raise RuntimeError(f"expected development revision {TARGET_REVISION}, found {revision}")
        counts = {
            table: int(connection.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one())
            for table in expected
        }
    if counts != expected:
        raise RuntimeError(f"development counts differ: {counts!r}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={TARGET_REVISION}")
    for table, count in counts.items():
        print(f"{table}={count}")
    print("m30_obligation_foundation_development=PASS")


def _create_and_verify() -> None:
    _create(TEST_DATABASE_NAME)
    try:
        _upgrade(TEST_DATABASE_NAME)
        _verify_schema(TEST_DATABASE_NAME)
        _downgrade(TEST_DATABASE_NAME)
        _verify_downgrade(TEST_DATABASE_NAME)
        _upgrade(TEST_DATABASE_NAME)
        _verify_schema(TEST_DATABASE_NAME)
    except Exception:
        print(
            f"M3.0 verification failed; retained disposable database={TEST_DATABASE_NAME}",
            file=sys.stderr,
        )
        raise
    _drop(TEST_DATABASE_NAME)
    print(
        "m30_obligation_foundation=PASS "
        f"database={TEST_DATABASE_NAME} tables=5 tenant_scope=PASS "
        "currency_scope=PASS cross_org_ready=PASS immutability=PASS empty=PASS "
        "upgrade_downgrade_upgrade=PASS dropped=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("verify")
    subparsers.add_parser("create-and-verify")
    drop = subparsers.add_parser("drop")
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
            raise RuntimeError("database confirmation does not match guarded M3.0 target")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
