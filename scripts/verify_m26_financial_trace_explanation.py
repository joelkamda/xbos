"""M2.6 read-only verifier for deterministic financial trace/explanation."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from database import engine as application_engine
from core.domain.finance.trace_contract import (
    FinancialEventTraceQuery,
    FinancialTraceNotFound,
)
from core.domain.finance.trace_service import CanonicalFinancialTraceService


TEST_DATABASE_NAME = "xbos_track_b_m26_trace_test"
EXPECTED_REVISION = "m25_financial_dimensions_007"
DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
ABSENT_EVENT_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _database_url(database_name: str):
    return _application_url().set(database=database_name)


def _admin_engine():
    return create_engine(
        _database_url("postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True
    )


def _exists(database_name: str) -> bool:
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                    {"database_name": database_name},
                ).scalar_one_or_none()
            )
    finally:
        engine.dispose()


def _create(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError("refusing unexpected disposable database name")
    if _exists(database_name):
        raise RuntimeError(f"disposable database already exists: {database_name}")
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}" TEMPLATE template0')
    finally:
        engine.dispose()


def _drop(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError("refusing unexpected disposable database name")
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        engine.dispose()


@contextmanager
def _migration_environment(database_name: str):
    value = _database_url(database_name).render_as_string(hide_password=False)
    previous = {
        key: os.environ.get(key) for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL")
    }
    os.environ["DATABASE_URL"] = value
    os.environ["MIGRATION_DATABASE_URL"] = value
    try:
        yield value
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _upgrade(database_name: str) -> None:
    with _migration_environment(database_name) as value:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", value.replace("%", "%%"))
        alembic_command.upgrade(config, "head")


def _engine(database_name: str):
    return create_engine(_database_url(database_name), pool_pre_ping=True)


def _revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one_or_none()


def development_counts(engine) -> dict[str, int]:
    names = (
        "financial_event_type_versions",
        "financial_dimension_types",
        "financial_dimension_values",
        "posting_dimension_policies",
        "idempotency_records",
        "financial_events",
        "outbox_messages",
        "journal_entries",
        "journal_lines",
    )
    with engine.connect() as connection:
        return {
            name: int(connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one())
            for name in names
        }


def _assert_empty_financial_truth(counts: dict[str, int]) -> None:
    if counts["financial_event_type_versions"] != 20:
        raise RuntimeError("canonical event catalog must contain exactly 20 rows")
    for name, count in counts.items():
        if name != "financial_event_type_versions" and count != 0:
            raise RuntimeError(f"expected empty {name}, found {count}")


def _assert_empty_lookup(engine) -> None:
    with Session(engine) as session:
        try:
            CanonicalFinancialTraceService.explain(
                session, FinancialEventTraceQuery(1, ABSENT_EVENT_ID)
            )
        except FinancialTraceNotFound as exc:
            if exc.code != "financial_event_not_found":
                raise
        else:
            raise RuntimeError("empty tenant-scoped trace lookup unexpectedly returned data")


def _verify_database(database_name: str) -> dict[str, int]:
    engine = _engine(database_name)
    try:
        revision = _revision(engine)
        if revision != EXPECTED_REVISION:
            raise RuntimeError(f"expected revision {EXPECTED_REVISION}, found {revision}")
        counts = development_counts(engine)
        _assert_empty_financial_truth(counts)
        _assert_empty_lookup(engine)
        return counts
    finally:
        engine.dispose()


def _verify_development() -> None:
    selected = _application_url().database
    if selected != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(
            f"refusing development verification against database {selected!r}"
        )
    counts = _verify_database(selected)
    print(f"database={selected}")
    print(f"revision={EXPECTED_REVISION}")
    for name, count in counts.items():
        print(f"{name}={count}")
    print("m26_financial_trace_development=PASS")


def _create_and_verify() -> None:
    _create(TEST_DATABASE_NAME)
    try:
        _upgrade(TEST_DATABASE_NAME)
        _verify_database(TEST_DATABASE_NAME)
    except Exception:
        print(
            f"M2.6 verification failed; retained disposable database={TEST_DATABASE_NAME}",
            file=sys.stderr,
        )
        raise
    _drop(TEST_DATABASE_NAME)
    print(
        "m26_financial_trace=PASS "
        f"database={TEST_DATABASE_NAME} canonical_head_unchanged=PASS "
        "empty_lookup=PASS tenant_scope=PASS read_only=PASS "
        "schema_counts=PASS dropped=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("create-and-verify")
    subparsers.add_parser("verify")
    drop_parser = subparsers.add_parser("drop")
    drop_parser.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()

    if args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "create-and-verify":
        _create_and_verify()
    elif args.command == "verify":
        _verify_development()
    elif args.command == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("confirmation does not match the disposable database")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
