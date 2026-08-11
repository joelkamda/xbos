"""Aggregate M6.0-M6.4 conformance, recovery, and freeze verification."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import EXPECTED_HEAD, validate_concurrency_guards, validate_frozen_m4_manifest, validate_release_manifest
from database import engine as application_engine
from scripts import verify_m60_operational_balance_authority as m60
from scripts import verify_m61_operational_transfers as m61
from scripts import verify_m62_reconciliation_windows as m62
from scripts import verify_m63_reconciliation_close_governance as m63
from scripts import verify_m64_reconciliation_controls as m64

DATABASES = (
    m60.TEST_DATABASE_NAME,
    m61.TEST_DATABASE_NAME,
    m62.TEST_DATABASE_NAME,
    m63.TEST_DATABASE_NAME,
    m64.TEST_DATABASE_NAME,
)
M6_TABLES = (
    "operational_account_authorities",
    "operational_account_balance_anchors",
    "operational_account_balance_observations",
    "reconciliation_calendar_policies",
    "reconciliation_series",
    "reconciliation_windows",
    "reconciliation_cascade_runs",
    "reconciliation_window_revisions",
    "reconciliation_window_governance_events",
    "reconciliation_controls",
    "reconciliation_control_items",
    "reconciliation_evidence_references",
)
FINANCIAL_TABLES = (
    "idempotency_records", "kernel_source_records", "financial_events", "outbox_messages",
    "journal_entries", "journal_lines", "financial_obligations", "value_sources",
    "payment_allocations", "allocation_reversals", "payment_settlements",
    "provider_settlement_components",
)


def _exists(name: str) -> bool:
    return m64._exists(name)


def _development() -> None:
    if m64._url().database != "xbos_track_b_dev":
        raise RuntimeError("development database must be xbos_track_b_dev")
    release_counts = (
        m2_manifest(ROOT).checked_components,
        m3_manifest(ROOT).checked_components,
        validate_frozen_m4_manifest(ROOT),
        m5_manifest(ROOT),
        validate_release_manifest(ROOT).checked_components,
    )
    validate_concurrency_guards(ROOT)
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development revision={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20:
            raise RuntimeError("financial event catalog count differs")
        tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        for table in M6_TABLES:
            if table not in tables:
                raise RuntimeError(f"M6 table missing={table}")
        for table in M6_TABLES + FINANCIAL_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development table not empty={table}")
    print("database=xbos_track_b_dev")
    print(f"revision={EXPECTED_HEAD}")
    print(f"release_manifests=m2:{release_counts[0]},m3:{release_counts[1]},m4:{release_counts[2]},m5:{release_counts[3]},m6:{release_counts[4]}")
    print("m65_m6_development_acceptance=PASS manifest=PASS lineage=PASS development_empty=PASS concurrency_guards=PASS")


def _status(*, fail_if_present: bool = False) -> None:
    found = []
    for name in DATABASES:
        exists = _exists(name)
        print(f"database={name} exists={str(exists).lower()}")
        if exists:
            found.append(name)
    if fail_if_present and found:
        raise RuntimeError(f"disposable databases already exist={','.join(found)}")


def _capability(module, exercise, label: str, *, recovery: bool = False) -> None:
    name = module.TEST_DATABASE_NAME
    module._create_clone()
    selected = None
    try:
        if recovery:
            module._migrate(name, module.PARENT_REVISION, downgrade=True)
            module._migrate(name, module.TARGET_REVISION)
        selected = module._engine(name)
        exercise(selected)
        selected.dispose()
        selected = None
        module._drop(name)
        print(f"phase={label} database={name} capability=PASS recovery={'PASS' if recovery else 'inherited-head'} dropped=true")
    except Exception:
        if selected is not None:
            selected.dispose()
        print(f"M6.5 capability failed; retained disposable database={name} phase={label}")
        raise


def _run() -> None:
    _development()
    _status(fail_if_present=True)
    application_engine.dispose()
    _capability(m60, m60._exercise, "m60")
    _capability(m61, m61._exercise, "m61")
    _capability(m62, m62._exercise, "m62")
    _capability(m63, m63._exercise, "m63")
    _capability(m64, m64._exercise, "m64", recovery=True)
    _development()
    _status(fail_if_present=True)
    print("m65_m6_acceptance=PASS canonical_head=m64_reconciliation_controls_020 manifest=PASS development=PASS m60_m64=PASS recovery=PASS replay=PASS conflict=PASS concurrency=PASS tenant_scope=PASS correction_cascade=PASS close_reopen=PASS bank_ar_ap=PASS reports=PASS dropped=true")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "create-and-verify"))
    args = parser.parse_args()
    if args.command == "verify":
        _development()
    elif args.command == "status":
        _status()
    else:
        _run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
