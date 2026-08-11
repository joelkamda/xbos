"""Read-only M7.0 inventory and adapter-boundary verification."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.legacy_authority_inventory import EXPECTED_HEAD, load_inventory, verify_no_writer_rerouting
from core.domain.finance.m6_acceptance import validate_release_manifest as validate_m6_manifest
from database import engine


def verify() -> None:
    inventory = load_inventory(ROOT)
    verify_no_writer_rerouting(ROOT)
    if inventory.live_cutover_owner != "R6" or inventory.writer_routing != "unchanged":
        raise RuntimeError("M7.0 cutover boundary changed")
    if len(inventory.surfaces) != 14:
        raise RuntimeError(f"unexpected inventory surface count={len(inventory.surfaces)}")
    if validate_m6_manifest(ROOT).canonical_head != EXPECTED_HEAD:
        raise RuntimeError("M6 freeze authority changed")
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != "xbos_track_b_dev":
            raise RuntimeError(f"unexpected development database={database}")
        if revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development revision={revision}")
    print(f"database={database}")
    print(f"revision={revision}")
    print(f"m70_legacy_authority_inventory=PASS surfaces={len(inventory.surfaces)} fingerprint={inventory.semantic_fingerprint}")
    print("m70_adapter_boundary=PASS writer_routing=UNCHANGED execution=FORBIDDEN cutover_owner=R6 migration=NONE")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    args = parser.parse_args()
    if args.command == "verify":
        verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
