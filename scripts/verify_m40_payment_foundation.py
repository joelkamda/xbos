"""Read-only development gate and disposable rehearsal for M4.0."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.m3_acceptance import (
    revision_preserves_m3_checkpoint,
    validate_release_manifest,
)
from core.persistence.m40_payment_foundation import (
    FOUNDATION_TABLES,
    FROZEN_EMPTY_TABLES,
    LEGACY_COEXISTENCE_TABLES,
    PARENT_REVISION,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
)
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
REQUIRED_CONSTRAINTS = {
    "fk_canonical_payment_intents_request",
    "fk_canonical_payment_attempts_tender",
    "fk_canonical_payment_attempts_provider_account",
    "uq_provider_callback_events_provider_event",
    "fk_payment_settlements_operational_account",
    "ck_payment_settlements_external_evidence",
    "fk_payment_settlement_reversals_settlement",
    "fk_value_sources_payment_settlement",
}
REQUIRED_TRIGGERS = {
    "trg_provider_callback_events_immutable",
    "trg_payment_settlement_reversals_immutable",
}


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _engine(database_name: str, *, isolation_level: str | None = None):
    return create_engine(
        _application_url().set(database=database_name),
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


def _create_database(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={database_name}")
    if _database_exists(database_name):
        raise RuntimeError(f"disposable database already exists={database_name}")
    admin = _engine("postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
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
    os.environ["DATABASE_URL"] = _application_url().set(database=database_name).render_as_string(
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


def _tables(connection) -> set[str]:
    return set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        ).scalars()
    )


def _verify_foundation(connection) -> None:
    tables = _tables(connection)
    missing = set(FOUNDATION_TABLES) - tables
    if missing:
        raise RuntimeError(f"missing M4.0 tables={sorted(missing)}")
    missing_legacy = set(LEGACY_COEXISTENCE_TABLES) - tables
    if missing_legacy:
        raise RuntimeError(f"legacy payment coexistence tables missing={sorted(missing_legacy)}")
    counts = {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in FOUNDATION_TABLES
    }
    populated = {table: count for table, count in counts.items() if count}
    if populated:
        raise RuntimeError(f"M4.0 tables are not empty={populated}")
    constraints = set(
        connection.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid=c.connamespace "
                "WHERE n.nspname='public'"
            )
        ).scalars()
    )
    missing_constraints = REQUIRED_CONSTRAINTS - constraints
    if missing_constraints:
        raise RuntimeError(f"missing M4.0 constraints={sorted(missing_constraints)}")
    triggers = set(
        connection.execute(
            text(
                "SELECT tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND NOT t.tgisinternal"
            )
        ).scalars()
    )
    missing_triggers = REQUIRED_TRIGGERS - triggers
    if missing_triggers:
        raise RuntimeError(f"missing M4.0 immutable triggers={sorted(missing_triggers)}")


def _verify_development() -> str:
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    validate_release_manifest(ROOT)
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if not revision_preserves_m3_checkpoint(ROOT, revision):
            raise RuntimeError(
                f"expected revision={PARENT_REVISION} or its linear descendant; actual={revision}"
            )
        catalog = connection.execute(
            text("SELECT count(*) FROM financial_event_type_versions")
        ).scalar_one()
        if catalog != 20:
            raise RuntimeError(f"expected canonical catalog=20; actual={catalog}")
        counts = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in FROZEN_EMPTY_TABLES
        }
        populated = {table: count for table, count in counts.items() if count}
        if populated:
            raise RuntimeError(f"development financial tables are not empty={populated}")
        tables = _tables(connection)
        if revision == TARGET_REVISION:
            _verify_foundation(connection)
        elif set(FOUNDATION_TABLES) & tables:
            raise RuntimeError("M4.0 tables exist before the M4.0 revision")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("financial_event_type_versions=20")
    print("m40_payment_foundation_development=PASS")
    return revision


def _status() -> bool:
    exists = _database_exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _create_and_verify() -> None:
    _verify_development()
    _create_database(TEST_DATABASE_NAME)
    disposable = None
    try:
        _migrate(TEST_DATABASE_NAME, "head")
        disposable = _engine(TEST_DATABASE_NAME)
        with disposable.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != TARGET_REVISION:
                raise RuntimeError(f"expected disposable revision={TARGET_REVISION}; actual={revision}")
            _verify_foundation(connection)
        disposable.dispose()
        disposable = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        disposable = _engine(TEST_DATABASE_NAME)
        with disposable.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != PARENT_REVISION:
                raise RuntimeError(f"expected downgrade revision={PARENT_REVISION}; actual={revision}")
            remaining = set(FOUNDATION_TABLES) & _tables(connection)
            if remaining:
                raise RuntimeError(f"M4.0 tables remain after downgrade={sorted(remaining)}")
        disposable.dispose()
        disposable = None
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        disposable = _engine(TEST_DATABASE_NAME)
        with disposable.connect() as connection:
            _verify_foundation(connection)
        disposable.dispose()
        disposable = None
        _drop_database(TEST_DATABASE_NAME)
        _verify_development()
        print(
            "m40_payment_foundation=PASS "
            f"database={TEST_DATABASE_NAME} schema=PASS empty=PASS "
            "legacy_coexistence=PASS provider_neutrality=PASS settlement_link=PASS "
            "upgrade_downgrade_upgrade=PASS dropped=true"
        )
    except Exception:
        if disposable is not None:
            disposable.dispose()
        print(f"M4.0 verification failed; retained disposable database={TEST_DATABASE_NAME}")
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
