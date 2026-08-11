from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.operational_balance_engine import TransactionalOperationalBalanceEngine
from core.domain.finance.reconciliation_close_contract import (
    CloseReconciliationWindowCommand,
    ReopenReconciliationWindowCommand,
)
from core.domain.finance.reconciliation_close_engine import TransactionalReconciliationCloseEngine
from core.domain.finance.reconciliation_window_engine import TransactionalReconciliationWindowEngine
from scripts import verify_m62_reconciliation_windows as m62

DEVELOPMENT_DATABASE_NAME = m62.DEVELOPMENT_DATABASE_NAME
TEST_DATABASE_NAME = "xbos_track_b_m63_close_test"
PARENT_REVISION = "m62_reconciliation_windows_018"
TARGET_REVISION = "m63_reconciliation_close_019"
BASE = m62.BASE
CORRELATION = UUID("63000000-0000-0000-0000-000000000099")


def _url(): return m62._url()
def _engine(name, isolation_level=None): return m62._engine(name, isolation_level)
def _exists(name): return m62._exists(name)
def _revision(connection): return m62._revision(connection)


def _create_clone():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    m62.application_engine.dispose()
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


def _migrate(name, revision, *, downgrade=False):
    with m62._migration_database(name):
        action = m62.alembic_command.downgrade if downgrade else m62.alembic_command.upgrade
        action(m62.Config(str(m62.ROOT / "alembic.ini")), revision)


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with m62.application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}:
            raise RuntimeError(f"unexpected development revision={revision}")
        table_exists = bool(connection.execute(text("SELECT to_regclass('public.reconciliation_window_governance_events')")).scalar_one())
        view_exists = bool(connection.execute(text("SELECT 1 FROM pg_views WHERE schemaname='public' AND viewname='current_reconciliation_window_governance'")).scalar_one_or_none())
        expected = revision == TARGET_REVISION
        if table_exists != expected or view_exists != expected:
            raise RuntimeError("M6.3 authority does not match development revision")
        if expected and connection.execute(text("SELECT count(*) FROM reconciliation_window_governance_events")).scalar_one():
            raise RuntimeError("development M6.3 governance table is not empty")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m63_reconciliation_close_development=PASS")


def _status():
    exists = _exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _close(tenant, org, window_public, revision, business_date, number):
    return CloseReconciliationWindowCommand(
        public_id=UUID(f"63000000-0000-0000-0001-{number:012d}"), tenant_id=tenant,
        organization_unit_id=org, reconciliation_window_public_id=window_public,
        governed_revision_number=revision, accounting_period_code="2026-08",
        close_disposition="explained_variance", transition_reason="variance_explained",
        evidence_payload={"review": f"close-{number}", "variance": "approved"},
        occurred_at=BASE+timedelta(days=1,hours=2,minutes=number), business_date=business_date,
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m63.verifier",
        source_component="m63.verifier", source_record_id=f"close-{number}",
        idempotency_scope="m63.close", idempotency_key=f"close-{number}",
    )


def _reopen(tenant, org, window_public, revision, prior_close, approver):
    return ReopenReconciliationWindowCommand(
        public_id=UUID("63000000-0000-0000-0002-000000000001"), tenant_id=tenant,
        organization_unit_id=org, reconciliation_window_public_id=window_public,
        governed_revision_number=revision, accounting_period_code="2026-08",
        prior_close_public_id=prior_close, transition_reason="approved_late_count",
        evidence_payload={"approval": "signed", "late_count": "verified"},
        approved_by_user_id=approver, approved_at=BASE+timedelta(days=1,hours=2,minutes=10),
        occurred_at=BASE+timedelta(days=1,hours=2,minutes=11), business_date=date(2026,8,10),
        calendar_policy_version=1, correlation_id=CORRELATION, actor_service="m63.verifier",
        source_component="m63.verifier", source_record_id="reopen-1",
        idempotency_scope="m63.reopen", idempotency_key="reopen-1",
    )


def _expect(code, action):
    try:
        action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected error={code}, found={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error was not raised={code}")


def _exercise(selected_engine):
    m62._exercise(selected_engine)
    with Session(selected_engine) as session, session.begin():
        rows = session.execute(text("""SELECT w.id,w.public_id,w.organization_unit_id,w.business_date,r.revision_number
            FROM reconciliation_windows w JOIN current_reconciliation_window_revisions r
              ON r.tenant_id=w.tenant_id AND r.reconciliation_window_id=w.id
            ORDER BY w.window_start""")).mappings().all()
        if len(rows) != 2:
            raise RuntimeError("M6.2 window authority was not established")
        tenant = int(session.execute(text("SELECT tenant_id FROM reconciliation_windows WHERE id=:id"), {"id": rows[0]["id"]}).scalar_one())
        org = int(rows[0]["organization_unit_id"])
        approver = session.execute(text("SELECT id FROM users WHERE tenant_id=:tenant ORDER BY id LIMIT 1"), {"tenant": tenant}).scalar_one_or_none()
        if approver is None:
            raise RuntimeError("disposable baseline requires one tenant user for governed reopen approval")
        first_command = _close(tenant, org, UUID(str(rows[0]["public_id"])), int(rows[0]["revision_number"]), rows[0]["business_date"], 1)
        second_command = _close(tenant, org, UUID(str(rows[1]["public_id"])), int(rows[1]["revision_number"]), rows[1]["business_date"], 2)
        _expect("predecessor_not_closed", lambda: TransactionalReconciliationCloseEngine.close(session, second_command))
        first_close = TransactionalReconciliationCloseEngine.close(session, first_command)
        replay = TransactionalReconciliationCloseEngine.close(session, first_command)
        if not replay.replayed or replay.id != first_close.id:
            raise RuntimeError("close replay did not return accepted transition")
        _expect("idempotency_conflict", lambda: TransactionalReconciliationCloseEngine.close(
            session, replace(first_command, evidence_payload={"review": "conflicting"})
        ))
        _expect("window_not_found", lambda: TransactionalReconciliationCloseEngine.close(
            session, replace(second_command, tenant_id=tenant+100000, idempotency_key="cross-tenant")
        ))
        protected_actual = replace(
            m62._actual(tenant, org, m62.SOURCE_ACCOUNT, 9, m62.BASE+timedelta(hours=9,minutes=45)),
            actual_balance="95", source_component="m63.verifier", idempotency_scope="m63.actual",
            idempotency_key="late-count", source_record_id="late-count",
        )
        try:
            with session.begin_nested():
                TransactionalOperationalBalanceEngine.record_actual(session, protected_actual)
        except DBAPIError:
            pass
        else:
            raise RuntimeError("closed window accepted a new actual-balance fact")
        cascade = replace(
            m62._cascade(tenant, org), public_id=UUID("63000000-0000-0000-0003-000000000001"),
            cascade_reason="balance_observation_appended", evidence_payload={"late_count": "verified"},
            source_component="m63.verifier", source_record_id="m63-cascade",
            idempotency_scope="m63.cascade", idempotency_key="m63-cascade", causation_id=None,
        )
        try:
            with session.begin_nested():
                TransactionalReconciliationWindowEngine.cascade(session, cascade)
        except DBAPIError:
            pass
        else:
            raise RuntimeError("closed window accepted an intersecting correction cascade")
        period_id = int(session.execute(text("SELECT accounting_period_id FROM reconciliation_window_governance_events WHERE id=:id"), {"id": first_close.id}).scalar_one())
        session.execute(text("UPDATE accounting_periods SET period_state='closed',closed_at=:at WHERE id=:id"), {"at": BASE+timedelta(days=1,hours=2), "id": period_id})
        reopen_command = _reopen(tenant, org, UUID(str(rows[0]["public_id"])), int(rows[0]["revision_number"]), first_close.public_id, int(approver))
        _expect("accounting_period_not_open", lambda: TransactionalReconciliationCloseEngine.reopen(session, reopen_command))
        session.execute(text("UPDATE accounting_periods SET period_state='reopened',reopened_by_user_id=:user,reopened_at=:at WHERE id=:id"), {
            "user": int(approver), "at": BASE+timedelta(days=1,hours=2,minutes=5), "id": period_id,
        })
        reopened = TransactionalReconciliationCloseEngine.reopen(session, reopen_command)
        if reopened.prior_event_id != first_close.id or reopened.approved_by_user_id != int(approver):
            raise RuntimeError("reopen did not preserve close linkage and approval")
        TransactionalOperationalBalanceEngine.record_actual(session, protected_actual)
        cascade_result = TransactionalReconciliationWindowEngine.cascade(session, cascade)
        if not cascade_result.revision_ids:
            raise RuntimeError("reopened window did not admit correction cascade")
        current_revision = int(session.execute(text("SELECT revision_number FROM current_reconciliation_window_revisions WHERE reconciliation_window_id=:id"), {"id": rows[0]["id"]}).scalar_one())
        reclose = replace(
            first_command, public_id=UUID("63000000-0000-0000-0001-000000000003"),
            governed_revision_number=current_revision, transition_reason="late_count_reconciled",
            evidence_payload={"review": "reclose", "variance": "approved"},
            source_record_id="close-3", idempotency_key="close-3",
        )
        TransactionalReconciliationCloseEngine.close(session, reclose)
        TransactionalReconciliationCloseEngine.close(session, second_command)
        try:
            with session.begin_nested():
                session.execute(text("UPDATE reconciliation_window_governance_events SET transition_reason='rewritten' WHERE id=:id"), {"id": first_close.id})
        except DBAPIError:
            pass
        else:
            raise RuntimeError("accepted close history was mutable")
    with selected_engine.connect() as connection:
        events = connection.execute(text("SELECT count(*) FROM reconciliation_window_governance_events")).scalar_one()
        closed = connection.execute(text("SELECT count(*) FROM current_reconciliation_window_governance WHERE governance_state='closed'")).scalar_one()
        reopened_history = connection.execute(text("SELECT count(*) FROM reconciliation_window_governance_events WHERE transition_type='reopen' AND approved_by_user_id IS NOT NULL")).scalar_one()
        if events != 4 or closed != 2 or reopened_history != 1:
            raise RuntimeError(f"unexpected governance history events={events} closed={closed} reopens={reopened_history}")


def _run():
    _verify_development(); _create_clone(); selected = None
    try:
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        selected = _engine(TEST_DATABASE_NAME)
        with selected.connect() as connection:
            if _revision(connection) != TARGET_REVISION: raise RuntimeError("disposable database did not reach M6.3")
        selected.dispose(); selected = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        selected = _engine(TEST_DATABASE_NAME); _exercise(selected); selected.dispose(); selected = None
        _drop(TEST_DATABASE_NAME); _verify_development()
        print(f"m63_reconciliation_close=PASS database={TEST_DATABASE_NAME} close=PASS predecessor=PASS protection=PASS reopen=PASS period_coordination=PASS history=PASS replay=PASS conflict=PASS tenant_scope=PASS immutability=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if selected is not None: selected.dispose()
        print(f"M6.3 verification failed; retained disposable database={TEST_DATABASE_NAME}")
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
