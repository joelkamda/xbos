"""Read-only development and disposable proof for M3.5 obligation traces."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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

from core.domain.finance.allocation_contract import (
    AllocateValueCommand,
    CreateValueSourceCommand,
    ReverseAllocationCommand,
)
from core.domain.finance.allocation_engine import TransactionalAllocationEngine
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from core.domain.finance.obligation_trace_contract import ObligationTraceNotFound, ObligationTraceQuery
from core.domain.finance.obligation_trace_service import ObligationSettlementTraceService
from database import engine as application_engine

TEST_DATABASE_NAME = "xbos_track_b_m35_obligation_trace_test"
DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TARGET_REVISION = "m34_obligation_aging_010"
TENANT = 3501
ORG = 3511
CORRELATION = UUID("35000000-0000-0000-0000-000000000099")
OBLIGATION = UUID("35000000-0000-0000-0000-000000000101")
VALUE_SOURCE = UUID("35000000-0000-0000-0000-000000000201")
ALLOCATION = UUID("35000000-0000-0000-0000-000000000301")


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _url(database_name):
    return _application_url().set(database=database_name)


def _engine(database_name, *, autocommit=False):
    options = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    return create_engine(_url(database_name), pool_pre_ping=True, **options)


def _exists(database_name):
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database_name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally:
        engine.dispose()


def _drop(database_name):
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"refusing unapproved database: {database_name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": database_name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@contextmanager
def _selected(database_name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(database_name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _upgrade():
    with _selected(TEST_DATABASE_NAME):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)


def _seed(engine):
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO tenants(id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
          VALUES(:tenant,'M35T','M3.5 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)"""), {"tenant": TENANT})
        connection.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata) VALUES('XAF','fiat','CFA',0,8,TRUE,'{}'::jsonb)"))
        connection.execute(text("INSERT INTO organization_units(id,tenant_id,unit_type,code,name,timezone_name,active) VALUES(:org,:tenant,'legal_entity','M35','M3.5 Entity','Africa/Douala',TRUE)"), {"org": ORG, "tenant": TENANT})


def _obligation(base):
    return CreateObligationCommand(
        public_id=OBLIGATION, tenant_id=TENANT, organization_unit_id=ORG,
        debtor_party_id=UUID("35000000-0000-0000-0000-000000000010"),
        creditor_party_id=UUID("35000000-0000-0000-0000-000000000011"),
        obligation_type="trade_receivable", original_amount=Decimal("100"),
        currency_code="XAF", due_at=base + timedelta(days=30), occurred_at=base,
        business_date=base.date(), calendar_policy_version=1, correlation_id=CORRELATION,
        actor_service="m35.verifier", source_component="m35.verifier", source_record_id="o1",
        idempotency_scope="m35.obligation", idempotency_key="o1",
        lines=(ObligationLineCommand(1, "principal", "Principal", Decimal("1"), Decimal("100"), Decimal("100"), "o1-line"),),
    )


def _source(base):
    occurred = base + timedelta(days=1)
    return CreateValueSourceCommand(
        public_id=VALUE_SOURCE, tenant_id=TENANT, organization_unit_id=ORG,
        owner_party_id=UUID("35000000-0000-0000-0000-000000000010"), source_type="payment",
        source_amount=Decimal("60"), currency_code="XAF", occurred_at=occurred,
        business_date=occurred.date(), calendar_policy_version=1, correlation_id=CORRELATION,
        actor_service="m35.verifier", source_component="m35.verifier", source_record_id="s1",
        idempotency_scope="m35.source", idempotency_key="s1",
    )


def _allocation(base):
    occurred = base + timedelta(days=2)
    return AllocateValueCommand(
        public_id=ALLOCATION, tenant_id=TENANT, organization_unit_id=ORG,
        value_source_public_id=VALUE_SOURCE, obligation_public_id=OBLIGATION,
        allocation_amount=Decimal("60"), currency_code="XAF", occurred_at=occurred,
        business_date=occurred.date(), calendar_policy_version=1, correlation_id=CORRELATION,
        actor_service="m35.verifier", source_component="m35.verifier", source_record_id="a1",
        idempotency_scope="m35.allocate", idempotency_key="a1",
    )


def _reversal(base):
    occurred = base + timedelta(days=4)
    return ReverseAllocationCommand(
        public_id=UUID("35000000-0000-0000-0000-000000000401"), tenant_id=TENANT,
        organization_unit_id=ORG, payment_allocation_public_id=ALLOCATION,
        reversal_amount=Decimal("20"), currency_code="XAF", reason_code="correction",
        occurred_at=occurred, business_date=occurred.date(), calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m35.verifier", source_component="m35.verifier",
        source_record_id="r1", idempotency_scope="m35.reverse", idempotency_key="r1",
    )


TRACE_TABLES = (
    "financial_obligations", "financial_obligation_lines", "value_sources",
    "payment_allocations", "allocation_reversals", "obligation_state_transitions",
    "financial_events", "outbox_messages", "journal_entries", "journal_lines",
)


def _counts(engine):
    with engine.connect() as connection:
        return {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in TRACE_TABLES}


def _exercise(engine):
    base = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        TransactionalObligationEngine.create(session, _obligation(base))
        TransactionalAllocationEngine.create_value_source(session, _source(base))
        TransactionalAllocationEngine.allocate(session, _allocation(base))
        TransactionalAllocationEngine.reverse(session, _reversal(base))

    before = _counts(engine)
    with Session(engine) as session:
        current = ObligationSettlementTraceService.explain(session, ObligationTraceQuery(TENANT, OBLIGATION))
        before_allocation = ObligationSettlementTraceService.explain(
            session, ObligationTraceQuery(TENANT, OBLIGATION, base + timedelta(days=1), (base + timedelta(days=1)).date())
        )
        after_allocation = ObligationSettlementTraceService.explain(
            session, ObligationTraceQuery(TENANT, OBLIGATION, base + timedelta(days=3), (base + timedelta(days=3)).date())
        )
        try:
            ObligationSettlementTraceService.explain(session, ObligationTraceQuery(TENANT + 1, OBLIGATION))
        except ObligationTraceNotFound:
            pass
        else:
            raise RuntimeError("tenant isolation failed")

    if current.balance["outstanding_amount"] != Decimal("60"):
        raise RuntimeError("current settlement balance differs")
    if before_allocation.balance["outstanding_amount"] != Decimal("100"):
        raise RuntimeError("pre-allocation cutoff differs")
    if after_allocation.balance["outstanding_amount"] != Decimal("40"):
        raise RuntimeError("post-allocation cutoff differs")
    if len(current.allocations) != 1 or len(current.allocations[0]["reversal_facts"]) != 1:
        raise RuntimeError("allocation/reversal lineage differs")
    if current.balance["state_as_of"] != "partially_satisfied" or not current.state_history:
        raise RuntimeError("lifecycle trace differs")
    if current.integrity["status"] != "PASS":
        raise RuntimeError(f"trace integrity failed: {current.integrity}")
    if "not asserted causation" not in current.explanation["ledger_evidence"]:
        raise RuntimeError("correlation boundary differs")
    if any("id" in row for row in current.allocations + current.state_history):
        raise RuntimeError("internal database identifier leaked")
    if _counts(engine) != before:
        raise RuntimeError("trace query mutated persisted facts")


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != TARGET_REVISION:
            raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20:
            raise RuntimeError("canonical event catalog count differs")
        for table in TRACE_TABLES:
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count:
                raise RuntimeError(f"development table not empty: {table}={count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m35_obligation_trace_development=PASS canonical_head_unchanged=PASS development_empty=PASS")


def _create_and_verify():
    _development_verify()
    _create()
    engine = None
    try:
        _upgrade()
        engine = _engine(TEST_DATABASE_NAME)
        _seed(engine)
        _exercise(engine)
        engine.dispose()
        engine = None
        _drop(TEST_DATABASE_NAME)
        _development_verify()
        print("m35_obligation_trace=PASS database=xbos_track_b_m35_obligation_trace_test canonical_head_unchanged=PASS current=PASS as_of=PASS allocation_chain=PASS reversal_chain=PASS lifecycle=PASS tenant_scope=PASS read_only=PASS integrity=PASS correlation_boundary=PASS dropped=true")
    except Exception:
        if engine is not None:
            engine.dispose()
        print(f"M3.5 verification failed; retained disposable database={TEST_DATABASE_NAME}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("verify")
    subparsers.add_parser("create-and-verify")
    drop = subparsers.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    arguments = parser.parse_args()
    if arguments.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif arguments.command == "verify":
        _development_verify()
    elif arguments.command == "drop":
        _drop(arguments.confirm_database_name)
        print(f"dropped={arguments.confirm_database_name}")
    else:
        _create_and_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
