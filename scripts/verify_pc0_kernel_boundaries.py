#!/usr/bin/env python3
"""Verify PC0 without importing application startup or mutating the database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.architecture_contract import PC0ArchitectureError, validate_pc0


def verify_development_database() -> dict[str, str]:
    """Perform only read-only operator-environment checks against configured DB."""
    try:
        from sqlalchemy import text
        from database import engine
    except Exception as exc:  # pragma: no cover - operator environment only
        raise RuntimeError(f"development DB prerequisites unavailable: {exc}") from exc

    with engine.connect() as connection:  # pragma: no cover - operator environment only
        transaction = connection.begin()
        try:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            database_name = connection.execute(text("SELECT current_database()")).scalar_one()
            server_version = connection.execute(text("SHOW server_version")).scalar_one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        finally:
            transaction.rollback()
    if database_name != "xbos_track_b_dev":
        raise RuntimeError(f"configured database is {database_name!r}, expected 'xbos_track_b_dev'")
    if revision != "m64_reconciliation_controls_020":
        raise RuntimeError(f"runtime Alembic head is {revision!r}")
    return {"database": database_name, "postgresql": server_version, "alembic_head": revision, "mode": "READ ONLY"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", action="store_true", help="also run read-only checks against xbos_track_b_dev")
    parser.add_argument("--no-release-manifest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        report = validate_pc0(ROOT, validate_release=not args.no_release_manifest)
        if args.development:
            report["development_database"] = verify_development_database()
    except (PC0ArchitectureError, RuntimeError, OSError) as exc:
        print(f"PC0_VERIFY=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    print("PC0_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
