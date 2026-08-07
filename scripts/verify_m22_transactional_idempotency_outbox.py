"""Disposable PostgreSQL verification for M2.2 transactional delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
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

from core.domain.finance.event_contract import (  # noqa: E402
    FinancialEventIdempotencyConflict,
    FinancialEventValidationError,
    canonical_json_bytes,
)
from core.domain.finance.transactional_event_engine import (  # noqa: E402
    TransactionalCanonicalFinancialEventEngine,
)
from database import engine as application_engine  # noqa: E402
from scripts.verify_m21_canonical_event_engine import (  # noqa: E402
    SOURCE_OTHER_TENANT,
    _event_command,
    _install_fixtures,
)


TEST_DATABASE_NAME = "xbos_track_b_m22_delivery_test"
EXPECTED_REVISION = "m22_transactional_delivery_004"
PARENT_REVISION = "m20_event_catalog_003"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _base_url():
    url = make_url(application_engine.url)
    if url.host not in LOCAL_HOSTS:
        raise RuntimeError(f"Refusing non-local PostgreSQL host: {url.host!r}")
    return url


def _database_exists(database_name: str) -> bool:
    admin = create_engine(
        _base_url().set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
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
        raise RuntimeError(f"Refusing unexpected test database: {database_name}")
    if _database_exists(database_name):
        raise RuntimeError(f"Test database already exists: {database_name}")
    admin = create_engine(
        _base_url().set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        admin.dispose()


def _drop_database(database_name: str) -> None:
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"Refusing unexpected test database: {database_name}")
    admin = create_engine(
        _base_url().set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
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
def _selected_database(database_name: str):
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


def _config(database_name: str) -> Config:
    with _selected_database(database_name):
        return Config(str(ROOT / "alembic.ini"))


def _upgrade(database_name: str, revision: str = "head") -> None:
    with _selected_database(database_name):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), revision)


def _downgrade(database_name: str, revision: str) -> None:
    with _selected_database(database_name):
        alembic_command.downgrade(Config(str(ROOT / "alembic.ini")), revision)


def _counts(connection) -> tuple[int, int, int]:
    return tuple(
        connection.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
        for table in ("idempotency_records", "financial_events", "outbox_messages")
    )


def _verify_rehearsal(selected_url: str) -> None:
    selected_engine = create_engine(selected_url)
    try:
        _install_fixtures(selected_engine)
        command = _event_command(
            public_id=UUID("10000000-0000-0000-0000-000000000022"),
            idempotency_key="m22:atomic:1",
            metadata={"source": "m22_transactional_verifier"},
            actor_service="m22-verifier",
        )

        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                first = TransactionalCanonicalFinancialEventEngine.emit(
                    session, command
                )
            if first.replayed:
                raise RuntimeError("First command was incorrectly reported as replay")
            if first.idempotency_record.processing_state != "completed":
                raise RuntimeError("Idempotency record did not complete atomically")
            if first.outbox_message.delivery_state != "pending":
                raise RuntimeError("Outbox message was not created pending")

        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                replay = TransactionalCanonicalFinancialEventEngine.emit(
                    session, command
                )
            if not replay.replayed:
                raise RuntimeError("Identical command was not reported as replay")
            if replay.event.public_id != first.event.public_id:
                raise RuntimeError("Replay changed the financial event public ID")
            if replay.outbox_message.public_id != first.outbox_message.public_id:
                raise RuntimeError("Replay changed the outbox message public ID")

        with Session(selected_engine) as session:
            try:
                with session.begin():
                    TransactionalCanonicalFinancialEventEngine.emit(
                        session, replace(command, amount=Decimal("1001"))
                    )
            except FinancialEventIdempotencyConflict as exc:
                if exc.code != "idempotency_conflict":
                    raise
            else:
                raise RuntimeError("Altered command reused an idempotency identity")

        rollback_command = replace(
            command,
            public_id=UUID("10000000-0000-0000-0000-000000000023"),
            idempotency_key="m22:rollback:1",
        )
        with Session(selected_engine) as session:
            transaction = session.begin()
            TransactionalCanonicalFinancialEventEngine.emit(session, rollback_command)
            transaction.rollback()

        cross_tenant = replace(
            command,
            public_id=UUID("10000000-0000-0000-0000-000000000024"),
            idempotency_key="m22:cross-tenant:1",
            source_record_id=SOURCE_OTHER_TENANT,
        )
        with Session(selected_engine) as session:
            try:
                with session.begin():
                    TransactionalCanonicalFinancialEventEngine.emit(
                        session, cross_tenant
                    )
            except FinancialEventValidationError as exc:
                if exc.code != "source_record_not_found":
                    raise
            else:
                raise RuntimeError("Cross-tenant source reference was accepted")

        with selected_engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            if revision != EXPECTED_REVISION:
                raise RuntimeError(f"Unexpected revision: {revision}")
            if _counts(connection) != (1, 1, 1):
                raise RuntimeError(
                    "Expected one committed idempotency record, event, and outbox message"
                )
            if connection.execute(
                text(
                    """
                    SELECT count(*) FROM public.idempotency_records
                    WHERE idempotency_key IN ('m22:rollback:1', 'm22:cross-tenant:1')
                    """
                )
            ).scalar_one() != 0:
                raise RuntimeError("Failed command left an idempotency reservation")
            row = connection.execute(
                text(
                    """
                    SELECT payload, payload_hash, topic, message_key,
                           organization_unit_id
                    FROM public.outbox_messages
                    """
                )
            ).mappings().one()
            required = {
                "message_id", "tenant_id", "organization_unit_id", "topic",
                "event_type", "event_version", "message_key", "correlation_id",
                "causation_id", "occurred_at", "recorded_at", "payload",
            }
            if set(row["payload"]) != required:
                raise RuntimeError("Outbox envelope fields differ from the contract")
            expected_hash = hashlib.sha256(
                canonical_json_bytes(row["payload"])
            ).hexdigest()
            if row["payload_hash"] != expected_hash:
                raise RuntimeError("Outbox payload hash differs from canonical envelope")
            if row["topic"] != row["payload"]["topic"]:
                raise RuntimeError("Outbox topic column and envelope differ")
            if row["message_key"] != row["payload"]["message_key"]:
                raise RuntimeError("Outbox message key column and envelope differ")

        connection = selected_engine.connect()
        transaction = connection.begin()
        try:
            try:
                connection.execute(
                    text(
                        """
                        UPDATE public.outbox_messages
                        SET payload = jsonb_set(payload, '{tampered}', 'true'::jsonb)
                        """
                    )
                )
            except DBAPIError:
                transaction.rollback()
            else:
                transaction.rollback()
                raise RuntimeError("Immutable outbox content accepted an update")
        finally:
            connection.close()

        with selected_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE public.outbox_messages
                    SET delivery_state = 'retrying', delivery_attempts = 1,
                        last_error = 'm22-verifier-retry'
                    """
                )
            )
        with selected_engine.connect() as connection:
            if connection.execute(
                text("SELECT delivery_state FROM public.outbox_messages")
            ).scalar_one() != "retrying":
                raise RuntimeError("Outbox delivery state could not advance")
    finally:
        selected_engine.dispose()


def _create_and_verify() -> None:
    _create_database(TEST_DATABASE_NAME)
    retained = True
    try:
        _upgrade(TEST_DATABASE_NAME)
        _downgrade(TEST_DATABASE_NAME, PARENT_REVISION)
        _upgrade(TEST_DATABASE_NAME)
        selected_url = _base_url().set(database=TEST_DATABASE_NAME).render_as_string(
            hide_password=False
        )
        _verify_rehearsal(selected_url)
        _drop_database(TEST_DATABASE_NAME)
        retained = False
        print(
            f"m22_transactional_delivery=PASS database={TEST_DATABASE_NAME} "
            "atomic=PASS replay=PASS conflict=PASS rollback=PASS "
            "tenant_isolation=PASS outbox_immutability=PASS "
            "upgrade_downgrade_upgrade=PASS dropped=true"
        )
    finally:
        if retained:
            print(
                "M2.2 verification failed; retained disposable database="
                f"{TEST_DATABASE_NAME}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("create-and-verify")
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
    elif args.command_name == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("Exact disposable database confirmation is required")
        _drop_database(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
