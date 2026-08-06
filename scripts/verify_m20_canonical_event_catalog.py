"""Verify and rehearse the M2.0 canonical event-catalog seed migration."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.persistence.m20_event_catalog import (  # noqa: E402
    EXPECTED_CATALOG_SEMANTIC_SHA256,
    EXPECTED_EVENT_COUNT,
    RECONCILIATION_EFFECTS,
    build_seed_rows,
)
from database import engine as application_engine  # noqa: E402


TEST_DATABASE_NAME = "xbos_track_b_m20_catalog_test"
SOURCE_REVISION = "m13_financial_foundation_002"
TARGET_REVISION = "m20_event_catalog_003"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _base_url():
    # Keep the real configured password; URL.__str__ intentionally masks it.
    url = make_url(application_engine.url)
    if url.host not in LOCAL_HOSTS:
        raise RuntimeError(f"Refusing non-local PostgreSQL host: {url.host!r}")
    return url


def _database_exists(database_name: str) -> bool:
    admin_url = _base_url().set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": database_name},
                ).scalar()
            )
    finally:
        admin.dispose()


def _create_database(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"Refusing unexpected rehearsal database: {database_name}")
    if _database_exists(database_name):
        raise RuntimeError(f"Rehearsal database already exists: {database_name}")
    admin = create_engine(_base_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin.dispose()


def _drop_database(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"Refusing unexpected rehearsal database: {database_name}")
    admin = create_engine(_base_url().set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :name AND pid <> pg_backend_pid()
                    """
                ),
                {"name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        admin.dispose()


@contextmanager
def _database_url(database_name: str):
    previous = os.environ.get("DATABASE_URL")
    selected = _base_url().set(database=database_name).render_as_string(
        hide_password=False
    )
    os.environ["DATABASE_URL"] = selected
    try:
        yield selected
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _alembic_config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _current_revision(connection) -> str | None:
    return connection.execute(
        text("SELECT version_num FROM public.alembic_version")
    ).scalar_one_or_none()


def _constraint_definition(connection) -> str:
    return connection.execute(
        text(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'public.financial_event_type_versions'::regclass
              AND conname = 'ck_financial_event_type_versions_recon_effect'
            """
        )
    ).scalar_one()


def _verify_seeded_database(database_url: str) -> None:
    expected_rows = {
        (row["event_type_code"], row["event_version"]): row
        for row in build_seed_rows()
    }
    selected_engine = create_engine(database_url)
    try:
        with selected_engine.connect() as connection:
            revision = _current_revision(connection)
            if revision != TARGET_REVISION:
                raise RuntimeError(
                    f"Expected revision {TARGET_REVISION}; found {revision}"
                )

            actual_rows = connection.execute(
                text(
                    """
                    SELECT event_type_code, event_version, display_name, definition,
                           amount_policy, default_economic_role,
                           reconciliation_effect, account_role_policy,
                           posting_eligible, definition_hash, metadata
                    FROM public.financial_event_type_versions
                    ORDER BY event_type_code, event_version
                    """
                )
            ).mappings().all()

            if len(actual_rows) != EXPECTED_EVENT_COUNT:
                raise RuntimeError(
                    f"Expected {EXPECTED_EVENT_COUNT} seed rows; found {len(actual_rows)}"
                )

            for actual in actual_rows:
                identity = (actual["event_type_code"], actual["event_version"])
                expected = expected_rows.get(identity)
                if expected is None:
                    raise RuntimeError(f"Unexpected catalog identity: {identity}")
                for field in (
                    "display_name",
                    "definition",
                    "amount_policy",
                    "default_economic_role",
                    "reconciliation_effect",
                    "account_role_policy",
                    "posting_eligible",
                    "definition_hash",
                    "metadata",
                ):
                    if actual[field] != expected[field]:
                        raise RuntimeError(
                            f"Catalog mismatch for {identity} field={field}"
                        )

            if connection.execute(
                text("SELECT count(*) FROM public.financial_events")
            ).scalar_one() != 0:
                raise RuntimeError("M2.0 must not create financial events")
            if connection.execute(
                text("SELECT count(*) FROM public.outbox_messages")
            ).scalar_one() != 0:
                raise RuntimeError("M2.0 must not create outbox messages")

            constraint = _constraint_definition(connection)
            for effect in RECONCILIATION_EFFECTS:
                if effect not in constraint:
                    raise RuntimeError(
                        f"Reconciliation constraint omits {effect!r}"
                    )

        # Prove immutability in a transaction that is always rolled back.
        connection = selected_engine.connect()
        transaction = connection.begin()
        try:
            try:
                connection.execute(
                    text(
                        """
                        UPDATE public.financial_event_type_versions
                        SET display_name = display_name || ' altered'
                        WHERE event_type_code = 'PAYMENT_SETTLED'
                          AND event_version = 1
                        """
                    )
                )
            except DBAPIError:
                transaction.rollback()
            else:
                transaction.rollback()
                raise RuntimeError("Immutable catalog row accepted an update")
        finally:
            connection.close()
    finally:
        selected_engine.dispose()


def _verify_downgraded_database(database_url: str) -> None:
    selected_engine = create_engine(database_url)
    try:
        with selected_engine.connect() as connection:
            revision = _current_revision(connection)
            if revision != SOURCE_REVISION:
                raise RuntimeError(
                    f"Expected downgraded revision {SOURCE_REVISION}; found {revision}"
                )
            count = connection.execute(
                text("SELECT count(*) FROM public.financial_event_type_versions")
            ).scalar_one()
            if count != 0:
                raise RuntimeError(f"Catalog downgrade retained {count} rows")
    finally:
        selected_engine.dispose()


def _create_and_verify() -> None:
    _create_database(TEST_DATABASE_NAME)
    retained = True
    try:
        with _database_url(TEST_DATABASE_NAME) as selected_url:
            config = _alembic_config()
            command.upgrade(config, "head")
            _verify_seeded_database(selected_url)
            command.downgrade(config, SOURCE_REVISION)
            _verify_downgraded_database(selected_url)
            command.upgrade(config, "head")
            _verify_seeded_database(selected_url)
        _drop_database(TEST_DATABASE_NAME)
        retained = False
        print(
            f"m20_catalog_rehearsal=PASS database={TEST_DATABASE_NAME} "
            "upgrade_downgrade_upgrade=PASS dropped=true"
        )
    finally:
        if retained:
            print(
                "M2.0 rehearsal failed; the disposable database was retained "
                f"for inspection: {TEST_DATABASE_NAME}"
            )


def _verify_current() -> None:
    url = _base_url()
    _verify_seeded_database(url.render_as_string(hide_password=False))
    print(f"database={url.database}")
    print(f"revision={TARGET_REVISION}")
    print(f"catalog_rows={EXPECTED_EVENT_COUNT}")
    print(f"catalog_semantic_sha256={EXPECTED_CATALOG_SEMANTIC_SHA256}")
    print("financial_events=0")
    print("outbox_messages=0")
    print("m20_canonical_event_catalog=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("create-and-verify")
    subparsers.add_parser("verify")
    drop_parser = subparsers.add_parser("drop")
    drop_parser.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()

    if args.command_name == "status":
        print(
            f"database={TEST_DATABASE_NAME} "
            f"exists={str(_database_exists(TEST_DATABASE_NAME)).lower()}"
        )
    elif args.command_name == "create-and-verify":
        _create_and_verify()
    elif args.command_name == "verify":
        _verify_current()
    elif args.command_name == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("Exact rehearsal database confirmation is required")
        _drop_database(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
