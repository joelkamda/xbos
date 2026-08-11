from __future__ import annotations

import argparse
import os
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine as application_engine
from core.domain.finance.operational_balance_contract import (
    CreateOperationalAccountCommand, RecordActualBalanceCommand, RecordBalanceAnchorCommand,
)
from core.domain.finance.operational_balance_engine import TransactionalOperationalBalanceEngine
from core.domain.finance.operational_transfer_contract import RecordOperationalTransferCommand
from core.domain.finance.operational_transfer_engine import TransactionalOperationalTransferEngine
from core.domain.finance.reconciliation_window_contract import (
    CascadeReconciliationWindowsCommand, CreateReconciliationCalendarPolicyCommand,
    CreateReconciliationSeriesCommand, RecordReconciliationWindowCommand, ShiftDefinition,
)
from core.domain.finance.reconciliation_window_engine import TransactionalReconciliationWindowEngine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m62_reconciliation_test"
PARENT_REVISION = "m61_transfers_reconciliation_017"
TARGET_REVISION = "m62_reconciliation_windows_018"
BASE = datetime(2026, 8, 10, 7, tzinfo=timezone.utc)
CORRELATION = UUID("62000000-0000-0000-0000-000000000099")
POLICY_PUBLIC = UUID("62000000-0000-0000-0000-000000000001")
SOURCE_ACCOUNT = UUID("62000000-0000-0000-0000-000000000002")
DESTINATION_ACCOUNT = UUID("62000000-0000-0000-0000-000000000003")
SERIES_PUBLIC = UUID("62000000-0000-0000-0000-000000000004")
TRANSFER_PUBLIC = UUID("62000000-0000-0000-0000-000000000005")
M62_TABLES = (
    "reconciliation_calendar_policies", "reconciliation_series", "reconciliation_windows",
    "reconciliation_cascade_runs", "reconciliation_window_revisions",
)
FINANCIAL_EMPTY_TABLES = (
    "idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
    "operational_account_authorities", "operational_account_balance_anchors", "operational_account_balance_observations",
)


def _url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _engine(name, isolation_level=None): return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


def _exists(name):
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally:
        selected.dispose()


def _create_clone():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally:
        selected.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        selected.dispose()


@contextmanager
def _migration_database(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous


def _migrate(name, revision, *, downgrade=False):
    with _migration_database(name):
        action = alembic_command.downgrade if downgrade else alembic_command.upgrade
        action(Config(str(ROOT / "alembic.ini")), revision)


def _revision(connection): return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}:
            raise RuntimeError(f"unexpected development revision={revision}")
        view_exists = bool(connection.execute(text("SELECT 1 FROM pg_views WHERE schemaname='public' AND viewname='current_reconciliation_window_revisions'")).scalar_one_or_none())
        if view_exists != (revision == TARGET_REVISION):
            raise RuntimeError("M6.2 current-revision view does not match development revision")
        for table_name in FINANCIAL_EMPTY_TABLES:
            if connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one():
                raise RuntimeError(f"development financial table is not empty={table_name}")
        if revision == TARGET_REVISION:
            for table_name in M62_TABLES:
                if connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one():
                    raise RuntimeError(f"development M6.2 table is not empty={table_name}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m62_reconciliation_windows_development=PASS")


def _status():
    exists = _exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _account(tenant, org, public_id, code, key):
    return CreateOperationalAccountCommand(
        public_id=public_id, tenant_id=tenant, organization_unit_id=org, account_class="treasury",
        account_type="cash", code=code, display_name=code.replace("-", " ").title(), currency_code="XAF",
        aggregation_role="leaf", opened_at=BASE-timedelta(days=1), correlation_id=CORRELATION,
        source_component="m62.verifier", source_record_id=key, idempotency_scope="m62.account",
        idempotency_key=key, actor_service="m62.verifier",
    )


def _anchor(tenant, org, account_public, number):
    return RecordBalanceAnchorCommand(
        public_id=UUID(f"62000000-0000-0000-0003-{number:012d}"), tenant_id=tenant,
        organization_unit_id=org, operational_account_public_id=account_public, anchor_balance="100",
        currency_code="XAF", anchor_at=BASE, provenance="opening_import",
        evidence_payload={"opening": str(account_public)}, occurred_at=BASE, business_date=date(2026,8,10),
        calendar_policy_version=1, correlation_id=CORRELATION, source_component="m62.verifier",
        source_record_id=f"anchor-{number}", idempotency_scope="m62.anchor", idempotency_key=f"anchor-{number}",
        actor_service="m62.verifier",
    )


def _actual(tenant, org, account_public, number, observed_at):
    return RecordActualBalanceCommand(
        public_id=UUID(f"62000000-0000-0000-0004-{number:012d}"), tenant_id=tenant,
        organization_unit_id=org, operational_account_public_id=account_public, actual_balance="100",
        currency_code="XAF", observed_at=observed_at, provenance="operator_counted",
        evidence_payload={"count_sheet": f"count-{number}"}, occurred_at=observed_at,
        business_date=date(2026,8,10), calendar_policy_version=1, correlation_id=CORRELATION,
        source_component="m62.verifier", source_record_id=f"actual-{number}", idempotency_scope="m62.actual",
        idempotency_key=f"actual-{number}", actor_service="m62.verifier",
    )


def _policy(tenant, org):
    return CreateReconciliationCalendarPolicyCommand(
        public_id=POLICY_PUBLIC, tenant_id=tenant, organization_unit_id=org, policy_code="neutral-shift-calendar",
        policy_version=1, timezone_name="Africa/Douala", business_day_boundary="08:00",
        shifts=(ShiftDefinition("day", "08:00"), ShiftDefinition("night", "18:00")),
        effective_from=BASE-timedelta(days=1), occurred_at=BASE, business_date=date(2026,8,10),
        calendar_policy_version=1, correlation_id=CORRELATION, source_component="m62.verifier",
        source_record_id="policy", idempotency_scope="m62.policy", idempotency_key="policy",
        actor_service="m62.verifier",
    )


def _series(tenant, org):
    return CreateReconciliationSeriesCommand(
        public_id=SERIES_PUBLIC, tenant_id=tenant, organization_unit_id=org,
        operational_account_public_id=SOURCE_ACCOUNT, calendar_policy_public_id=POLICY_PUBLIC,
        series_code="source-shifts", currency_code="XAF", starts_at=BASE, occurred_at=BASE,
        business_date=date(2026,8,10), calendar_policy_version=1, correlation_id=CORRELATION,
        source_component="m62.verifier", source_record_id="series", idempotency_scope="m62.series",
        idempotency_key="series", actor_service="m62.verifier",
    )


def _window(tenant, org, number, start, end):
    return RecordReconciliationWindowCommand(
        public_id=UUID(f"62000000-0000-0000-0005-{number:012d}"), tenant_id=tenant,
        organization_unit_id=org, reconciliation_series_public_id=SERIES_PUBLIC,
        window_start=start, window_end=end, evidence_payload={"count_sheet": f"window-{number}"},
        occurred_at=end, business_date=date(2026,8,10), calendar_policy_version=1,
        correlation_id=CORRELATION, source_component="m62.verifier", source_record_id=f"window-{number}",
        idempotency_scope="m62.window", idempotency_key=f"window-{number}", actor_service="m62.verifier",
    )


def _cascade(tenant, org):
    return CascadeReconciliationWindowsCommand(
        public_id=UUID("62000000-0000-0000-0006-000000000001"), tenant_id=tenant,
        organization_unit_id=org, reconciliation_series_public_id=SERIES_PUBLIC,
        changed_from_at=BASE+timedelta(hours=2), cascade_reason="financial_fact_appended",
        evidence_payload={"late_transfer": str(TRANSFER_PUBLIC)}, occurred_at=BASE+timedelta(days=1,hours=1),
        business_date=date(2026,8,11), calendar_policy_version=1, correlation_id=CORRELATION,
        causation_id=TRANSFER_PUBLIC, source_component="m62.verifier", source_record_id="cascade",
        idempotency_scope="m62.cascade", idempotency_key="cascade", actor_service="m62.verifier",
    )


def _expect(code, action):
    try: action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected error={code}, found={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error was not raised={code}")


def _seed(session):
    tenant = int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
    org = session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:tenant ORDER BY id LIMIT 1"), {"tenant": tenant}).scalar_one_or_none()
    if org is None:
        org = session.execute(text("INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active) VALUES(:tenant,'branch','m62-verifier','M6.2 Verifier','Africa/Douala',true) RETURNING id"), {"tenant": tenant}).scalar_one()
    org = int(org)
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    session.execute(text("""INSERT INTO tenant_currency_policies(tenant_id,currency_code,rounding_mode,cash_rounding_increment,active,effective_from,policy_version)
        VALUES(:tenant,'XAF','half_even',0,true,:effective,62) ON CONFLICT(tenant_id,currency_code,policy_version) DO UPDATE SET active=true"""), {
        "tenant": tenant, "effective": BASE-timedelta(days=1),
    })
    source = TransactionalOperationalBalanceEngine.create_account(session, _account(tenant, org, SOURCE_ACCOUNT, "m62-source", "source"))
    destination = TransactionalOperationalBalanceEngine.create_account(session, _account(tenant, org, DESTINATION_ACCOUNT, "m62-destination", "destination"))
    TransactionalOperationalBalanceEngine.record_anchor(session, _anchor(tenant, org, source.public_id, 1))
    TransactionalOperationalBalanceEngine.record_anchor(session, _anchor(tenant, org, destination.public_id, 2))
    TransactionalOperationalBalanceEngine.record_actual(session, _actual(tenant, org, source.public_id, 1, BASE+timedelta(hours=9,minutes=30)))
    TransactionalOperationalBalanceEngine.record_actual(session, _actual(tenant, org, source.public_id, 2, BASE+timedelta(hours=23,minutes=30)))
    TransactionalReconciliationWindowEngine.create_calendar_policy(session, _policy(tenant, org))
    TransactionalReconciliationWindowEngine.create_series(session, _series(tenant, org))
    return tenant, org, source, destination


def _seed_transfer_posting(session, tenant, org, source, destination):
    session.execute(text("""INSERT INTO accounting_periods(tenant_id,legal_entity_unit_id,period_code,period_start,period_end,period_state)
        VALUES(:tenant,:org,'2026-08','2026-08-01','2026-08-31','open') ON CONFLICT(tenant_id,legal_entity_unit_id,period_code) DO NOTHING"""), {
        "tenant": tenant, "org": org,
    })
    for number, (role, operational_id) in enumerate((("source_operational_asset", source.id), ("target_operational_asset", destination.id)), 1):
        ledger = session.execute(text("""INSERT INTO ledger_accounts(public_id,tenant_id,legal_entity_unit_id,account_code,account_name,account_type,normal_balance,currency_policy,fixed_currency_code,active,effective_from)
            VALUES(:public,:tenant,:org,:code,:name,'asset','debit','fixed','XAF',true,'2026-01-01') RETURNING id"""), {
            "public": f"62000000-0000-0000-0007-{number:012d}", "tenant": tenant, "org": org,
            "code": f"m62-{number}", "name": role,
        }).scalar_one()
        session.execute(text("""INSERT INTO ledger_account_role_bindings(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,ledger_account_id,operational_account_id,effective_from,active)
            VALUES(:tenant,:org,:role,'default','XAF',:ledger,:operational,'2026-01-01',true)"""), {
            "tenant": tenant, "org": org, "role": role, "ledger": ledger, "operational": operational_id,
        })
    source_record = int(session.execute(text("""INSERT INTO kernel_source_records(tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,source_occurred_at)
        VALUES(:tenant,:org,'m62.verifier','value_transfer','late-transfer',:at) RETURNING id"""), {
        "tenant": tenant, "org": org, "at": BASE+timedelta(hours=2),
    }).scalar_one())
    TransactionalOperationalTransferEngine.record(session, RecordOperationalTransferCommand(
        public_id=TRANSFER_PUBLIC, tenant_id=tenant, organization_unit_id=org,
        source_operational_account_public_id=SOURCE_ACCOUNT, destination_operational_account_public_id=DESTINATION_ACCOUNT,
        amount="10", currency_code="XAF", occurred_at=BASE+timedelta(hours=2), value_at=BASE+timedelta(hours=2),
        business_date=date(2026,8,10), calendar_policy_version=1, provenance="operator_authorized",
        transfer_purpose="treasury_sweep", evidence_payload={"authorization": "late-approved"},
        source_record_id=source_record, idempotency_scope="m62.transfer", idempotency_key="late-transfer",
        correlation_id=CORRELATION, actor_service="m62.verifier",
    ))


def _exercise(selected_engine):
    with Session(selected_engine) as session, session.begin():
        tenant, org, source, destination = _seed(session)
        first_command = _window(tenant, org, 1, BASE, BASE+timedelta(hours=10))
        first = TransactionalReconciliationWindowEngine.record_window(session, first_command)
        replay = TransactionalReconciliationWindowEngine.record_window(session, first_command)
        if not replay.window.replayed or replay.window.id != first.window.id:
            raise RuntimeError("window replay did not return the accepted window")
        _expect("idempotency_conflict", lambda: TransactionalReconciliationWindowEngine.record_window(
            session, replace(first_command, evidence_payload={"count_sheet": "changed"})
        ))
        second = TransactionalReconciliationWindowEngine.record_window(
            session, _window(tenant, org, 2, BASE+timedelta(hours=10), BASE+timedelta(days=1))
        )
        _expect("window_continuity_violation", lambda: TransactionalReconciliationWindowEngine.record_window(
            session, _window(tenant, org, 3, BASE+timedelta(days=1,hours=10), BASE+timedelta(days=2))
        ))
        _expect("series_not_found", lambda: TransactionalReconciliationWindowEngine.record_window(
            session, replace(_window(tenant, org, 4, BASE+timedelta(days=1), BASE+timedelta(days=1,hours=10)),
                            tenant_id=tenant+100000, idempotency_key="cross-tenant")
        ))
        if first.revision.closing_expected != Decimal("100") or second.revision.opening_expected != Decimal("100"):
            raise RuntimeError("initial M6.0 window projection is incorrect")
        _seed_transfer_posting(session, tenant, org, source, destination)
        cascade_command = _cascade(tenant, org)
        cascade = TransactionalReconciliationWindowEngine.cascade(session, cascade_command)
        cascade_replay = TransactionalReconciliationWindowEngine.cascade(session, cascade_command)
        if cascade_replay.revision_ids != cascade.revision_ids or len(cascade.revision_ids) != 2:
            raise RuntimeError("cascade replay or forward propagation failed")
        _expect("idempotency_conflict", lambda: TransactionalReconciliationWindowEngine.cascade(
            session, replace(cascade_command, cascade_reason="authorized_recalculation")
        ))
        current = session.execute(text("""SELECT window_start,revision_number,opening_expected,closing_expected,
            actual_closing,variance,readiness_condition FROM current_reconciliation_window_revisions
            ORDER BY window_start""")).mappings().all()
        if len(current) != 2 or [row["revision_number"] for row in current] != [2,2]:
            raise RuntimeError(f"unexpected current revisions={current}")
        if (Decimal(current[0]["opening_expected"]) != Decimal("100") or Decimal(current[0]["closing_expected"]) != Decimal("90")
                or Decimal(current[1]["opening_expected"]) != Decimal("90") or Decimal(current[1]["closing_expected"]) != Decimal("90")):
            raise RuntimeError(f"correction did not cascade through successors={current}")
        if any(Decimal(row["actual_closing"]) != Decimal("100") or Decimal(row["variance"]) != Decimal("10") for row in current):
            raise RuntimeError("later actual counts were lost during cascade")
        try:
            with session.begin_nested():
                session.execute(text("UPDATE reconciliation_windows SET shift_code='rewritten' WHERE id=:id"), {"id": first.window.id})
        except DBAPIError:
            pass
        else:
            raise RuntimeError("accepted reconciliation window mutation was allowed")

    with selected_engine.connect() as connection:
        counts = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in M62_TABLES}
        expected = {
            "reconciliation_calendar_policies": 1, "reconciliation_series": 1, "reconciliation_windows": 2,
            "reconciliation_cascade_runs": 1, "reconciliation_window_revisions": 4,
        }
        if counts != expected:
            raise RuntimeError(f"unexpected M6.2 counts={counts}")
        history = connection.execute(text("SELECT count(*) FROM reconciliation_window_revisions WHERE revision_number=1")).scalar_one()
        if history != 2:
            raise RuntimeError("cascade rewrote initial window history")
        before = counts["reconciliation_windows"]
    with Session(selected_engine) as session:
        transaction = session.begin()
        tenant = int(session.execute(text("SELECT tenant_id FROM reconciliation_series WHERE public_id=:public"), {"public": str(SERIES_PUBLIC)}).scalar_one())
        org = int(session.execute(text("SELECT organization_unit_id FROM reconciliation_series WHERE public_id=:public"), {"public": str(SERIES_PUBLIC)}).scalar_one())
        TransactionalReconciliationWindowEngine.record_window(
            session, _window(tenant, org, 9, BASE+timedelta(days=1), BASE+timedelta(days=1,hours=10))
        )
        session.flush(); transaction.rollback()
    with selected_engine.connect() as connection:
        if connection.execute(text("SELECT count(*) FROM reconciliation_windows")).scalar_one() != before:
            raise RuntimeError("outer rollback leaked reconciliation window")


def _run():
    _verify_development(); _create_clone(); selected = None
    try:
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        selected = _engine(TEST_DATABASE_NAME)
        with selected.connect() as connection:
            if _revision(connection) != TARGET_REVISION: raise RuntimeError("disposable database did not reach M6.2")
        selected.dispose(); selected = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        selected = _engine(TEST_DATABASE_NAME); _exercise(selected); selected.dispose(); selected = None
        _drop(TEST_DATABASE_NAME); _verify_development()
        print(f"m62_reconciliation_windows=PASS database={TEST_DATABASE_NAME} calendar=PASS shift_attribution=PASS continuity=PASS no_skip=PASS expected_balance=PASS actual_provenance=PASS cascade=PASS historical_revisions=PASS replay=PASS conflict=PASS tenant_scope=PASS immutability=PASS rollback=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if selected is not None: selected.dispose()
        print(f"M6.2 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status"); sub.add_parser("verify"); sub.add_parser("create-and-verify")
    drop = sub.add_parser("drop"); drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()
    if args.command == "status": return 0 if _status() else 1
    if args.command == "verify": _verify_development()
    elif args.command == "create-and-verify": _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME: raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
