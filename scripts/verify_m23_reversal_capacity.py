"""Disposable PostgreSQL verification for M2.3 correction capacity."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    FinancialEventValidationError,
)
from core.domain.finance.transactional_event_engine import (  # noqa: E402
    TransactionalCanonicalFinancialEventEngine,
)
from database import engine as application_engine  # noqa: E402
from scripts.verify_m21_canonical_event_engine import (  # noqa: E402
    ACCOUNT_CASH,
    ORG_ONE,
    SOURCE_SETTLEMENT,
    TENANT_ONE,
    _event_command,
    _install_fixtures,
)


TEST_DATABASE_NAME = "xbos_track_b_m23_reversal_test"
EXPECTED_REVISION = "m23_reversal_capacity_005"
PARENT_REVISION = "m22_transactional_delivery_004"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SOURCE_SETTLEMENT_TWO = 931000
SOURCE_REVERSAL_ONE = 931001
SOURCE_REVERSAL_TWO = 931002
SOURCE_REVERSAL_OVER = 931003
SOURCE_ALLOCATION_REVERSAL = 931004
SOURCE_GENERIC_REVERSAL = 931005
SOURCE_CONCURRENT_ONE = 931006
SOURCE_CONCURRENT_TWO = 931007


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


def _upgrade(database_name: str, revision: str = "head") -> None:
    with _selected_database(database_name):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), revision)


def _downgrade(database_name: str, revision: str) -> None:
    with _selected_database(database_name):
        alembic_command.downgrade(Config(str(ROOT / "alembic.ini")), revision)


def _install_reversal_sources(selected_engine) -> None:
    rows = [
        (SOURCE_SETTLEMENT_TWO, "payment_settlement", "settlement-2"),
        (SOURCE_REVERSAL_ONE, "payment_settlement_reversal", "reverse-1"),
        (SOURCE_REVERSAL_TWO, "payment_settlement_reversal", "reverse-2"),
        (SOURCE_REVERSAL_OVER, "payment_settlement_reversal", "reverse-over"),
        (SOURCE_ALLOCATION_REVERSAL, "payment_allocation_reversal", "allocation-reverse"),
        (SOURCE_GENERIC_REVERSAL, "financial_event_reversal", "generic-reverse"),
        (SOURCE_CONCURRENT_ONE, "payment_settlement_reversal", "concurrent-1"),
        (SOURCE_CONCURRENT_TWO, "payment_settlement_reversal", "concurrent-2"),
    ]
    with selected_engine.begin() as connection:
        for source_id, aggregate_type, external_id in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO public.kernel_source_records (
                        id, tenant_id, organization_unit_id, source_component,
                        aggregate_type, aggregate_external_id,
                        source_occurred_at, metadata
                    ) VALUES (
                        :id, :tenant_id, :organization_unit_id, 'm23_verifier',
                        :aggregate_type, :external_id, now(), '{}'::jsonb
                    )
                    """
                ),
                {
                    "id": source_id,
                    "tenant_id": TENANT_ONE,
                    "organization_unit_id": ORG_ONE,
                    "aggregate_type": aggregate_type,
                    "external_id": external_id,
                },
            )


def _settlement_command(*, public_id: str, key: str, source_record_id: int):
    return _event_command(
        public_id=UUID(public_id),
        event_type_code="PAYMENT_SETTLED",
        amount=Decimal("1000"),
        economic_role="settlement_in",
        source_record_id=source_record_id,
        target_operational_account_id=ACCOUNT_CASH,
        idempotency_key=key,
        classification_snapshot={
            "settlement_purpose": {"code": "m23_capacity_fixture"}
        },
        posting_context={"profile": "inbound_settlement"},
        metadata={"source": "m23_reversal_verifier"},
        actor_service="m23-verifier",
    )


def _reversal_command(
    original_id: int,
    *,
    public_id: str,
    key: str,
    source_record_id: int,
    amount: str,
    event_type_code: str = "PAYMENT_SETTLEMENT_REVERSED",
):
    aggregate_role = (
        "payment_allocation_reversal"
        if event_type_code == "PAYMENT_ALLOCATION_REVERSED"
        else "financial_event_reversal"
        if event_type_code == "FINANCIAL_FACT_REVERSED"
        else "payment_settlement_reversal"
    )
    economic_role = (
        "deallocation"
        if event_type_code == "PAYMENT_ALLOCATION_REVERSED"
        else "correction"
    )
    return _event_command(
        public_id=UUID(public_id),
        event_type_code=event_type_code,
        amount=Decimal(amount),
        economic_role=economic_role,
        source_record_id=source_record_id,
        original_event_id=original_id,
        source_operational_account_id=(
            ACCOUNT_CASH
            if event_type_code in {
                "PAYMENT_SETTLEMENT_REVERSED", "FINANCIAL_FACT_REVERSED"
            }
            else None
        ),
        target_operational_account_id=None,
        idempotency_key=key,
        classification_snapshot={"reversal_reason": {"code": aggregate_role}},
        posting_context={"profile": "inverse_original"},
        metadata={"source": "m23_reversal_verifier"},
        actor_service="m23-verifier",
    )


def _expect_validation(code: str, selected_engine, command) -> None:
    with Session(selected_engine) as session:
        try:
            with session.begin():
                TransactionalCanonicalFinancialEventEngine.emit(session, command)
        except FinancialEventValidationError as exc:
            if exc.code != code:
                raise RuntimeError(
                    f"Expected validation {code}; received {exc.code}"
                ) from exc
        else:
            raise RuntimeError(f"Expected validation failure {code}")


def _concurrent_capacity(selected_engine, original_id: int) -> None:
    first_holds_lock = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    first_command = _reversal_command(
        original_id,
        public_id="10000000-0000-0000-0000-000000000236",
        key="m23:concurrent:700",
        source_record_id=SOURCE_CONCURRENT_ONE,
        amount="700",
    )
    second_command = _reversal_command(
        original_id,
        public_id="10000000-0000-0000-0000-000000000237",
        key="m23:concurrent:400",
        source_record_id=SOURCE_CONCURRENT_TWO,
        amount="400",
    )

    def first_worker():
        with Session(selected_engine) as session:
            with session.begin():
                TransactionalCanonicalFinancialEventEngine.emit(session, first_command)
                first_holds_lock.set()
                if not release_first.wait(timeout=10):
                    raise RuntimeError("Timed out waiting to release first reversal")
        return "committed"

    def second_worker():
        if not first_holds_lock.wait(timeout=10):
            raise RuntimeError("First reversal never acquired original-event lock")
        second_started.set()
        with Session(selected_engine) as session:
            try:
                with session.begin():
                    TransactionalCanonicalFinancialEventEngine.emit(
                        session, second_command
                    )
            except FinancialEventValidationError as exc:
                return exc.code
        return "unexpected_success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_worker)
        if not first_holds_lock.wait(timeout=10):
            raise RuntimeError("First reversal did not acquire lock")
        second_future = executor.submit(second_worker)
        if not second_started.wait(timeout=10):
            raise RuntimeError("Second reversal did not start")
        time.sleep(0.2)
        release_first.set()
        if first_future.result(timeout=10) != "committed":
            raise RuntimeError("First concurrent reversal did not commit")
        if second_future.result(timeout=10) != "reversal_capacity_exceeded":
            raise RuntimeError("Concurrent over-reversal was not rejected")


def _verify(selected_url: str) -> None:
    selected_engine = create_engine(selected_url)
    try:
        _install_fixtures(selected_engine)
        _install_reversal_sources(selected_engine)

        first_original = _settlement_command(
            public_id="10000000-0000-0000-0000-000000000230",
            key="m23:original:1",
            source_record_id=SOURCE_SETTLEMENT,
        )
        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                original_one = TransactionalCanonicalFinancialEventEngine.emit(
                    session, first_original
                ).event

        reverse_400 = _reversal_command(
            original_one.id,
            public_id="10000000-0000-0000-0000-000000000231",
            key="m23:reverse:400",
            source_record_id=SOURCE_REVERSAL_ONE,
            amount="400",
        )
        reverse_600 = _reversal_command(
            original_one.id,
            public_id="10000000-0000-0000-0000-000000000232",
            key="m23:reverse:600",
            source_record_id=SOURCE_REVERSAL_TWO,
            amount="600",
        )
        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                first_correction = TransactionalCanonicalFinancialEventEngine.emit(
                    session, reverse_400
                )
                replay = TransactionalCanonicalFinancialEventEngine.emit(
                    session, reverse_400
                )
                if not replay.replayed or replay.event.id != first_correction.event.id:
                    raise RuntimeError("Correction replay changed authoritative identity")
        with Session(selected_engine) as session:
            with session.begin():
                TransactionalCanonicalFinancialEventEngine.emit(session, reverse_600)

        over_capacity = _reversal_command(
            original_one.id,
            public_id="10000000-0000-0000-0000-000000000233",
            key="m23:reverse:over",
            source_record_id=SOURCE_REVERSAL_OVER,
            amount="1",
        )
        _expect_validation("reversal_capacity_exceeded", selected_engine, over_capacity)

        mismatch = _reversal_command(
            original_one.id,
            public_id="10000000-0000-0000-0000-000000000234",
            key="m23:type:mismatch",
            source_record_id=SOURCE_ALLOCATION_REVERSAL,
            amount="1",
            event_type_code="PAYMENT_ALLOCATION_REVERSED",
        )
        _expect_validation("reversal_type_mismatch", selected_engine, mismatch)

        chained = _reversal_command(
            first_correction.event.id,
            public_id="10000000-0000-0000-0000-000000000235",
            key="m23:correction:chain",
            source_record_id=SOURCE_GENERIC_REVERSAL,
            amount="1",
            event_type_code="FINANCIAL_FACT_REVERSED",
        )
        _expect_validation("original_event_is_correction", selected_engine, chained)

        second_original = _settlement_command(
            public_id="10000000-0000-0000-0000-000000000238",
            key="m23:original:2",
            source_record_id=SOURCE_SETTLEMENT_TWO,
        )
        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                original_two = TransactionalCanonicalFinancialEventEngine.emit(
                    session, second_original
                ).event
        _concurrent_capacity(selected_engine, original_two.id)

        connection = selected_engine.connect()
        transaction = connection.begin()
        try:
            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO public.financial_events (
                            public_id, tenant_id, organization_unit_id,
                            event_type_code, event_version, amount, currency_code,
                            economic_role, source_operational_account_id,
                            target_operational_account_id, source_record_id,
                            original_event_id, occurred_at, business_date,
                            calendar_policy_version, actor_service,
                            idempotency_scope, idempotency_key, correlation_id,
                            classification_snapshot, posting_context, metadata
                        )
                        SELECT gen_random_uuid(), tenant_id, organization_unit_id,
                               event_type_code, event_version, 1, currency_code,
                               economic_role, source_operational_account_id,
                               target_operational_account_id, source_record_id,
                               original_event_id, occurred_at, business_date,
                               calendar_policy_version, actor_service,
                               idempotency_scope, 'm23:direct-bypass', correlation_id,
                               classification_snapshot, posting_context, metadata
                        FROM public.financial_events
                        WHERE idempotency_key = 'm23:reverse:400'
                        """
                    )
                )
            except DBAPIError:
                transaction.rollback()
            else:
                transaction.rollback()
                raise RuntimeError("Database trigger accepted direct over-reversal")
        finally:
            connection.close()

        with selected_engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            if revision != EXPECTED_REVISION:
                raise RuntimeError(f"Unexpected revision: {revision}")
            counts = tuple(
                connection.execute(
                    text(f"SELECT count(*) FROM public.{table}")
                ).scalar_one()
                for table in (
                    "idempotency_records", "financial_events", "outbox_messages"
                )
            )
            if counts != (5, 5, 5):
                raise RuntimeError(f"Expected atomic counts (5,5,5); found {counts}")
            first_total = connection.execute(
                text(
                    """
                    SELECT COALESCE(sum(amount), 0) FROM public.financial_events
                    WHERE tenant_id = :tenant_id AND original_event_id = :original_id
                    """
                ),
                {"tenant_id": TENANT_ONE, "original_id": original_one.id},
            ).scalar_one()
            concurrent_total = connection.execute(
                text(
                    """
                    SELECT COALESCE(sum(amount), 0) FROM public.financial_events
                    WHERE tenant_id = :tenant_id AND original_event_id = :original_id
                    """
                ),
                {"tenant_id": TENANT_ONE, "original_id": original_two.id},
            ).scalar_one()
            if Decimal(first_total) != Decimal("1000"):
                raise RuntimeError("Sequential correction total differs from 1000")
            if Decimal(concurrent_total) != Decimal("700"):
                raise RuntimeError("Concurrent correction serialization failed")
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
        _verify(selected_url)
        _drop_database(TEST_DATABASE_NAME)
        retained = False
        print(
            f"m23_reversal_capacity=PASS database={TEST_DATABASE_NAME} "
            "partial=PASS exact=PASS replay=PASS over_capacity=PASS "
            "type_match=PASS correction_chain=PASS concurrency=PASS "
            "database_trigger=PASS atomic_counts=5/5/5 "
            "upgrade_downgrade_upgrade=PASS dropped=true"
        )
    finally:
        if retained:
            print(
                "M2.3 verification failed; retained disposable database="
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
