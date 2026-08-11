"""Aggregate M7.0-M7.4 conformance and M7 freeze verification."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.legacy_authority_inventory import verify_no_writer_rerouting
from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import (
    EXPECTED_HEAD,
    validate_frozen_m4_manifest,
    validate_release_manifest as m6_manifest,
)
from core.domain.finance.m7_acceptance import (
    validate_authority_boundaries,
    validate_public_artifacts,
    validate_release_manifest as m7_manifest,
)
from database import engine

FINANCIAL_TABLES = (
    "idempotency_records",
    "kernel_source_records",
    "financial_events",
    "outbox_messages",
    "journal_entries",
    "journal_lines",
    "financial_obligations",
    "value_sources",
    "payment_allocations",
    "allocation_reversals",
    "payment_settlements",
    "provider_settlement_components",
    "operational_account_balance_anchors",
    "operational_account_balance_observations",
    "reconciliation_series",
    "reconciliation_windows",
    "reconciliation_cascade_runs",
    "reconciliation_window_revisions",
    "reconciliation_window_governance_events",
    "reconciliation_controls",
    "reconciliation_control_items",
    "reconciliation_evidence_references",
)
VERIFIERS = (
    ("m70", ("verify_m70_legacy_financial_authority.py", "verify")),
    ("m71", ("verify_m71_wnd_financial_mapping.py",)),
    ("m72", ("verify_m72_wnd_inventory_document_mapping.py",)),
    ("m73", ("verify_m73_wnd_shadow_rehearsal.py",)),
    ("m74", ("verify_m74_wnd_cutover_support.py",)),
)


def _development() -> None:
    if engine.url.database != "xbos_track_b_dev":
        raise RuntimeError("development database must be xbos_track_b_dev")
    counts = (
        m2_manifest(ROOT).checked_components,
        m3_manifest(ROOT).checked_components,
        validate_frozen_m4_manifest(ROOT),
        m5_manifest(ROOT),
        m6_manifest(ROOT).checked_components,
        m7_manifest(ROOT).checked_components,
    )
    validate_authority_boundaries(ROOT)
    validate_public_artifacts(ROOT)
    verify_no_writer_rerouting(ROOT)
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != "xbos_track_b_dev" or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20:
            raise RuntimeError("financial event catalog count differs")
        tables = set(connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        ).scalars())
        for table in FINANCIAL_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development table not empty={table}")
    print("database=xbos_track_b_dev")
    print(f"revision={EXPECTED_HEAD}")
    print(
        "release_manifests="
        f"m2:{counts[0]},m3:{counts[1]},m4:{counts[2]},m5:{counts[3]},m6:{counts[4]},m7:{counts[5]}"
    )
    print(
        "m75_m7_development_acceptance=PASS manifest=PASS lineage=PASS development_empty=PASS "
        "writer_routing=UNCHANGED cutover=NOT_AUTHORIZED retirement=NOT_EXECUTED"
    )


def _run() -> None:
    _development()
    engine.dispose()
    for label, command in VERIFIERS:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / command[0]), *command[1:]],
            cwd=ROOT,
            check=True,
        )
        print(f"phase={label} capability=PASS schema_neutral=true")
    _development()
    print(
        "m75_m7_acceptance=PASS canonical_head=m64_reconciliation_controls_020 manifest=PASS "
        "development=PASS m70_m74=PASS inventory=PASS mapping=PASS cogs_documents=PASS "
        "shadow=PASS control_totals=PASS dual_read=PASS readiness=PASS replay=PASS conflict=PASS "
        "tenant_scope=PASS writer_routing=UNCHANGED cutover=NOT_AUTHORIZED "
        "retirement=NOT_EXECUTED migration=NONE"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "create-and-verify"))
    args = parser.parse_args()
    if args.command == "verify":
        _development()
    else:
        _run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
