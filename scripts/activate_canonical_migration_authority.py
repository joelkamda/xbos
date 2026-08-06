"""Activate and adopt the M1.4 canonical Alembic authority.

The database-changing commands are restricted to the exact local Track B
development database. Configuration activation changes only two reviewed
values in alembic.ini and is recoverable through Git.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.persistence.m14_authority import (
    ACTIVATION_DATABASE,
    ACTIVE_SCRIPT_LOCATION,
    CANONICAL_HEAD_REVISION,
    FOUNDATION_TABLES,
    INACTIVE_SCRIPT_LOCATION,
    SAFE_INI_URL,
    SOURCE_AUTHORITY_REVISION,
    SOURCE_STATE_REVISION,
    assert_exact_source_schema,
    checked_activation_url,
    source_tables_from_baseline,
)


ALEMBIC_INI = ROOT / "alembic.ini"
SOURCE_BASELINE = (
    ROOT / "alembic_reconstruction" / "sql" / "source_state_baseline.sql"
)


def _database_url():
    from database import DATABASE_URL

    return checked_activation_url(DATABASE_URL)


def _engine():
    return create_engine(_database_url(), poolclass=NullPool)


def _config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option(
        "sqlalchemy.url",
        _database_url().render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def _with_database_url():
    class DatabaseUrlContext:
        def __enter__(self):
            self.previous = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = _database_url().render_as_string(
                hide_password=False
            )

        def __exit__(self, exc_type, exc, traceback):
            if self.previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = self.previous

    return DatabaseUrlContext()


def _ini_value(name: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(ALEMBIC_INI.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Missing {name!r} in {ALEMBIC_INI}")
    return match.group(1)


def _config_is_active() -> bool:
    return (
        _ini_value("script_location") == ACTIVE_SCRIPT_LOCATION
        and _ini_value("sqlalchemy.url") == SAFE_INI_URL
    )


def _activate_config() -> None:
    source = ALEMBIC_INI.read_text(encoding="utf-8")
    current_location = _ini_value("script_location")
    if current_location not in {INACTIVE_SCRIPT_LOCATION, ACTIVE_SCRIPT_LOCATION}:
        raise RuntimeError(f"Unexpected Alembic script location: {current_location!r}")

    next_source, location_count = re.subn(
        r"^\s*script_location\s*=.*$",
        f"script_location = {ACTIVE_SCRIPT_LOCATION}",
        source,
        count=1,
        flags=re.MULTILINE,
    )
    next_source, url_count = re.subn(
        r"^\s*sqlalchemy\.url\s*=.*$",
        f"sqlalchemy.url = {SAFE_INI_URL}",
        next_source,
        count=1,
        flags=re.MULTILINE,
    )
    if location_count != 1 or url_count != 1:
        raise RuntimeError("Refusing ambiguous alembic.ini edit")
    ALEMBIC_INI.write_text(next_source, encoding="utf-8")
    if not _config_is_active():
        raise RuntimeError("Alembic authority configuration activation failed")


def _current_revision(connection) -> str:
    return str(
        connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one()
    )


def _table_set(connection) -> set[str]:
    return set(inspect(connection).get_table_names(schema="public"))


def _foundation_counts(connection) -> dict[str, int]:
    tables = _table_set(connection)
    return {
        name: int(
            connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one()
        )
        for name in sorted(FOUNDATION_TABLES & tables)
    }


def _preflight() -> str:
    expected_source = source_tables_from_baseline(SOURCE_BASELINE)
    engine = _engine()
    try:
        with engine.connect() as connection:
            revision = _current_revision(connection)
            tables = _table_set(connection)
            foundation_present = FOUNDATION_TABLES & tables

            if revision == CANONICAL_HEAD_REVISION:
                missing = FOUNDATION_TABLES - tables
                if missing:
                    raise RuntimeError(
                        f"Canonical head is missing foundation tables: {sorted(missing)}"
                    )
                counts = _foundation_counts(connection)
                nonempty = {name: count for name, count in counts.items() if count}
                if nonempty:
                    return f"adopted_in_use nonempty={nonempty}"
                return "adopted_empty"

            if revision != SOURCE_AUTHORITY_REVISION:
                raise RuntimeError(f"Unexpected database revision: {revision!r}")
            if foundation_present:
                raise RuntimeError(
                    "Source revision already contains canonical foundation tables: "
                    f"{sorted(foundation_present)}"
                )
            assert_exact_source_schema(tables, expected_source)
            return "ready_for_adoption"
    finally:
        engine.dispose()


def _verify_adopted_empty() -> None:
    expected_source = source_tables_from_baseline(SOURCE_BASELINE)
    engine = _engine()
    try:
        with engine.connect() as connection:
            revision = _current_revision(connection)
            if revision != CANONICAL_HEAD_REVISION:
                raise RuntimeError(f"Expected canonical head, found {revision!r}")
            tables = _table_set(connection)
            expected = set(expected_source) | set(FOUNDATION_TABLES)
            if tables != expected:
                raise RuntimeError(
                    "Post-adoption table mismatch: "
                    f"missing={sorted(expected - tables)} "
                    f"unexpected={sorted(tables - expected)}"
                )
            nonempty = {
                name: count
                for name, count in _foundation_counts(connection).items()
                if count
            }
            if nonempty:
                raise RuntimeError(f"M1.4 foundation must remain empty: {nonempty}")
    finally:
        engine.dispose()


def _adopt(args) -> None:
    if args.confirm_database_name != ACTIVATION_DATABASE:
        raise RuntimeError("Exact activation database confirmation is required")
    if args.confirm_source_revision != SOURCE_AUTHORITY_REVISION:
        raise RuntimeError("Exact source revision confirmation is required")
    if not _config_is_active():
        raise RuntimeError("Activate alembic.ini before database adoption")
    state = _preflight()
    if state == "adopted_empty":
        print("canonical_authority_adoption=ALREADY_COMPLETE")
        return
    if state != "ready_for_adoption":
        raise RuntimeError(f"Database is not adoptable: {state}")

    try:
        with _with_database_url():
            command.stamp(_config(), SOURCE_STATE_REVISION, purge=True)
            command.upgrade(_config(), CANONICAL_HEAD_REVISION)
        _verify_adopted_empty()
    except Exception:
        print(
            "Adoption stopped. Source data was not transformed or deleted. "
            "Inspect the raw alembic_version and run preflight before recovery."
        )
        raise
    print("canonical_authority_adoption=PASS")


def _rollback(args) -> None:
    if args.confirm_database_name != ACTIVATION_DATABASE:
        raise RuntimeError("Exact activation database confirmation is required")
    if args.confirm_empty_foundation_rollback != "EMPTY-M14-FOUNDATION":
        raise RuntimeError("Exact empty-foundation rollback confirmation is required")
    if not _config_is_active():
        raise RuntimeError("Canonical Alembic configuration is not active")
    if _preflight() != "adopted_empty":
        raise RuntimeError("Rollback is allowed only while every M1 foundation table is empty")

    with _with_database_url():
        command.downgrade(_config(), SOURCE_STATE_REVISION)
    engine = _engine()
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM public.alembic_version"))
            connection.execute(
                text(
                    "INSERT INTO public.alembic_version(version_num) "
                    "VALUES (:revision)"
                ),
                {"revision": SOURCE_AUTHORITY_REVISION},
            )
    finally:
        engine.dispose()
    if _preflight() != "ready_for_adoption":
        raise RuntimeError("Source authority restoration verification failed")
    print("canonical_authority_empty_rollback=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("config-status")
    commands.add_parser("activate-config")
    commands.add_parser("preflight")

    adopt = commands.add_parser("adopt")
    adopt.add_argument("--confirm-database-name", required=True)
    adopt.add_argument("--confirm-source-revision", required=True)

    rollback = commands.add_parser("rollback-empty")
    rollback.add_argument("--confirm-database-name", required=True)
    rollback.add_argument("--confirm-empty-foundation-rollback", required=True)
    args = parser.parse_args()

    if args.command == "config-status":
        print(f"script_location={_ini_value('script_location')}")
        print(f"sqlalchemy.url={_ini_value('sqlalchemy.url')}")
        print(f"canonical_config_active={str(_config_is_active()).lower()}")
        return 0
    if args.command == "activate-config":
        _activate_config()
        print("canonical_alembic_configuration=ACTIVE")
        return 0
    if args.command == "preflight":
        url = _database_url()
        print(f"host={url.host}")
        print(f"database={url.database}")
        print(f"authority_state={_preflight()}")
        return 0
    if args.command == "adopt":
        _adopt(args)
        return 0
    _rollback(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
