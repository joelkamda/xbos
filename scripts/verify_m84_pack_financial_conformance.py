"""Disposable PostgreSQL verification for reusable M8.4 pack conformance."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.adversarial_ordering_contract import AuthorityProbe
from core.domain.finance.adversarial_ordering_service import authorize
from core.domain.finance.event_contract import FinancialEventIdempotencyConflict
from core.domain.finance.legacy_authority_inventory import verify_no_writer_rerouting
from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import EXPECTED_HEAD, validate_frozen_m4_manifest, validate_release_manifest as m6_manifest
from core.domain.finance.m7_acceptance import validate_authority_boundaries, validate_release_manifest as m7_manifest
from core.domain.finance.pack_conformance_contract import assert_profile_replay
from core.domain.finance.pack_conformance_service import evaluate_pack, find_hidden_financial_writers, validate_generic_harness_neutrality
from core.domain.finance.transactional_event_engine import TransactionalCanonicalFinancialEventEngine
from core.domain.finance.wnd_financial_mapping_contract import WndFinancialMappingError
from core.domain.finance.wnd_financial_mapping_service import WndFinancialMappingService
from core.domain.finance.wnd_pack_conformance_profile import build_wnd_conformance_profile, commercial_sale_envelope, first_canonical_plan
from database import engine as application_engine
from scripts.verify_m21_canonical_event_engine import ORG_TWO, _event_command, _install_fixtures

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m84_pack_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
EMPTY_TABLES = (
    "idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
    "financial_obligations", "value_sources", "payment_allocations", "allocation_reversals",
    "payment_settlements", "reconciliation_windows", "reconciliation_controls",
)
PACK_PATHS = (
    "core/domain/finance/wnd_financial_mapping_service.py",
    "core/domain/finance/wnd_inventory_document_service.py",
    "core/domain/finance/wnd_shadow_rehearsal_service.py",
    "core/domain/finance/wnd_cutover_support_service.py",
    "core/domain/finance/wnd_pack_conformance_profile.py",
)


def _url():
    value = make_url(application_engine.url)
    if value.host not in LOCAL_HOSTS:
        raise RuntimeError(f"refusing non-local PostgreSQL host={value.host!r}")
    return value


def _engine(name, isolation_level=None):
    return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


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


def _static_conformance():
    validate_generic_harness_neutrality(ROOT)
    validate_authority_boundaries(ROOT)
    verify_no_writer_rerouting(ROOT)
    hidden = find_hidden_financial_writers(ROOT, PACK_PATHS)
    if hidden:
        raise RuntimeError(f"hidden financial writers={hidden!r}")
    profile = build_wnd_conformance_profile()
    replay = build_wnd_conformance_profile()
    assert_profile_replay(profile, replay)
    report = evaluate_pack(profile)
    if report.cutover != "NOT_AUTHORIZED" or report.writer_retirement != "NOT_EXECUTED":
        raise RuntimeError("M8.4 readiness evidence exceeded R6 boundary")
    changed = commercial_sale_envelope(gross_amount="11000")
    changed_payload = dict(changed.payload)
    changed_payload.update({"collected_amount": "8000"})
    changed = replace(changed, payload=changed_payload)
    first = first_canonical_plan()
    candidate = WndFinancialMappingService.map(changed)
    try:
        from core.domain.finance.wnd_financial_mapping_contract import assert_replay
        assert_replay(first, candidate)
    except WndFinancialMappingError as exc:
        if exc.code != "mapping_idempotency_conflict":
            raise
    else:
        raise RuntimeError("conflicting specimen source did not fail closed")
    return profile, report


def _development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"development database must be={DEVELOPMENT_DATABASE_NAME}")
    releases = (
        m2_manifest(ROOT).checked_components, m3_manifest(ROOT).checked_components,
        validate_frozen_m4_manifest(ROOT), m5_manifest(ROOT),
        m6_manifest(ROOT).checked_components, m7_manifest(ROOT).checked_components,
    )
    profile, report = _static_conformance()
    with application_engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != DEVELOPMENT_DATABASE_NAME or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
        tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        for table in EMPTY_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development financial table not empty={table}")
    print(f"database={database}")
    print(f"revision={revision}")
    print("release_manifests=" + ",".join(f"m{index + 2}:{count}" for index, count in enumerate(releases)))
    print(f"m84_pack_conformance_development=PASS manifests=PASS M7_frozen=PASS development_empty=PASS generic_harness=PASS specimen_flows={len(profile.flows)} readiness={report.readiness_verdict} schema_neutral=PASS")


def _expect(code, action):
    try:
        action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected={code}; actual={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error not raised={code}")


def _counts(session):
    names = ("idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines", "financial_obligations", "value_sources", "payment_allocations")
    return {name: session.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in names}


def _exercise(selected):
    profile, report = _static_conformance()
    _install_fixtures(selected)
    descriptor = first_canonical_plan().commands[0]
    command = _event_command(
        public_id=descriptor.public_id,
        amount=Decimal(str(descriptor.payload["amount"])),
        idempotency_scope=descriptor.idempotency_scope,
        idempotency_key=descriptor.idempotency_key,
        correlation_id=UUID(str(descriptor.payload["correlation_id"])),
        metadata={"pack_conformance_profile": profile.profile_fingerprint, "operational_source": "commercial_sale:sale-8401"},
        actor_service="m84-pack-conformance",
    )
    with Session(selected, expire_on_commit=False) as session, session.begin():
        accepted = TransactionalCanonicalFinancialEventEngine.emit(session, command)
        replay = TransactionalCanonicalFinancialEventEngine.emit(session, command)
        if accepted.replayed or not replay.replayed or accepted.event.id != replay.event.id:
            raise RuntimeError("canonical exact-once replay did not converge")
        _expect("idempotency_conflict", lambda: TransactionalCanonicalFinancialEventEngine.emit(session, replace(command, amount=command.amount + Decimal("1"))))
        cross_org = replace(command, public_id=UUID("84000000-0000-0000-0000-000000000003"), idempotency_key="m84:cross-org", organization_unit_id=ORG_TWO)
        _expect("organization_unit_not_active", lambda: TransactionalCanonicalFinancialEventEngine.emit(session, cross_org))

    rollback = replace(command, public_id=UUID("84000000-0000-0000-0000-000000000004"), idempotency_key="m84:rollback")
    with Session(selected) as session:
        transaction = session.begin()
        before = _counts(session)
        TransactionalCanonicalFinancialEventEngine.emit(session, rollback)
        transaction.rollback()
    with Session(selected) as session:
        after = _counts(session)
        if after != before:
            raise RuntimeError(f"failed pack-to-finance command left residue before={before} after={after}")
        if after["financial_events"] != 1 or after["idempotency_records"] != 1 or after["outbox_messages"] != 1:
            raise RuntimeError(f"exact-once authority counts differ={after}")
        if any(after[name] for name in ("journal_entries", "journal_lines", "financial_obligations", "value_sources", "payment_allocations")):
            raise RuntimeError("pack conformance probe created an unrequested secondary financial effect")
        row = session.execute(text("SELECT metadata FROM financial_events WHERE public_id=:public"), {"public": str(command.public_id)}).mappings().one()
        if row["metadata"].get("pack_conformance_profile") != profile.profile_fingerprint:
            raise RuntimeError("operational-source-to-canonical traceability lost")
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_HEAD:
            raise RuntimeError(f"disposable revision changed={revision}")

    authorize(AuthorityProbe(2, 1, "post_financial_fact", 84, frozenset({"accounting.post"})))
    authorize(AuthorityProbe(2, 1, "reopen_period", 84, frozenset({"accounting.close_period"}), 85, frozenset({"accounting.close_period"}), "m84-approved-evidence"))
    _expect("permission_denied", lambda: authorize(AuthorityProbe(2, 1, "post_financial_fact", 84, frozenset())))
    _expect("approval_separation_required", lambda: authorize(AuthorityProbe(2, 1, "reopen_period", 84, frozenset({"accounting.close_period"}), 84, frozenset({"accounting.close_period"}), "m84-approved-evidence")))
    if report.readiness_verdict != "PASS":
        raise RuntimeError("specimen readiness report did not pass")


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
        print(f"M8.4 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print(
        f"m84_pack_financial_conformance=PASS database={TEST_DATABASE_NAME} pack_conformance=PASS "
        "generic_harness=PASS wnd_specimen=PASS exact_once=PASS replay=PASS conflict=PASS "
        "control_totals=PASS hidden_writers=NONE traceability=PASS tenant_scope=PASS organization_scope=PASS "
        "permissions=PASS approvals=PASS recovery=PASS M7_frozen=PASS writer_routing=UNCHANGED "
        "cutover=NOT_AUTHORIZED writer_retirement=NOT_EXECUTED schema_neutral=PASS migration=NONE dropped=true"
    )


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
        _drop(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
