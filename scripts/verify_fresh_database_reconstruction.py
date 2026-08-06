"""Create, verify, inspect, or explicitly drop the M1.2 disposable DB."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "contracts" / "persistence" / "v1" / "reconstruction_baseline.json"
)
SQL_PATH = ROOT / "alembic_reconstruction" / "sql" / "source_state_baseline.sql"
CONFIG_PATH = ROOT / "alembic_reconstruction.ini"

sys.path.insert(0, str(ROOT))

from core.persistence.database_config import resolve_database_url
from core.persistence.reconstruction_policy import (
    RECONSTRUCTION_DATABASE_NAME,
    RECONSTRUCTION_REVISION,
    validate_reconstruction_url,
)


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _urls():
    configured = make_url(resolve_database_url())
    test_url = validate_reconstruction_url(
        configured.set(database=RECONSTRUCTION_DATABASE_NAME)
    )
    admin_url = configured.set(database="postgres")
    return admin_url, test_url


def _database_exists(admin_url) -> bool:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": RECONSTRUCTION_DATABASE_NAME},
                ).scalar()
            )
    finally:
        engine.dispose()


def _create_database(admin_url) -> None:
    if _database_exists(admin_url):
        raise RuntimeError(
            f"Refusing to overwrite existing database {RECONSTRUCTION_DATABASE_NAME!r}"
        )

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{RECONSTRUCTION_DATABASE_NAME}" '
                "TEMPLATE template0 ENCODING 'UTF8'"
            )
    finally:
        engine.dispose()


def _upgrade(test_url) -> None:
    rendered = test_url.render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = rendered

    try:
        config = Config(str(CONFIG_PATH))
        config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _sql_object_names():
    sql = SQL_PATH.read_text(encoding="utf-8")
    sequences = set(
        re.findall(r"^CREATE SEQUENCE public\.([^\s]+)", sql, re.MULTILINE)
    )
    indexes = set(
        re.findall(
            r"^CREATE (?:UNIQUE )?INDEX ([^\s]+)", sql, re.MULTILINE
        )
    )
    constraints = set(
        re.findall(r"^\s+ADD CONSTRAINT ([^\s]+)", sql, re.MULTILINE)
    ) | set(re.findall(r"^\s+CONSTRAINT ([^\s]+)", sql, re.MULTILINE))
    return sequences, indexes, constraints


def _verify(test_url) -> None:
    contract = _contract()
    expected_tables = set(contract["expected_public_tables"])
    expected_sequences, expected_indexes, expected_constraints = _sql_object_names()

    engine = create_engine(test_url)
    try:
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names(schema="public"))
        actual_sequences = set(inspector.get_sequence_names(schema="public"))

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            extension_exists = bool(
                connection.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'")
                ).scalar()
            )
            function_exists = bool(
                connection.execute(
                    text(
                        "SELECT 1 FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname = 'public' "
                        "AND p.proname = 'xbos_taxonomy_tree'"
                    )
                ).scalar()
            )
            actual_indexes = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public'"
                    )
                )
            }
            actual_constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_namespace n ON n.oid = c.connamespace "
                        "WHERE n.nspname = 'public'"
                    )
                )
            }

        failures = []
        if revision != RECONSTRUCTION_REVISION:
            failures.append(f"revision={revision!r}")
        if actual_tables != expected_tables:
            failures.append(
                f"table drift missing={sorted(expected_tables - actual_tables)} "
                f"extra={sorted(actual_tables - expected_tables)}"
            )
        if not expected_sequences <= actual_sequences:
            failures.append(
                f"missing sequences={sorted(expected_sequences - actual_sequences)}"
            )
        if not expected_indexes <= actual_indexes:
            failures.append(
                f"missing indexes={sorted(expected_indexes - actual_indexes)}"
            )
        if not expected_constraints <= actual_constraints:
            failures.append(
                "missing constraints="
                f"{sorted(expected_constraints - actual_constraints)}"
            )
        if not extension_exists:
            failures.append("pgcrypto extension missing")
        if not function_exists:
            failures.append("xbos_taxonomy_tree function missing")

        if failures:
            raise RuntimeError("; ".join(failures))

        print("M1.2 clean-room reconstruction: PASS")
        print(f"database={RECONSTRUCTION_DATABASE_NAME}")
        print(f"revision={revision}")
        print(f"tables={len(actual_tables)}")
        print(f"sequences={len(expected_sequences)}")
        print(f"explicit_indexes={len(expected_indexes)}")
        print(f"constraints={len(expected_constraints)}")
        print("extension=pgcrypto")
        print("function=xbos_taxonomy_tree")
    finally:
        engine.dispose()


def _drop_database(admin_url, confirmation: str | None) -> None:
    if confirmation != RECONSTRUCTION_DATABASE_NAME:
        raise RuntimeError(
            "Drop requires --confirm-database-name "
            f"{RECONSTRUCTION_DATABASE_NAME}"
        )

    if not _database_exists(admin_url):
        print(f"database={RECONSTRUCTION_DATABASE_NAME} exists=false")
        return

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE "{RECONSTRUCTION_DATABASE_NAME}" WITH (FORCE)'
            )
    finally:
        engine.dispose()

    print(f"dropped={RECONSTRUCTION_DATABASE_NAME}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("status", "create-and-verify", "verify-existing", "drop"),
    )
    parser.add_argument("--confirm-database-name")
    args = parser.parse_args()

    admin_url, test_url = _urls()

    if args.action == "status":
        print(
            f"database={RECONSTRUCTION_DATABASE_NAME} "
            f"exists={str(_database_exists(admin_url)).lower()}"
        )
    elif args.action == "create-and-verify":
        _create_database(admin_url)
        try:
            _upgrade(test_url)
            _verify(test_url)
        except Exception:
            print(
                "Reconstruction failed; the disposable database was retained "
                "for inspection and was not dropped automatically.",
                file=sys.stderr,
            )
            raise
    elif args.action == "verify-existing":
        if not _database_exists(admin_url):
            raise RuntimeError(
                f"Database {RECONSTRUCTION_DATABASE_NAME!r} does not exist"
            )
        _verify(test_url)
    else:
        _drop_database(admin_url, args.confirm_database_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
