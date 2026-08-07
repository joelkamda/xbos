"""Disposable PostgreSQL verification for the M2.1 canonical event engine."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
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
    CanonicalFinancialEventCommand,
    FinancialEventIdempotencyConflict,
    FinancialEventValidationError,
    canonical_command_fingerprint,
)
from core.domain.finance.event_engine import CanonicalFinancialEventEngine  # noqa: E402
from database import engine as application_engine  # noqa: E402


TEST_DATABASE_NAME = "xbos_track_b_m21_event_test"
EXPECTED_REVISION = "m20_event_catalog_003"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TENANT_ONE = 910001
TENANT_TWO = 910002
ORG_ONE = 920001
ORG_TWO = 920002
SOURCE_REVENUE = 930001
SOURCE_SETTLEMENT = 930002
SOURCE_TRANSFER = 930003
SOURCE_OTHER_TENANT = 930101
ACCOUNT_CASH = 940001
ACCOUNT_BANK = 940002
OCCURRED_AT = datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc)


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


def _upgrade(database_name: str) -> None:
    with _selected_database(database_name):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def _install_fixtures(selected_engine) -> None:
    with selected_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO public.tenants (
                    id, code, name, country_code, country_name,
                    currency, locale, timezone, settings, extra_metadata
                ) VALUES
                    (:tenant_one, 'M21T1', 'M2.1 Tenant One', 'CM', 'Cameroon',
                     'XAF', 'en-CM', 'Africa/Douala', '{}'::json, '{}'::json),
                    (:tenant_two, 'M21T2', 'M2.1 Tenant Two', 'CM', 'Cameroon',
                     'XAF', 'en-CM', 'Africa/Douala', '{}'::json, '{}'::json)
                """
            ),
            {"tenant_one": TENANT_ONE, "tenant_two": TENANT_TWO},
        )
        connection.execute(
            text(
                """
                INSERT INTO public.currency_assets (
                    code, asset_kind, display_name, minor_unit_scale,
                    maximum_storage_scale, active, metadata
                ) VALUES ('XAF', 'fiat', 'Central African CFA franc', 0, 8, TRUE, '{}'::jsonb)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO public.organization_units (
                    id, tenant_id, unit_type, code, name, timezone_name, active
                ) VALUES
                    (:org_one, :tenant_one, 'branch', 'M21-BR-1', 'M2.1 Branch One',
                     'Africa/Douala', TRUE),
                    (:org_two, :tenant_two, 'branch', 'M21-BR-2', 'M2.1 Branch Two',
                     'Africa/Douala', TRUE)
                """
            ),
            {
                "org_one": ORG_ONE,
                "tenant_one": TENANT_ONE,
                "org_two": ORG_TWO,
                "tenant_two": TENANT_TWO,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO public.tenant_currency_policies (
                    tenant_id, currency_code, rounding_mode,
                    cash_rounding_increment, active, effective_from, policy_version
                ) VALUES
                    (:tenant_one, 'XAF', 'half_up', 0, TRUE, :effective_from, 1),
                    (:tenant_two, 'XAF', 'half_up', 0, TRUE, :effective_from, 1)
                """
            ),
            {
                "tenant_one": TENANT_ONE,
                "tenant_two": TENANT_TWO,
                "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO public.kernel_source_records (
                    id, tenant_id, organization_unit_id, source_component,
                    aggregate_type, aggregate_external_id, source_occurred_at,
                    metadata
                ) VALUES
                    (:source_revenue, :tenant_one, :org_one, 'neutral_test',
                     'commercial_transaction', 'sale-1', :occurred_at, '{}'::jsonb),
                    (:source_settlement, :tenant_one, :org_one, 'neutral_test',
                     'payment_settlement', 'settlement-1', :occurred_at, '{}'::jsonb),
                    (:source_transfer, :tenant_one, :org_one, 'neutral_test',
                     'value_transfer', 'transfer-1', :occurred_at, '{}'::jsonb),
                    (:source_other, :tenant_two, :org_two, 'neutral_test',
                     'commercial_transaction', 'sale-other', :occurred_at, '{}'::jsonb)
                """
            ),
            {
                "source_revenue": SOURCE_REVENUE,
                "source_settlement": SOURCE_SETTLEMENT,
                "source_transfer": SOURCE_TRANSFER,
                "source_other": SOURCE_OTHER_TENANT,
                "tenant_one": TENANT_ONE,
                "tenant_two": TENANT_TWO,
                "org_one": ORG_ONE,
                "org_two": ORG_TWO,
                "occurred_at": OCCURRED_AT,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO public.operational_financial_accounts (
                    id, tenant_id, organization_unit_id, account_class,
                    account_type, code, display_name, currency_code,
                    aggregation_role, reconciliation_enabled, active, opened_at,
                    metadata
                ) VALUES
                    (:cash, :tenant_one, :org_one, 'treasury', 'cash',
                     'M21-CASH', 'M2.1 Cash', 'XAF', 'leaf', TRUE, TRUE,
                     :opened_at, '{}'::jsonb),
                    (:bank, :tenant_one, :org_one, 'treasury', 'bank',
                     'M21-BANK', 'M2.1 Bank', 'XAF', 'leaf', TRUE, TRUE,
                     :opened_at, '{}'::jsonb)
                """
            ),
            {
                "cash": ACCOUNT_CASH,
                "bank": ACCOUNT_BANK,
                "tenant_one": TENANT_ONE,
                "org_one": ORG_ONE,
                "opened_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        )


def _event_command(**overrides) -> CanonicalFinancialEventCommand:
    values = {
        "public_id": UUID("10000000-0000-0000-0000-000000000001"),
        "tenant_id": TENANT_ONE,
        "organization_unit_id": ORG_ONE,
        "event_type_code": "COMMERCIAL_REVENUE_RECOGNIZED",
        "event_version": 1,
        "amount": Decimal("1000.00"),
        "currency_code": "XAF",
        "economic_role": "recognition",
        "source_record_id": SOURCE_REVENUE,
        "occurred_at": OCCURRED_AT,
        "business_date": date(2026, 8, 7),
        "calendar_policy_version": 1,
        "idempotency_scope": "financial_event.emit",
        "idempotency_key": "m21:revenue:1",
        "correlation_id": UUID("20000000-0000-0000-0000-000000000001"),
        "classification_snapshot": {
            "revenue_nature": {"code": "food_sales"}
        },
        "posting_context": {"profile": "commercial_recognition"},
        "metadata": {"source": "m21_neutral_fixture"},
        "actor_service": "m21-verifier",
    }
    values.update(overrides)
    return CanonicalFinancialEventCommand(**values)


def _expect_validation(code: str, callback) -> None:
    try:
        callback()
    except FinancialEventValidationError as exc:
        if exc.code != code:
            raise RuntimeError(
                f"Expected validation code {code}; received {exc.code}"
            ) from exc
    else:
        raise RuntimeError(f"Expected validation failure {code}")


def _verify_engine(selected_url: str) -> None:
    selected_engine = create_engine(selected_url)
    try:
        _install_fixtures(selected_engine)
        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                revenue = _event_command()
                first = CanonicalFinancialEventEngine.emit(session, revenue)
                replay = CanonicalFinancialEventEngine.emit(session, revenue)
                if first.id != replay.id or replay.replayed is not True:
                    raise RuntimeError("Identical replay did not return original event")
                if first.metadata["_kernel"]["command_fingerprint"] != canonical_command_fingerprint(revenue):
                    raise RuntimeError("Stored command fingerprint differs")

                try:
                    CanonicalFinancialEventEngine.emit(
                        session, replace(revenue, amount=Decimal("1001"))
                    )
                except FinancialEventIdempotencyConflict as exc:
                    if exc.code != "idempotency_conflict":
                        raise
                else:
                    raise RuntimeError("Altered replay was accepted")

                _expect_validation(
                    "source_record_not_found",
                    lambda: CanonicalFinancialEventEngine.emit(
                        session,
                        replace(
                            revenue,
                            public_id=UUID("10000000-0000-0000-0000-000000000010"),
                            idempotency_key="m21:cross-tenant:1",
                            source_record_id=SOURCE_OTHER_TENANT,
                        ),
                    ),
                )
                _expect_validation(
                    "classification_roles_missing",
                    lambda: CanonicalFinancialEventEngine.emit(
                        session,
                        replace(
                            revenue,
                            public_id=UUID("10000000-0000-0000-0000-000000000011"),
                            idempotency_key="m21:missing-classification:1",
                            classification_snapshot={},
                        ),
                    ),
                )

                settlement = _event_command(
                    public_id=UUID("10000000-0000-0000-0000-000000000002"),
                    event_type_code="PAYMENT_SETTLED",
                    amount=Decimal("750"),
                    economic_role="settlement_in",
                    source_record_id=SOURCE_SETTLEMENT,
                    target_operational_account_id=ACCOUNT_CASH,
                    idempotency_key="m21:settlement:1",
                    correlation_id=UUID("20000000-0000-0000-0000-000000000002"),
                    classification_snapshot={
                        "settlement_purpose": {"code": "commercial_collection"}
                    },
                    posting_context={"profile": "inbound_settlement"},
                )
                CanonicalFinancialEventEngine.emit(session, settlement)

                transfer = _event_command(
                    public_id=UUID("10000000-0000-0000-0000-000000000003"),
                    event_type_code="VALUE_TRANSFERRED",
                    amount=Decimal("250"),
                    economic_role="transfer",
                    source_record_id=SOURCE_TRANSFER,
                    source_operational_account_id=ACCOUNT_CASH,
                    target_operational_account_id=ACCOUNT_BANK,
                    idempotency_key="m21:transfer:1",
                    correlation_id=UUID("20000000-0000-0000-0000-000000000003"),
                    classification_snapshot={
                        "transfer_purpose": {"code": "cash_to_bank"}
                    },
                    posting_context={"profile": "operational_value_transfer"},
                )
                CanonicalFinancialEventEngine.emit(session, transfer)

                _expect_validation(
                    "operational_account_required",
                    lambda: CanonicalFinancialEventEngine.emit(
                        session,
                        replace(
                            settlement,
                            public_id=UUID("10000000-0000-0000-0000-000000000012"),
                            idempotency_key="m21:settlement-no-account:1",
                            target_operational_account_id=None,
                        ),
                    ),
                )

        with selected_engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            if revision != EXPECTED_REVISION:
                raise RuntimeError(f"Unexpected revision after verification: {revision}")
            event_count = connection.execute(
                text("SELECT count(*) FROM public.financial_events")
            ).scalar_one()
            if event_count != 3:
                raise RuntimeError(f"Expected 3 committed events; found {event_count}")
            outbox_count = connection.execute(
                text("SELECT count(*) FROM public.outbox_messages")
            ).scalar_one()
            if outbox_count != 0:
                raise RuntimeError("M2.1 must not create outbox messages")

        connection = selected_engine.connect()
        transaction = connection.begin()
        try:
            try:
                connection.execute(
                    text(
                        """
                        UPDATE public.financial_events
                        SET amount = amount + 1
                        WHERE id = (SELECT min(id) FROM public.financial_events)
                        """
                    )
                )
            except DBAPIError:
                transaction.rollback()
            else:
                transaction.rollback()
                raise RuntimeError("Immutable financial event accepted an update")
        finally:
            connection.close()
    finally:
        selected_engine.dispose()


def _create_and_verify() -> None:
    _create_database(TEST_DATABASE_NAME)
    retained = True
    try:
        _upgrade(TEST_DATABASE_NAME)
        selected_url = _base_url().set(database=TEST_DATABASE_NAME).render_as_string(
            hide_password=False
        )
        _verify_engine(selected_url)
        _drop_database(TEST_DATABASE_NAME)
        retained = False
        print(
            f"m21_canonical_event_engine=PASS database={TEST_DATABASE_NAME} "
            "events=3 replay=PASS conflict=PASS tenant_isolation=PASS "
            "immutability=PASS outbox=0 dropped=true"
        )
    finally:
        if retained:
            print(
                "M2.1 verification failed; retained disposable database="
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
