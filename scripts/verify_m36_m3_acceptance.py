"""Consolidated fail-fast acceptance proof for the frozen M3 milestone."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from core.domain.finance.m3_acceptance import (
    EXPECTED_HEAD,
    revision_preserves_m3_checkpoint,
    validate_release_manifest,
)
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
CAPABILITIES = (
    ("m30", "verify_m30_obligation_foundation.py", "xbos_track_b_m30_foundation_test"),
    ("m31", "verify_m31_typed_obligation_lifecycle_balances.py", "xbos_track_b_m31_obligation_test"),
    ("m32", "verify_m32_allocation_engine.py", "xbos_track_b_m32_allocation_test"),
    ("m33", "verify_m33_value_application_workflows.py", "xbos_track_b_m33_value_application_test"),
    ("m34", "verify_m34_obligation_aging.py", "xbos_track_b_m34_aging_test"),
    ("m35", "verify_m35_obligation_settlement_trace.py", "xbos_track_b_m35_obligation_trace_test"),
)
ZERO_TABLES = (
    "financial_dimension_types",
    "financial_dimension_values",
    "posting_dimension_policies",
    "idempotency_records",
    "financial_events",
    "outbox_messages",
    "journal_entries",
    "journal_lines",
    "financial_obligations",
    "financial_obligation_lines",
    "value_sources",
    "payment_allocations",
    "allocation_reversals",
    "allocation_scope_policies",
    "obligation_state_transitions",
)


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _database_exists(database_name: str) -> bool:
    engine = create_engine(_application_url().set(database="postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database_name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _status() -> bool:
    clean = True
    for _, _, database_name in CAPABILITIES:
        exists = _database_exists(database_name)
        print(f"database={database_name} exists={str(exists).lower()}")
        clean = clean and not exists
    return clean


def _development_acceptance():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    manifest = validate_release_manifest(ROOT)
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if not revision_preserves_m3_checkpoint(ROOT, revision):
            raise RuntimeError(
                f"expected revision={EXPECTED_HEAD} or a linear descendant; actual={revision}"
            )
        catalog = connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one()
        if catalog != 20:
            raise RuntimeError(f"expected canonical catalog=20; actual={catalog}")
        counts = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ZERO_TABLES}
    populated = {table: count for table, count in counts.items() if count}
    if populated:
        raise RuntimeError(f"development financial tables are not empty: {populated}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print(f"manifest_components={manifest.checked_components}")
    print("m36_m3_development_acceptance=PASS canonical_head=m34_obligation_aging_010 manifest=PASS development_empty=PASS")


def _run_capability(script_name: str):
    subprocess.run([sys.executable, str(ROOT / "scripts" / script_name), "create-and-verify"], cwd=ROOT, check=True)


def _create_and_verify():
    _development_acceptance()
    if not _status():
        raise RuntimeError("one or more M3 disposable databases already exist")
    completed: list[str] = []
    for code, script_name, _ in CAPABILITIES:
        print(f"m36_capability_rehearsal={code} state=START")
        _run_capability(script_name)
        completed.append(code)
        print(f"m36_capability_rehearsal={code} state=PASS")
    if not _status():
        raise RuntimeError("a capability rehearsal retained a disposable database")
    _development_acceptance()
    capability_summary = " ".join(f"{code}=PASS" for code in completed)
    print(
        "m36_m3_acceptance=PASS canonical_head=m34_obligation_aging_010 "
        f"manifest=PASS development_empty=PASS {capability_summary} "
        "disposable_databases_dropped=true"
    )


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("verify")
    commands.add_parser("create-and-verify")
    arguments = parser.parse_args()
    if arguments.command == "status":
        return 0 if _status() else 1
    if arguments.command == "verify":
        _development_acceptance()
    else:
        _create_and_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
