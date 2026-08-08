"""Disposable PostgreSQL proof for M2.5 financial dimensions."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.atomic_posting_engine import (  # noqa: E402
    AtomicPostedFinancialEventEngine,
)
from core.domain.finance.event_contract import (  # noqa: E402
    CanonicalFinancialEventCommand,
    FinancialEventValidationError,
)
from database import engine as application_engine  # noqa: E402


TEST_DATABASE_NAME = "xbos_track_b_m25_dimensions_test"
TENANT_ID = 925001
OTHER_TENANT_ID = 925002
ORG_ID = 925001
OTHER_ORG_ID = 925002
BUSINESS_DATE = date(2026, 8, 7)
OCCURRED_AT = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _base_url():
    selected = make_url(
        application_engine.url.render_as_string(hide_password=False)
    )
    if selected.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"Refusing non-local PostgreSQL host: {selected.host!r}")
    return selected


def _test_url():
    return _base_url().set(database=TEST_DATABASE_NAME)


def _admin_engine():
    return create_engine(
        _base_url().set(database="postgres"), isolation_level="AUTOCOMMIT"
    )


def _database_exists() -> bool:
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            return bool(
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": TEST_DATABASE_NAME},
                ).scalar()
            )
    finally:
        engine.dispose()


def _create_database() -> None:
    if _database_exists():
        raise RuntimeError(
            f"Disposable database already exists unexpectedly: {TEST_DATABASE_NAME}"
        )
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0 ENCODING \'UTF8\''
            )
    finally:
        engine.dispose()


def _drop_database() -> None:
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :name AND pid <> pg_backend_pid()
                    """
                ),
                {"name": TEST_DATABASE_NAME},
            )
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}"'
            )
    finally:
        engine.dispose()


@contextmanager
def _database_environment():
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _test_url().render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _alembic(revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    with _database_environment():
        if downgrade:
            alembic_command.downgrade(config, revision)
        else:
            alembic_command.upgrade(config, revision)


def _seed(session: Session) -> dict[str, int]:
    session.execute(
        text(
            """
            INSERT INTO public.tenants
                (id, code, name, country_code, currency, locale, timezone,
                 settings, extra_metadata)
            VALUES
                (:tenant, 'm25-proof', 'M2.5 Proof Tenant', 'CM', 'XAF',
                 'en-CM', 'Africa/Douala', '{}', '{}'),
                (:other_tenant, 'm25-other', 'M2.5 Other Tenant', 'CM', 'XAF',
                 'en-CM', 'Africa/Douala', '{}', '{}')
            """
        ),
        {"tenant": TENANT_ID, "other_tenant": OTHER_TENANT_ID},
    )
    session.execute(
        text(
            """
            INSERT INTO public.organization_units
                (id, tenant_id, unit_type, code, name, timezone_name)
            VALUES
                (:org, :tenant, 'legal_entity', 'M25', 'M2.5 Proof Entity', 'Africa/Douala'),
                (:other_org, :other_tenant, 'legal_entity', 'OTHER', 'Other Entity', 'Africa/Douala')
            """
        ),
        {
            "org": ORG_ID,
            "tenant": TENANT_ID,
            "other_org": OTHER_ORG_ID,
            "other_tenant": OTHER_TENANT_ID,
        },
    )
    session.execute(
        text(
            """
            INSERT INTO public.currency_assets
                (code, asset_kind, display_name, minor_unit_scale, maximum_storage_scale)
            VALUES ('XAF', 'fiat', 'Central African CFA franc', 0, 8)
            """
        )
    )
    session.execute(
        text(
            """
            INSERT INTO public.tenant_currency_policies
                (tenant_id, currency_code, rounding_mode, effective_from, policy_version)
            VALUES
                (:tenant, 'XAF', 'half_up', :occurred_at, 1),
                (:other_tenant, 'XAF', 'half_up', :occurred_at, 1)
            """
        ),
        {
            "tenant": TENANT_ID,
            "other_tenant": OTHER_TENANT_ID,
            "occurred_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    )
    source = session.execute(
        text(
            """
            INSERT INTO public.kernel_source_records
                (tenant_id, organization_unit_id, source_component,
                 aggregate_type, aggregate_external_id, source_occurred_at)
            VALUES
                (:tenant, :org, 'm25.verifier', 'commercial_transaction',
                 'm25-commercial', :occurred_at),
                (:tenant, :org, 'm25.verifier', 'expense_transaction',
                 'm25-expense', :occurred_at),
                (:tenant, :org, 'm25.verifier', 'financial_event_reversal',
                 'm25-reversal', :occurred_at)
            RETURNING id, aggregate_type
            """
        ),
        {
            "tenant": TENANT_ID,
            "org": ORG_ID,
            "occurred_at": OCCURRED_AT,
        },
    ).mappings().all()
    source_ids = {row["aggregate_type"]: int(row["id"]) for row in source}

    accounts: dict[str, int] = {}
    for code, name, account_type, balance in (
        ("AR", "Trade receivable", "asset", "debit"),
        ("REV", "Classified revenue", "income", "credit"),
        ("EXP", "Classified expense", "expense", "debit"),
        ("AP", "Trade or accrued payable", "liability", "credit"),
    ):
        accounts[code] = int(
            session.execute(
                text(
                    """
                    INSERT INTO public.ledger_accounts
                        (tenant_id, legal_entity_unit_id, account_code,
                         account_name, account_type, normal_balance,
                         currency_policy, fixed_currency_code, effective_from)
                    VALUES
                        (:tenant, :org, :code, :name, :account_type,
                         :balance, 'fixed', 'XAF', :effective_from)
                    RETURNING id
                    """
                ),
                {
                    "tenant": TENANT_ID,
                    "org": ORG_ID,
                    "code": code,
                    "name": name,
                    "account_type": account_type,
                    "balance": balance,
                    "effective_from": date(2026, 1, 1),
                },
            ).scalar_one()
        )
    for role, account_code in (
        ("trade_or_contract_receivable", "AR"),
        ("classified_revenue", "REV"),
        ("classified_expense", "EXP"),
        ("trade_or_accrued_payable", "AP"),
    ):
        session.execute(
            text(
                """
                INSERT INTO public.ledger_account_role_bindings
                    (tenant_id, legal_entity_unit_id, account_role, binding_key,
                     currency_code, ledger_account_id, effective_from)
                VALUES
                    (:tenant, :org, :role, 'default', 'XAF', :account_id, :effective_from)
                """
            ),
            {
                "tenant": TENANT_ID,
                "org": ORG_ID,
                "role": role,
                "account_id": accounts[account_code],
                "effective_from": date(2026, 1, 1),
            },
        )
    session.execute(
        text(
            """
            INSERT INTO public.accounting_periods
                (tenant_id, legal_entity_unit_id, period_code,
                 period_start, period_end, period_state)
            VALUES
                (:tenant, :org, '2026-08', '2026-08-01', '2026-08-31', 'open')
            """
        ),
        {"tenant": TENANT_ID, "org": ORG_ID},
    )

    dimension_ids: dict[str, int] = {}
    for code, name in (
        ("channel", "Sales channel"),
        ("department", "Department"),
        ("cost_center", "Cost center"),
        ("project", "Project"),
        ("campaign", "Campaign"),
    ):
        dimension_ids[code] = int(
            session.execute(
                text(
                    """
                    INSERT INTO public.financial_dimension_types
                        (tenant_id, dimension_code, display_name, effective_from)
                    VALUES (:tenant, :code, :name, :effective_from)
                    RETURNING id
                    """
                ),
                {
                    "tenant": TENANT_ID,
                    "code": code,
                    "name": name,
                    "effective_from": date(2026, 1, 1),
                },
            ).scalar_one()
        )

    value_ids: dict[str, int] = {}
    for dimension, code, name in (
        ("channel", "counter", "Counter"),
        ("channel", "whatsapp", "WhatsApp"),
        ("department", "retail", "Retail"),
        ("cost_center", "sales", "Sales"),
        ("project", "launch", "Launch"),
        ("campaign", "august", "August campaign"),
    ):
        value_ids[f"{dimension}:{code}"] = int(
            session.execute(
                text(
                    """
                    INSERT INTO public.financial_dimension_values
                        (tenant_id, dimension_type_id, value_code,
                         display_name, effective_from)
                    VALUES
                        (:tenant, :dimension_type_id, :code, :name, :effective_from)
                    RETURNING id
                    """
                ),
                {
                    "tenant": TENANT_ID,
                    "dimension_type_id": dimension_ids[dimension],
                    "code": code,
                    "name": name,
                    "effective_from": date(2026, 1, 1),
                },
            ).scalar_one()
        )

    policies = (
        ("commercial_recognition", "*", dimension_ids["channel"], "required", value_ids["channel:counter"]),
        ("commercial_recognition", "classified_revenue", dimension_ids["department"], "required", None),
        ("commercial_recognition", "classified_revenue", dimension_ids["cost_center"], "optional", None),
        ("commercial_recognition", "classified_revenue", dimension_ids["project"], "forbidden", None),
        ("expense_accrual", "*", dimension_ids["channel"], "required", value_ids["channel:counter"]),
        ("expense_accrual", "classified_expense", dimension_ids["department"], "optional", None),
    )
    for profile, role, type_id, requirement, default_id in policies:
        session.execute(
            text(
                """
                INSERT INTO public.posting_dimension_policies
                    (tenant_id, legal_entity_unit_id, posting_profile_code,
                     account_role, dimension_type_id, requirement,
                     default_dimension_value_id, effective_from)
                VALUES
                    (:tenant, :org, :profile, :role,
                     :type_id, :requirement, :default_id, :effective_from)
                """
            ),
            {
                "tenant": TENANT_ID,
                "org": ORG_ID,
                "profile": profile,
                "role": role,
                "type_id": type_id,
                "requirement": requirement,
                "default_id": default_id,
                "effective_from": date(2026, 1, 1),
            },
        )

    other_type = int(
        session.execute(
            text(
                """
                INSERT INTO public.financial_dimension_types
                    (tenant_id, dimension_code, display_name, effective_from)
                VALUES (:tenant, 'channel', 'Other channel', :effective_from)
                RETURNING id
                """
            ),
            {
                "tenant": OTHER_TENANT_ID,
                "effective_from": date(2026, 1, 1),
            },
        ).scalar_one()
    )
    session.execute(
        text(
            """
            INSERT INTO public.financial_dimension_values
                (tenant_id, dimension_type_id, value_code, display_name, effective_from)
            VALUES (:tenant, :type_id, 'foreign', 'Foreign tenant value', :effective_from)
            """
        ),
        {
            "tenant": OTHER_TENANT_ID,
            "type_id": other_type,
            "effective_from": date(2026, 1, 1),
        },
    )
    session.commit()
    return {
        "commercial_source": source_ids["commercial_transaction"],
        "expense_source": source_ids["expense_transaction"],
        "reversal_source": source_ids["financial_event_reversal"],
    }


def _revenue_command(source_id: int, key: str, posting_context: dict):
    return CanonicalFinancialEventCommand(
        public_id=uuid4(),
        tenant_id=TENANT_ID,
        organization_unit_id=ORG_ID,
        event_type_code="COMMERCIAL_REVENUE_RECOGNIZED",
        event_version=1,
        amount=Decimal("100"),
        currency_code="XAF",
        economic_role="recognition",
        source_record_id=source_id,
        occurred_at=OCCURRED_AT,
        business_date=BUSINESS_DATE,
        calendar_policy_version=1,
        idempotency_scope="m25.verifier",
        idempotency_key=key,
        correlation_id=uuid4(),
        classification_snapshot={"revenue_nature": "verification"},
        posting_context=posting_context,
        actor_service="xbos.finance.m25.verifier",
    )


def _correction_command(source_id: int, original_event_id: int):
    return CanonicalFinancialEventCommand(
        public_id=uuid4(),
        tenant_id=TENANT_ID,
        organization_unit_id=ORG_ID,
        event_type_code="FINANCIAL_FACT_REVERSED",
        event_version=1,
        amount=Decimal("25"),
        currency_code="XAF",
        economic_role="correction",
        source_record_id=source_id,
        original_event_id=original_event_id,
        occurred_at=OCCURRED_AT,
        business_date=BUSINESS_DATE,
        calendar_policy_version=1,
        idempotency_scope="m25.verifier",
        idempotency_key="correction",
        correlation_id=uuid4(),
        classification_snapshot={"reversal_reason": "verification"},
        posting_context={},
        actor_service="xbos.finance.m25.verifier",
    )


def _expense_command(source_id: int):
    return CanonicalFinancialEventCommand(
        public_id=uuid4(),
        tenant_id=TENANT_ID,
        organization_unit_id=ORG_ID,
        event_type_code="EXPENSE_RECOGNIZED",
        event_version=1,
        amount=Decimal("80"),
        currency_code="XAF",
        economic_role="recognition",
        source_record_id=source_id,
        occurred_at=OCCURRED_AT,
        business_date=BUSINESS_DATE,
        calendar_policy_version=1,
        idempotency_scope="m25.verifier",
        idempotency_key="expense-original",
        correlation_id=uuid4(),
        classification_snapshot={"expense_nature": "verification"},
        posting_context={
            "dimension_values": {"channel": "whatsapp"},
            "account_role_dimension_values": {
                "classified_expense": {"department": "retail"}
            },
        },
        actor_service="xbos.finance.m25.verifier",
    )


def _expect_rejection(engine, source_id: int, key: str, context: dict, code: str):
    with Session(engine) as session:
        try:
            AtomicPostedFinancialEventEngine.emit_and_post(
                session, _revenue_command(source_id, key, context)
            )
        except FinancialEventValidationError as exc:
            session.rollback()
            if exc.code != code:
                raise AssertionError(f"expected {code}, received {exc.code}") from exc
        else:
            session.rollback()
            raise AssertionError(f"expected financial dimension rejection {code}")


def _verify(engine, ids: dict[str, int]) -> None:
    first_context = {
        "dimension_values": {"channel": "whatsapp"},
        "account_role_dimension_values": {
            "classified_revenue": {
                "department": "retail",
                "cost_center": "sales",
            }
        },
    }
    default_context = {
        "account_role_dimension_values": {
            "classified_revenue": {"department": "retail"}
        }
    }
    with Session(engine) as session:
        first = AtomicPostedFinancialEventEngine.emit_and_post(
            session,
            _revenue_command(ids["commercial_source"], "global-override", first_context),
        )
        session.commit()
        first_entry_id = first.journal_entry.id

    with Session(engine) as session:
        rows = session.execute(
            text(
                """
                SELECT account_role, dimension_snapshot
                FROM public.journal_lines
                WHERE tenant_id = :tenant AND journal_entry_id = :entry
                ORDER BY line_number
                """
            ),
            {"tenant": TENANT_ID, "entry": first_entry_id},
        ).mappings().all()
        by_role = {row["account_role"]: row["dimension_snapshot"] for row in rows}
        debit_dimensions = by_role["trade_or_contract_receivable"]["financial_dimensions"]
        revenue_dimensions = by_role["classified_revenue"]["financial_dimensions"]
        assert debit_dimensions["channel"]["value_code"] == "whatsapp"
        assert revenue_dimensions["channel"]["value_code"] == "whatsapp"
        assert revenue_dimensions["department"]["value_code"] == "retail"
        assert revenue_dimensions["cost_center"]["value_code"] == "sales"

    with Session(engine) as session:
        defaulted = AtomicPostedFinancialEventEngine.emit_and_post(
            session,
            _revenue_command(ids["commercial_source"], "required-default", default_context),
        )
        session.commit()
        for line in defaulted.journal_entry.lines:
            channel = line.dimension_snapshot["financial_dimensions"]["channel"]
            assert channel["value_code"] == "counter"
            assert channel["selection_source"] == "policy_default"

    _expect_rejection(
        engine,
        ids["commercial_source"],
        "missing-required",
        {"dimension_values": {"channel": "counter"}},
        "dimension_required",
    )
    _expect_rejection(
        engine,
        ids["commercial_source"],
        "forbidden",
        {
            "dimension_values": {"channel": "counter"},
            "account_role_dimension_values": {
                "classified_revenue": {"department": "retail", "project": "launch"}
            },
        },
        "dimension_forbidden",
    )
    _expect_rejection(
        engine,
        ids["commercial_source"],
        "unconfigured",
        {
            "dimension_values": {"channel": "counter"},
            "account_role_dimension_values": {
                "classified_revenue": {"department": "retail", "campaign": "august"}
            },
        },
        "dimension_not_allowed",
    )
    _expect_rejection(
        engine,
        ids["commercial_source"],
        "tenant-isolation",
        {
            "dimension_values": {"channel": "foreign"},
            "account_role_dimension_values": {
                "classified_revenue": {"department": "retail"}
            },
        },
        "dimension_value_missing",
    )

    with Session(engine) as session:
        expense = AtomicPostedFinancialEventEngine.emit_and_post(
            session, _expense_command(ids["expense_source"])
        )
        session.commit()
        expense_event_id = expense.financial_event_result.event.id
        expense_entry_id = expense.journal_entry.id

    with Session(engine) as session:
        correction = AtomicPostedFinancialEventEngine.emit_and_post(
            session,
            _correction_command(ids["reversal_source"], expense_event_id),
        )
        session.commit()
        correction_entry_id = correction.journal_entry.id
    with Session(engine) as session:
        original = session.execute(
            text(
                """
                SELECT line_number, dimension_snapshot
                FROM public.journal_lines
                WHERE tenant_id = :tenant AND journal_entry_id = :entry
                ORDER BY line_number
                """
            ),
            {"tenant": TENANT_ID, "entry": expense_entry_id},
        ).mappings().all()
        inverse = session.execute(
            text(
                """
                SELECT line_number, dimension_snapshot
                FROM public.journal_lines
                WHERE tenant_id = :tenant AND journal_entry_id = :entry
                ORDER BY line_number
                """
            ),
            {"tenant": TENANT_ID, "entry": correction_entry_id},
        ).mappings().all()
        assert [row["dimension_snapshot"] for row in inverse] == [
            row["dimension_snapshot"] for row in original
        ]

    with Session(engine) as session:
        line_id = session.execute(
            text(
                """
                SELECT id FROM public.journal_lines
                WHERE tenant_id = :tenant AND journal_entry_id = :entry
                ORDER BY line_number LIMIT 1
                """
            ),
            {"tenant": TENANT_ID, "entry": first_entry_id},
        ).scalar_one()
        try:
            session.execute(
                text(
                    """
                    UPDATE public.journal_lines
                    SET dimension_snapshot = '{}'::jsonb
                    WHERE tenant_id = :tenant AND id = :line
                    """
                ),
                {"tenant": TENANT_ID, "line": line_id},
            )
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        else:
            raise AssertionError("posted dimension snapshot mutation unexpectedly succeeded")

    with Session(engine) as session:
        counts = tuple(
            int(
                session.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one()
            )
            for table in (
                "idempotency_records",
                "financial_events",
                "outbox_messages",
                "journal_entries",
                "journal_lines",
                "journal_entry_event_links",
            )
        )
        if counts != (4, 4, 4, 4, 8, 4):
            raise AssertionError(f"unexpected atomic counts: {counts}")


def _create_and_verify() -> None:
    _create_database()
    engine = create_engine(_test_url())
    try:
        _alembic("head")
        _alembic("m24_balanced_posting_006", downgrade=True)
        _alembic("head")
        with Session(engine) as session:
            ids = _seed(session)
        _verify(engine, ids)
    except Exception:
        engine.dispose()
        print(
            f"M2.5 verification failed; retained disposable database={TEST_DATABASE_NAME}",
            file=sys.stderr,
        )
        raise
    engine.dispose()
    _drop_database()
    print(
        "m25_financial_dimensions=PASS "
        f"database={TEST_DATABASE_NAME} "
        "global_override=PASS required_default=PASS "
        "missing_forbidden=PASS tenant_isolation=PASS "
        "correction_inheritance=PASS immutability=PASS "
        "atomic_counts=PASS upgrade_downgrade_upgrade=PASS dropped=true"
    )


def _verify_development() -> None:
    engine = application_engine
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one()
        counts = {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM public.{table}")
                ).scalar_one()
            )
            for table in (
                "financial_dimension_types",
                "financial_dimension_values",
                "posting_dimension_policies",
                "financial_events",
                "outbox_messages",
            )
        }
    print(f"database={engine.url.database}")
    print(f"revision={revision}")
    for table, count in counts.items():
        print(f"{table}={count}")
    if revision != "m25_financial_dimensions_007":
        raise RuntimeError("development database is not at the M2.5 revision")
    if any(counts[table] for table in counts):
        raise RuntimeError("M2.5 development tables and financial targets must remain empty")
    print("m25_financial_dimensions_development=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("create-and-verify")
    sub.add_parser("verify")
    drop = sub.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()

    if args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_database_exists()).lower()}")
    elif args.command == "create-and-verify":
        _create_and_verify()
    elif args.command == "verify":
        _verify_development()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError(
                "Refusing unexpected test database; exact confirmation is required"
            )
        _drop_database()
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
