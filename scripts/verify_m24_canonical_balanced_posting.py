"""Disposable PostgreSQL verification for M2.4 balanced posting."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
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

from core.domain.finance.atomic_posting_engine import (  # noqa: E402
    AtomicPostedFinancialEventEngine,
)
from core.domain.finance.event_contract import (  # noqa: E402
    FinancialEventValidationError,
)
from database import engine as application_engine  # noqa: E402
from scripts.verify_m21_canonical_event_engine import (  # noqa: E402
    ACCOUNT_CASH,
    ORG_ONE,
    SOURCE_REVENUE,
    SOURCE_SETTLEMENT,
    TENANT_ONE,
    _event_command,
    _install_fixtures,
)


TEST_DATABASE_NAME = "xbos_track_b_m24_posting_test"
EXPECTED_REVISION = "m24_balanced_posting_006"
PARENT_REVISION = "m23_reversal_capacity_005"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

SOURCE_REVERSAL = 932401
SOURCE_UNBOUND_EXPENSE = 932402
LEDGER_AR = 952401
LEDGER_REVENUE = 952402
LEDGER_CASH = 952403
LEDGER_UNAPPLIED = 952404
PERIOD_ID = 962401


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


def _install_posting_fixtures(selected_engine) -> None:
    with selected_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO public.kernel_source_records (
                    id, tenant_id, organization_unit_id, source_component,
                    aggregate_type, aggregate_external_id,
                    source_occurred_at, metadata
                ) VALUES
                    (:reversal, :tenant, :org, 'm24_verifier',
                     'payment_settlement_reversal', 'reversal-1', now(), '{}'::jsonb),
                    (:expense, :tenant, :org, 'm24_verifier',
                     'expense_transaction', 'expense-unbound', now(), '{}'::jsonb)
                """
            ),
            {
                "reversal": SOURCE_REVERSAL,
                "expense": SOURCE_UNBOUND_EXPENSE,
                "tenant": TENANT_ONE,
                "org": ORG_ONE,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO public.accounting_periods (
                    id, tenant_id, legal_entity_unit_id, period_code,
                    period_start, period_end, period_state
                ) VALUES (
                    :period, :tenant, :org, '2026-08',
                    DATE '2026-08-01', DATE '2026-08-31', 'open'
                )
                """
            ),
            {"period": PERIOD_ID, "tenant": TENANT_ONE, "org": ORG_ONE},
        )
        accounts = (
            (LEDGER_AR, "1100", "Trade Receivable", "asset", "debit"),
            (LEDGER_REVENUE, "4100", "Classified Revenue", "income", "credit"),
            (LEDGER_CASH, "1000", "Cash on Hand", "asset", "debit"),
            (LEDGER_UNAPPLIED, "2100", "Unapplied Receipts", "liability", "credit"),
        )
        for account_id, code, name, account_type, normal_balance in accounts:
            connection.execute(
                text(
                    """
                    INSERT INTO public.ledger_accounts (
                        id, tenant_id, legal_entity_unit_id,
                        account_code, account_name, account_type, normal_balance,
                        currency_policy, fixed_currency_code, effective_from,
                        metadata
                    ) VALUES (
                        :id, :tenant, :org, :code, :name, :account_type,
                        :normal_balance, 'fixed', 'XAF', DATE '2026-01-01',
                        '{}'::jsonb
                    )
                    """
                ),
                {
                    "id": account_id,
                    "tenant": TENANT_ONE,
                    "org": ORG_ONE,
                    "code": code,
                    "name": name,
                    "account_type": account_type,
                    "normal_balance": normal_balance,
                },
            )
        bindings = (
            ("trade_or_contract_receivable", LEDGER_AR, None),
            ("classified_revenue", LEDGER_REVENUE, None),
            ("cash_bank_or_provider_asset", LEDGER_CASH, ACCOUNT_CASH),
            ("unapplied_receipts_clearing", LEDGER_UNAPPLIED, None),
        )
        for account_role, ledger_account_id, operational_account_id in bindings:
            connection.execute(
                text(
                    """
                    INSERT INTO public.ledger_account_role_bindings (
                        tenant_id, legal_entity_unit_id, account_role,
                        binding_key, currency_code, ledger_account_id,
                        operational_account_id, effective_from, metadata
                    ) VALUES (
                        :tenant, :org, :account_role, 'default', 'XAF',
                        :ledger_account_id, :operational_account_id,
                        DATE '2026-01-01', '{}'::jsonb
                    )
                    """
                ),
                {
                    "tenant": TENANT_ONE,
                    "org": ORG_ONE,
                    "account_role": account_role,
                    "ledger_account_id": ledger_account_id,
                    "operational_account_id": operational_account_id,
                },
            )


def _revenue_command():
    return _event_command(
        public_id=UUID("10000000-0000-0000-0000-000000000240"),
        event_type_code="COMMERCIAL_REVENUE_RECOGNIZED",
        amount=Decimal("1000"),
        economic_role="recognition",
        source_record_id=SOURCE_REVENUE,
        idempotency_key="m24:revenue:1000",
        posting_context={"posting_profile_code": "commercial_recognition"},
        metadata={"source": "m24_posting_verifier"},
        actor_service="m24-verifier",
    )


def _settlement_command():
    return _event_command(
        public_id=UUID("10000000-0000-0000-0000-000000000241"),
        event_type_code="PAYMENT_SETTLED",
        amount=Decimal("1000"),
        economic_role="settlement_in",
        source_record_id=SOURCE_SETTLEMENT,
        target_operational_account_id=ACCOUNT_CASH,
        idempotency_key="m24:settlement:1000",
        classification_snapshot={
            "settlement_purpose": {"code": "commercial_collection"}
        },
        posting_context={"posting_profile_code": "inbound_settlement"},
        metadata={"source": "m24_posting_verifier"},
        actor_service="m24-verifier",
    )


def _reversal_command(original_event_id: int):
    return _event_command(
        public_id=UUID("10000000-0000-0000-0000-000000000242"),
        event_type_code="PAYMENT_SETTLEMENT_REVERSED",
        amount=Decimal("400"),
        economic_role="correction",
        source_record_id=SOURCE_REVERSAL,
        original_event_id=original_event_id,
        source_operational_account_id=ACCOUNT_CASH,
        target_operational_account_id=None,
        idempotency_key="m24:settlement:reverse:400",
        classification_snapshot={
            "reversal_reason": {"code": "provider_reversal"}
        },
        posting_context={
            "posting_profile_code": "inverse_original_settlement"
        },
        metadata={"source": "m24_posting_verifier"},
        actor_service="m24-verifier",
    )


def _unbound_expense_command(key: str):
    return _event_command(
        public_id=UUID("10000000-0000-0000-0000-000000000243"),
        event_type_code="EXPENSE_RECOGNIZED",
        amount=Decimal("25"),
        economic_role="recognition",
        source_record_id=SOURCE_UNBOUND_EXPENSE,
        idempotency_key=key,
        classification_snapshot={"expense_nature": {"code": "utilities"}},
        posting_context={"posting_profile_code": "expense_accrual"},
        metadata={"source": "m24_posting_verifier"},
        actor_service="m24-verifier",
    )


def _expect_validation(code: str, selected_engine, command) -> None:
    try:
        with Session(selected_engine) as session:
            with session.begin():
                AtomicPostedFinancialEventEngine.emit_and_post(session, command)
    except FinancialEventValidationError as exc:
        if exc.code != code:
            raise RuntimeError(
                f"Expected validation {code}; received {exc.code}"
            ) from exc
    else:
        raise RuntimeError(f"Expected validation failure {code}")


def _expect_direct_unbalanced_rejection(selected_engine) -> None:
    connection = selected_engine.connect()
    transaction = connection.begin()
    try:
        entry_id = connection.execute(
            text(
                """
                INSERT INTO public.journal_entries (
                    tenant_id, legal_entity_unit_id, accounting_period_id,
                    journal_code, entry_number, entry_state,
                    transaction_currency_code, base_currency_code,
                    posting_date, business_date, description,
                    posting_profile_code, created_by_service, correlation_id,
                    metadata
                ) VALUES (
                    :tenant, :org, :period, 'FIN', 'DIRECT-UNBALANCED', 'draft',
                    'XAF', 'XAF', DATE '2026-08-07', DATE '2026-08-07',
                    'direct bypass probe', 'commercial_recognition',
                    'm24-direct-probe', gen_random_uuid(), '{}'::jsonb
                ) RETURNING id
                """
            ),
            {"tenant": TENANT_ONE, "org": ORG_ONE, "period": PERIOD_ID},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO public.journal_lines (
                    tenant_id, journal_entry_id, line_number,
                    ledger_account_id, account_role,
                    transaction_currency_code, transaction_debit_amount,
                    transaction_credit_amount, base_currency_code,
                    base_debit_amount, base_credit_amount, fx_rate,
                    organization_unit_id, source_record_id, dimension_snapshot
                ) VALUES (
                    :tenant, :entry, 1, :account,
                    'trade_or_contract_receivable', 'XAF', 10, 0,
                    'XAF', 10, 0, 1, :org, :source, '{}'::jsonb
                )
                """
            ),
            {
                "tenant": TENANT_ONE,
                "entry": entry_id,
                "account": LEDGER_AR,
                "org": ORG_ONE,
                "source": SOURCE_REVENUE,
            },
        )
        connection.execute(
            text(
                """
                UPDATE public.journal_entries
                SET entry_state = 'posted', posted_at = now()
                WHERE tenant_id = :tenant AND id = :entry
                """
            ),
            {"tenant": TENANT_ONE, "entry": entry_id},
        )
        try:
            transaction.commit()
        except DBAPIError:
            pass
        else:
            raise RuntimeError("Database accepted an unbalanced posted journal")
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _expect_posted_immutability(selected_engine, journal_entry_id: int) -> None:
    try:
        with selected_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE public.journal_lines
                    SET transaction_debit_amount = transaction_debit_amount + 1,
                        base_debit_amount = base_debit_amount + 1
                    WHERE tenant_id = :tenant
                      AND journal_entry_id = :entry
                      AND transaction_debit_amount > 0
                    """
                ),
                {"tenant": TENANT_ONE, "entry": journal_entry_id},
            )
    except DBAPIError:
        return
    raise RuntimeError("Database allowed mutation of a posted journal line")


def _verify(selected_url: str) -> None:
    selected_engine = create_engine(selected_url)
    try:
        _install_fixtures(selected_engine)
        _install_posting_fixtures(selected_engine)

        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                revenue = AtomicPostedFinancialEventEngine.emit_and_post(
                    session, _revenue_command()
                )
                if revenue.journal_entry is None:
                    raise RuntimeError("Revenue event was not posted")
                if len(revenue.journal_entry.lines) != 2:
                    raise RuntimeError("Revenue journal is not two-line")

        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                settlement = AtomicPostedFinancialEventEngine.emit_and_post(
                    session, _settlement_command()
                )
                replay = AtomicPostedFinancialEventEngine.emit_and_post(
                    session, _settlement_command()
                )
                if settlement.journal_entry is None or replay.journal_entry is None:
                    raise RuntimeError("Settlement journal is missing")
                if settlement.journal_entry.id != replay.journal_entry.id:
                    raise RuntimeError("Posting replay changed journal identity")
                if not replay.replayed or not replay.journal_entry.replayed:
                    raise RuntimeError("Posting replay was not marked replayed")

        with Session(selected_engine, expire_on_commit=False) as session:
            with session.begin():
                reversal = AtomicPostedFinancialEventEngine.emit_and_post(
                    session,
                    _reversal_command(settlement.financial_event_result.event.id),
                )
                if reversal.journal_entry is None:
                    raise RuntimeError("Reversal journal is missing")
                original_lines = settlement.journal_entry.lines
                reversal_lines = reversal.journal_entry.lines
                if [line.ledger_account_id for line in original_lines] != [
                    line.ledger_account_id for line in reversal_lines
                ]:
                    raise RuntimeError("Reversal did not preserve original accounts")
                if reversal_lines[0].transaction_credit_amount != Decimal("400"):
                    raise RuntimeError("Reversal did not invert original debit")
                if reversal_lines[1].transaction_debit_amount != Decimal("400"):
                    raise RuntimeError("Reversal did not invert original credit")

        _expect_validation(
            "account_role_unbound",
            selected_engine,
            _unbound_expense_command("m24:unbound:expense"),
        )

        with selected_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE public.accounting_periods
                    SET period_state = 'closed', closed_at = now(), row_version = row_version + 1
                    WHERE tenant_id = :tenant AND id = :period
                    """
                ),
                {"tenant": TENANT_ONE, "period": PERIOD_ID},
            )
        _expect_validation(
            "accounting_period_not_open",
            selected_engine,
            _unbound_expense_command("m24:closed:period"),
        )
        with selected_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE public.accounting_periods
                    SET period_state = 'reopened', reopened_at = now(), row_version = row_version + 1
                    WHERE tenant_id = :tenant AND id = :period
                    """
                ),
                {"tenant": TENANT_ONE, "period": PERIOD_ID},
            )

        _expect_direct_unbalanced_rejection(selected_engine)
        _expect_posted_immutability(selected_engine, revenue.journal_entry.id)

        with selected_engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            if revision != EXPECTED_REVISION:
                raise RuntimeError(f"Unexpected revision: {revision}")
            tables = (
                "idempotency_records",
                "financial_events",
                "outbox_messages",
                "journal_entries",
                "journal_lines",
                "journal_entry_event_links",
            )
            counts = tuple(
                connection.execute(
                    text(f"SELECT count(*) FROM public.{table}")
                ).scalar_one()
                for table in tables
            )
            if counts != (3, 3, 3, 3, 6, 3):
                raise RuntimeError(
                    "Expected atomic counts (3,3,3,3,6,3); "
                    f"found {counts}"
                )
            unbalanced = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM (
                        SELECT journal_entry_id
                        FROM public.journal_lines
                        GROUP BY journal_entry_id
                        HAVING sum(transaction_debit_amount) <> sum(transaction_credit_amount)
                            OR sum(base_debit_amount) <> sum(base_credit_amount)
                    ) invalid
                    """
                )
            ).scalar_one()
            if unbalanced:
                raise RuntimeError("An unbalanced journal survived verification")
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
            f"m24_balanced_posting=PASS database={TEST_DATABASE_NAME} "
            "template=PASS replay=PASS inverse_original=PASS "
            "period_guard=PASS role_binding=PASS balance_trigger=PASS "
            "immutability=PASS atomic_counts=3/3/3/3/6/3 "
            "upgrade_downgrade_upgrade=PASS dropped=true"
        )
    finally:
        if retained:
            print(
                "M2.4 verification failed; retained disposable database="
                f"{TEST_DATABASE_NAME}"
            )


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
        selected_url = _base_url().render_as_string(hide_password=False)
        with create_engine(selected_url).connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            print(f"database={_base_url().database}")
            print(f"revision={revision}")
            for table in (
                "financial_events",
                "outbox_messages",
                "journal_entries",
                "journal_lines",
            ):
                count = connection.execute(
                    text(f"SELECT count(*) FROM public.{table}")
                ).scalar_one()
                print(f"{table}={count}")
            if revision != EXPECTED_REVISION:
                raise RuntimeError(f"Unexpected revision: {revision}")
            print("m24_development_schema=PASS")
    elif args.command_name == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("Exact disposable database confirmation is required")
        _drop_database(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
