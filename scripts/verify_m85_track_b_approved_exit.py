"""Aggregate clean-replay, composition, adversarial, recovery and exit proof for Track B."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.allocation_contract import AllocateValueCommand, CreateValueSourceCommand
from core.domain.finance.allocation_engine import TransactionalAllocationEngine
from core.domain.finance.atomic_posting_engine import AtomicPostedFinancialEventEngine
from core.domain.finance.event_contract import FinancialEventIdempotencyConflict, FinancialEventValidationError
from core.domain.finance.m6_acceptance import EXPECTED_HEAD
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.track_b_acceptance import validate_authority_exit, validate_public_artifacts, validate_release_manifest
from core.domain.finance.track_b_exit_contract import TrackBExitEvidence
from core.domain.finance.transactional_event_engine import TransactionalCanonicalFinancialEventEngine
from database import engine as application_engine
from scripts import verify_m64_reconciliation_controls as m64
from scripts.verify_m21_canonical_event_engine import (
    ORG_ONE,
    SOURCE_OTHER_TENANT,
    TENANT_ONE,
    _event_command,
    _install_fixtures,
)
from scripts.verify_m24_canonical_balanced_posting import (
    PERIOD_ID,
    _install_posting_fixtures,
    _revenue_command,
    _reversal_command,
    _settlement_command,
    _unbound_expense_command,
)
from scripts.verify_m43_payment_settlements import _seed_scope
from scripts.verify_m83_performance_recovery import _payment_fixture

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m85_exit_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
EMPTY_TABLES = (
    "idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
    "financial_obligations", "value_sources", "payment_allocations", "allocation_reversals",
    "canonical_payment_intents", "canonical_payment_attempts", "payment_settlements",
    "reconciliation_windows", "reconciliation_controls",
)
SELECTED_SUITES = (
    ("M8.0", "scripts/verify_m80_global_financial_invariants.py"),
    ("M8.1", "scripts/verify_m81_ordering_offline_isolation_authorization.py"),
    ("M8.2", "scripts/verify_m82_external_failure_resilience.py"),
    ("M8.3", "scripts/verify_m83_performance_recovery.py"),
    ("M8.4", "scripts/verify_m84_pack_financial_conformance.py"),
)
APPROVER_BRANCH_ID = 985001
APPROVER_USER_ID = 985001


def _url():
    value = make_url(application_engine.url)
    if value.host not in LOCAL_HOSTS:
        raise RuntimeError(f"refusing non-local PostgreSQL host={value.host!r}")
    return value


def _engine(name, autocommit=False):
    options = {"pool_pre_ping": True}
    if autocommit:
        options["isolation_level"] = "AUTOCOMMIT"
    return create_engine(_url().set(database=name), **options)


def _exists(name):
    selected = _engine("postgres", True)
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally:
        selected.dispose()


def _create_clean():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    selected = _engine("postgres", True)
    try:
        with selected.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0')
    finally:
        selected.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    selected = _engine("postgres", True)
    try:
        with selected.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        selected.dispose()


@contextmanager
def _selected_database(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _migrate(revision, *, downgrade=False):
    with _selected_database(TEST_DATABASE_NAME):
        (alembic_command.downgrade if downgrade else alembic_command.upgrade)(Config(str(ROOT / "alembic.ini")), revision)


def _expect(code, action):
    try:
        action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected={code}; actual={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error not raised={code}")


def _development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"development database must be={DEVELOPMENT_DATABASE_NAME}")
    manifest = validate_release_manifest(ROOT)
    validate_authority_exit(ROOT)
    validate_public_artifacts(ROOT)
    with application_engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != DEVELOPMENT_DATABASE_NAME or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
        existing = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        for table in EMPTY_TABLES:
            if table in existing and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development financial table not empty={table}")
    print(f"database={database}")
    print(f"revision={revision}")
    print("release_manifests=" + ",".join(f"m{index + 2}:{count}" for index, count in enumerate(manifest.historical_release_counts)))
    print("m85_track_b_development_exit=PASS manifest=PASS canonical_lineage=PASS M7_frozen=PASS development_empty=PASS hidden_writers=NONE schema_neutral=PASS")


def _obligation_scenario(selected):
    base = datetime(2026, 8, 12, 8, tzinfo=timezone.utc)
    debtor = UUID("85000000-0000-0000-0010-000000000001")
    creditor = UUID("85000000-0000-0000-0010-000000000002")
    obligation_public = UUID("85000000-0000-0000-0020-000000000001")
    source_public = UUID("85000000-0000-0000-0030-000000000001")
    allocation_public = UUID("85000000-0000-0000-0040-000000000001")
    amount = Decimal("125")
    obligation = CreateObligationCommand(
        public_id=obligation_public, tenant_id=TENANT_ONE, organization_unit_id=ORG_ONE,
        debtor_party_id=debtor, creditor_party_id=creditor, obligation_type="trade_receivable",
        original_amount=amount, currency_code="XAF", due_at=base + timedelta(days=30), occurred_at=base,
        business_date=date(2026, 8, 12), calendar_policy_version=1,
        correlation_id=UUID("85000000-0000-0000-0090-000000000001"), actor_service="m85.verifier",
        source_component="m85.aggregate", source_record_id="obligation-1",
        idempotency_scope="m85.obligation", idempotency_key="obligation-1",
        lines=(ObligationLineCommand(1, "principal", "Aggregate principal", Decimal(1), amount, amount, "line-1"),),
    )
    value = CreateValueSourceCommand(
        public_id=source_public, tenant_id=TENANT_ONE, organization_unit_id=ORG_ONE, owner_party_id=debtor,
        source_type="payment", source_amount=amount, currency_code="XAF", occurred_at=base,
        business_date=date(2026, 8, 12), calendar_policy_version=1,
        correlation_id=UUID("85000000-0000-0000-0090-000000000001"), actor_service="m85.verifier",
        source_component="m85.aggregate", source_record_id="value-1",
        idempotency_scope="m85.value", idempotency_key="value-1",
    )
    allocation = AllocateValueCommand(
        public_id=allocation_public, tenant_id=TENANT_ONE, organization_unit_id=ORG_ONE,
        value_source_public_id=source_public, obligation_public_id=obligation_public,
        allocation_amount=amount, currency_code="XAF", occurred_at=base,
        business_date=date(2026, 8, 12), calendar_policy_version=1,
        correlation_id=UUID("85000000-0000-0000-0090-000000000001"), actor_service="m85.verifier",
        source_component="m85.aggregate", source_record_id="allocation-1",
        idempotency_scope="m85.allocation", idempotency_key="allocation-1",
    )
    with Session(selected, expire_on_commit=False) as session, session.begin():
        first = TransactionalObligationEngine.create(session, obligation)
        replay = TransactionalObligationEngine.create(session, obligation)
        if (
            first.replayed
            or not replay.replayed
            or first.obligation.public_id != replay.obligation.public_id
            or first.obligation.id != replay.obligation.id
        ):
            raise RuntimeError("obligation replay changed canonical identity or disposition")
        TransactionalAllocationEngine.create_value_source(session, value)
        TransactionalAllocationEngine.allocate(session, allocation)
        obligation_count = session.execute(
            text("SELECT count(*) FROM financial_obligations WHERE tenant_id=:tenant AND public_id=:public"),
            {"tenant": TENANT_ONE, "public": str(obligation_public)},
        ).scalar_one()
        if obligation_count != 1:
            raise RuntimeError(f"obligation replay created duplicate effects={obligation_count}")


def _payment_scenario(selected):
    with Session(selected) as session, session.begin():
        tenant, organization, provider, mobile, _cash = _seed_scope(session)
        intent, attempt, processing, succeeded, settlement, confirmed = _payment_fixture(tenant, organization, provider, mobile, 8500, 0)
        TransactionalPaymentIntentEngine.create_intent(session, intent)
        TransactionalPaymentAttemptEngine.create(session, attempt)
        TransactionalPaymentAttemptEngine.transition(session, processing)
        TransactionalPaymentAttemptEngine.transition(session, succeeded)
        TransactionalPaymentSettlementEngine.create(session, settlement)
        TransactionalPaymentSettlementEngine.transition(session, confirmed)


def _install_governed_actor_fixture(selected):
    """Install the minimal legacy identity authority required by M6.3 reopen proof."""
    with selected.begin() as connection:
        connection.execute(text("""INSERT INTO branches(
            id,tenant_id,branch_code,name,city,address,is_active)
            VALUES(:id,:tenant,'M85-APPROVAL','M8.5 Approval Authority','Douala','Disposable rehearsal',true)"""), {
            "id": APPROVER_BRANCH_ID, "tenant": TENANT_ONE,
        })
        connection.execute(text("""INSERT INTO users(
            id,username,password_hash,full_name,role,tenant_id,branch_id,is_active)
            VALUES(:id,'m85-approval-actor','not-a-login-secret','M8.5 Approval Actor','manager',:tenant,:branch,true)"""), {
            "id": APPROVER_USER_ID, "tenant": TENANT_ONE, "branch": APPROVER_BRANCH_ID,
        })


def _cross_milestone(selected):
    _install_fixtures(selected)
    _install_posting_fixtures(selected)
    _install_governed_actor_fixture(selected)
    with Session(selected, expire_on_commit=False) as session, session.begin():
        revenue = AtomicPostedFinancialEventEngine.emit_and_post(session, _revenue_command())
        replay = AtomicPostedFinancialEventEngine.emit_and_post(session, _revenue_command())
        if revenue.journal_entry is None or replay.journal_entry is None or revenue.journal_entry.id != replay.journal_entry.id or not replay.replayed:
            raise RuntimeError("posted replay did not converge")
        _expect("idempotency_conflict", lambda: AtomicPostedFinancialEventEngine.emit_and_post(session, replace(_revenue_command(), amount=Decimal("1001"))))
        settlement = AtomicPostedFinancialEventEngine.emit_and_post(session, _settlement_command())
        reversal = AtomicPostedFinancialEventEngine.emit_and_post(session, _reversal_command(settlement.financial_event_result.event.id))
        if settlement.journal_entry is None or reversal.journal_entry is None:
            raise RuntimeError("settlement or reversal journal missing")
        cross_tenant = replace(
            _event_command(), public_id=UUID("85000000-0000-0000-0000-000000000010"),
            idempotency_key="m85:cross-tenant", source_record_id=SOURCE_OTHER_TENANT,
        )
        _expect("source_record_not_found", lambda: TransactionalCanonicalFinancialEventEngine.emit(session, cross_tenant))
    _obligation_scenario(selected)
    _payment_scenario(selected)
    m64._exercise(selected)

    rollback = replace(_event_command(), public_id=UUID("85000000-0000-0000-0000-000000000020"), idempotency_key="m85:rollback")
    with Session(selected) as session:
        transaction = session.begin()
        TransactionalCanonicalFinancialEventEngine.emit(session, rollback)
        transaction.rollback()
    with selected.begin() as connection:
        connection.execute(text("UPDATE accounting_periods SET period_state='closed', closed_at=now(), row_version=row_version+1 WHERE tenant_id=:tenant AND id=:period"), {"tenant": TENANT_ONE, "period": PERIOD_ID})
    with Session(selected) as session:
        _expect("accounting_period_not_open", lambda: AtomicPostedFinancialEventEngine.emit_and_post(session, _unbound_expense_command("m85:closed-period")))
        session.rollback()

    with selected.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_HEAD:
            raise RuntimeError(f"clean replay revision changed={revision}")
        imbalance = connection.execute(text("SELECT COALESCE(sum(transaction_debit_amount),0)-COALESCE(sum(transaction_credit_amount),0) FROM journal_lines")).scalar_one()
        if imbalance != 0:
            raise RuntimeError(f"aggregate journals unbalanced={imbalance}")
        if connection.execute(text("SELECT count(*) FROM financial_events fe LEFT JOIN journal_entry_event_links link ON link.tenant_id=fe.tenant_id AND link.financial_event_id=fe.id WHERE fe.actor_service='m24-verifier' AND fe.event_type_code IN ('COMMERCIAL_REVENUE_RECOGNIZED','PAYMENT_SETTLED','PAYMENT_SETTLEMENT_REVERSED') AND link.financial_event_id IS NULL")).scalar_one():
            raise RuntimeError("posted canonical event is not traceable to its journal")
        if connection.execute(text("SELECT count(*) FROM financial_obligations WHERE obligation_state<>'satisfied' AND public_id=:public"), {"public": "85000000-0000-0000-0020-000000000001"}).scalar_one():
            raise RuntimeError("allocated obligation balance is inconsistent")
        if connection.execute(text("SELECT count(*) FROM payment_settlements WHERE settlement_state='confirmed'")).scalar_one() < 1:
            raise RuntimeError("confirmed payment settlement missing")
        if connection.execute(text("SELECT count(*) FROM idempotency_records WHERE idempotency_key='m85:rollback'")).scalar_one():
            raise RuntimeError("rolled-back event left idempotency residue")
        if connection.execute(text("SELECT count(*) FROM reconciliation_windows")).scalar_one() < 1 or connection.execute(text("SELECT count(*) FROM reconciliation_controls")).scalar_one() < 1:
            raise RuntimeError("reconciliation composition evidence missing")
        tables = len(set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars()))
    print(f"clean_replay_database={TEST_DATABASE_NAME} revision={revision} public_tables={tables}")
    print("cross_milestone_scenario=PASS events_journals=PASS obligation_allocation=PASS payment_settlement=PASS reversal=PASS reconciliation=PASS closed_period=PASS replay=PASS conflict=PASS tenant_scope=PASS rollback=PASS")


def _clean_replay():
    _create_clean()
    selected = None
    try:
        _migrate("head")
        selected = _engine(TEST_DATABASE_NAME)
        with selected.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != EXPECTED_HEAD:
                raise RuntimeError(f"clean upgrade head differs={revision}")
            for table in EMPTY_TABLES:
                if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                    raise RuntimeError(f"clean migration created financial state={table}")
        _migrate("m63_reconciliation_close_019", downgrade=True)
        _migrate("head")
        _cross_milestone(selected)
        selected.dispose(); selected = None
        _drop(TEST_DATABASE_NAME)
    except Exception:
        if selected is not None:
            selected.dispose()
        print(f"M8.5 clean replay failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print("m85_clean_replay=PASS template=template0 canonical_lineage=PASS empty_install=PASS downgrade_reupgrade=PASS cross_milestone=PASS financial_invariants=PASS dropped=true")


def _selected_adversarial_suites():
    for milestone, relative in SELECTED_SUITES:
        completed = subprocess.run(
            [sys.executable, str(ROOT / relative), "create-and-verify"],
            cwd=ROOT, text=True, capture_output=True, timeout=1200,
        )
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.returncode:
            if completed.stderr:
                print(completed.stderr.rstrip(), file=sys.stderr)
            raise RuntimeError(f"selected adversarial suite failed={milestone}")
        print(f"selected_suite={milestone} result=PASS")


def _run():
    _development()
    _clean_replay()
    _selected_adversarial_suites()
    _development()
    TrackBExitEvidence(
        EXPECTED_HEAD, 12, True, True, True, tuple(item[0] for item in SELECTED_SUITES),
        True, (), "NOT_AUTHORIZED", "NOT_EXECUTED",
    )
    print("m85_track_b_approved_exit=PASS aggregate_conformance=PASS canonical_lineage=PASS clean_replay=PASS financial_invariants=PASS cross_milestone_scenario=PASS replay=PASS conflict=PASS concurrency=PASS ordering=PASS offline=PASS provider_failure=PASS uncertainty=PASS rollback=PASS backup_restore=PASS recovery=PASS pack_conformance=PASS hidden_writers=NONE tenant_scope=PASS organization_scope=PASS permissions=PASS approvals=PASS M7_frozen=PASS development_empty=PASS cutover=NOT_AUTHORIZED writer_retirement=NOT_EXECUTED schema_neutral=PASS migration=NONE disposable_cleanup=PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "create-and-verify", "drop"))
    parser.add_argument("--confirm-database-name")
    args = parser.parse_args()
    if args.command == "verify":
        _development()
    elif args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "create-and-verify":
        _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
