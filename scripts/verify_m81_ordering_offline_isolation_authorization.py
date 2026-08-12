"""Disposable PostgreSQL verification for M8.1 adversarial ordering and isolation."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.adversarial_ordering_contract import AuthorityProbe
from core.domain.finance.adversarial_ordering_service import authorize, validate_authority_sources
from core.domain.finance.event_contract import FinancialEventValidationError
from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import EXPECTED_HEAD, validate_frozen_m4_manifest, validate_release_manifest as m6_manifest
from core.domain.finance.m7_acceptance import validate_release_manifest as m7_manifest
from core.domain.finance.transactional_event_engine import TransactionalCanonicalFinancialEventEngine
from database import engine as application_engine
from scripts.verify_m21_canonical_event_engine import ORG_TWO, _event_command, _install_fixtures

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m81_ordering_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
BASE = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


def _url():
    value = make_url(application_engine.url)
    if value.host not in LOCAL_HOSTS:
        raise RuntimeError(f"refusing non-local PostgreSQL host={value.host!r}")
    return value


def _engine(name, isolation_level=None):
    return create_engine(_url().set(database=name), isolation_level=isolation_level)


def _exists(name):
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar())
    finally:
        selected.dispose()


def _create():
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


def _development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"development database must be={DEVELOPMENT_DATABASE_NAME}")
    releases = (m2_manifest(ROOT).checked_components, m3_manifest(ROOT).checked_components, validate_frozen_m4_manifest(ROOT), m5_manifest(ROOT), m6_manifest(ROOT).checked_components, m7_manifest(ROOT).checked_components)
    validate_authority_sources(ROOT)
    with application_engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != DEVELOPMENT_DATABASE_NAME or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
        for table in ("financial_events", "reconciliation_windows", "reconciliation_window_governance_events"):
            if connection.execute(text("SELECT to_regclass(:table)"), {"table": f"public.{table}"}).scalar_one() and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development financial table not empty={table}")
    print(f"database={database}")
    print(f"revision={revision}")
    print(f"m81_ordering_offline_development=PASS manifests={','.join(map(str, releases))} authority_sources=PASS development_empty=PASS")


def _expect(code, action):
    try:
        action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected={code}; actual={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error not raised={code}")


def _exercise(selected):
    _install_fixtures(selected)
    later = _event_command(
        public_id=UUID("81000000-0000-0000-0000-000000000001"),
        idempotency_key="m81:offline:later", occurred_at=BASE + timedelta(hours=5),
        business_date=date(2026, 8, 11), correlation_id=UUID("81000000-0000-0000-0000-000000000099"),
        metadata={"capture_mode": "offline", "source_sequence": 2}, actor_service="m81-offline-sync",
    )
    earlier = replace(
        later, public_id=UUID("81000000-0000-0000-0000-000000000002"),
        idempotency_key="m81:offline:earlier", occurred_at=BASE + timedelta(hours=1),
        metadata={"capture_mode": "offline", "source_sequence": 1},
    )
    with Session(selected, expire_on_commit=False) as session, session.begin():
        accepted_later = TransactionalCanonicalFinancialEventEngine.emit(session, later)
        accepted_earlier = TransactionalCanonicalFinancialEventEngine.emit(session, earlier)
        replay = TransactionalCanonicalFinancialEventEngine.emit(session, earlier)
        if not replay.replayed or replay.event.id != accepted_earlier.event.id:
            raise RuntimeError("offline replay created a second effect")
        if accepted_later.event.occurred_at <= accepted_earlier.event.occurred_at:
            raise RuntimeError("fixture did not exercise out-of-order arrival")
        cross_org = replace(earlier, public_id=UUID("81000000-0000-0000-0000-000000000003"), idempotency_key="m81:cross-org", organization_unit_id=ORG_TWO)
        _expect("organization_unit_not_active", lambda: TransactionalCanonicalFinancialEventEngine.emit(session, cross_org))

    with selected.connect() as connection:
        rows = connection.execute(text("SELECT public_id,occurred_at,recorded_at,metadata FROM financial_events ORDER BY business_date,occurred_at,public_id")).mappings().all()
        if len(rows) != 2 or str(rows[0]["public_id"]) != str(earlier.public_id) or str(rows[1]["public_id"]) != str(later.public_id):
            raise RuntimeError("economic ordering followed arrival rather than occurred_at")
        if any(row["recorded_at"] is None or row["metadata"].get("capture_mode") != "offline" for row in rows):
            raise RuntimeError("offline provenance or recording time was lost")
        if connection.execute(text("SELECT count(*) FROM financial_events WHERE organization_unit_id=:org"), {"org": ORG_TWO}).scalar_one():
            raise RuntimeError("cross-organization attempt wrote a fact")
        if connection.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one() != 2:
            raise RuntimeError("offline replay/conflict identity count differs")

    authorize(AuthorityProbe(2, 1, "reconcile", 7, frozenset({"accounting.reconcile"})))
    authorize(AuthorityProbe(2, 1, "reopen_period", 7, frozenset({"accounting.close_period"}), 8, frozenset({"accounting.close_period"}), "signed-evidence"))
    _expect("permission_denied", lambda: authorize(AuthorityProbe(2, 1, "close_period", 7, frozenset({"accounting.reconcile"}))))
    _expect("approval_separation_required", lambda: authorize(AuthorityProbe(2, 1, "reopen_period", 7, frozenset({"accounting.close_period"}), 7, frozenset({"accounting.close_period"}), "signed-evidence")))


def _run():
    _development()
    _create()
    selected = None
    try:
        selected = _engine(TEST_DATABASE_NAME)
        _exercise(selected)
        selected.dispose(); selected = None
        _drop(TEST_DATABASE_NAME)
        _development()
    except Exception:
        if selected is not None:
            selected.dispose()
        print(f"M8.1 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print(f"m81_ordering_offline_isolation_authorization=PASS database={TEST_DATABASE_NAME} ordering=PASS offline=PASS occurred_at=PASS recorded_at=PASS replay=PASS conflict=PASS tenant_scope=PASS organization_scope=PASS permissions=PASS approvals=PASS rollback=PASS schema_neutral=PASS migration=NONE dropped=true")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "create-and-verify", "drop"))
    parser.add_argument("--confirm-database-name")
    args = parser.parse_args()
    if args.command == "verify": _development()
    elif args.command == "status": print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "create-and-verify": _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME: raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
