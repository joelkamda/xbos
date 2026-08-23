from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import DATABASE_URL
import scripts.verify_r6_1_wnd_rehearsal_adoption as r61

EXPECTED_BRANCH = "restaurant/r6-4-wnd-production-cutover-package-runbook"
EXPECTED_HEAD = "b97d3850b120aff92261ad9edcb3bf3151ebbcb3"
PRODUCTION_DATABASE = "xbos"
LEGACY_HEAD = "5c706797029a"
DOWNLOADS = Path.home() / "Downloads"


def _run(args, **kwargs):
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(args, **kwargs)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _engine():
    return create_engine(
        make_url(DATABASE_URL).set(database=PRODUCTION_DATABASE),
        poolclass=NullPool,
    )


def _git(*args: str) -> str:
    cp = _run(["git", *args], cwd=ROOT, capture_output=True)
    if cp.returncode:
        raise RuntimeError((cp.stdout or "") + "\n" + (cp.stderr or ""))
    return (cp.stdout or "").strip()


def _observe() -> dict[str, Any]:
    engine = _engine()
    try:
        head = r61._current_head(engine)
        if head != LEGACY_HEAD:
            raise RuntimeError(
                f"R6_4_PRODUCTION_HEAD_NOT_LEGACY expected={LEGACY_HEAD} actual={head}"
            )
        counts = r61._counts(engine)
        totals = r61._control_totals(engine)
        with engine.connect() as c:
            pg_version = str(c.execute(text("SHOW server_version")).scalar_one())
            db_size = int(c.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one())
            table_count = int(c.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )).scalar_one())
            neutral_presence = {
                name: bool(c.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar_one())
                for name in (
                    "public.r1_restaurant_orders",
                    "public.r2_restaurant_preparation_tickets",
                    "public.pk_packs",
                    "public.platform_parties",
                )
            }
            wal_lsn = str(c.execute(text("SELECT pg_current_wal_lsn()")).scalar_one())
        if any(neutral_presence.values()):
            raise RuntimeError(
                "R6_4_PRODUCTION_PARTIAL_NEUTRAL_ADOPTION_DETECTED="
                + json.dumps(neutral_presence, sort_keys=True)
            )
        return {
            "head": head,
            "counts": counts,
            "totals": {k: str(v) for k, v in totals.items()},
            "postgresql": pg_version,
            "database_size_bytes": db_size,
            "public_table_count": table_count,
            "neutral_authority_presence": neutral_presence,
            "observed_wal_lsn": wal_lsn,
        }
    finally:
        engine.dispose()


def _dump(path: Path) -> None:
    url = make_url(DATABASE_URL)
    pg_dump = r61._locate_pg_tool("pg_dump")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    cmd = [
        str(pg_dump),
        "--host", url.host or "localhost",
        "--port", str(url.port or 5432),
        "--username", url.username or "postgres",
        "--dbname", PRODUCTION_DATABASE,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file", str(path),
    ]
    cp = _run(cmd, env=env, capture_output=True)
    if cp.returncode:
        raise RuntimeError(
            "R6_4_PG_DUMP_FAILED\n" + (cp.stdout or "") + "\n" + (cp.stderr or "")
        )


def _verify_dump(path: Path) -> int:
    pg_restore = r61._locate_pg_tool("pg_restore")
    cp = _run([str(pg_restore), "--list", str(path)], capture_output=True)
    if cp.returncode:
        raise RuntimeError(
            "R6_4_PG_RESTORE_LIST_FAILED\n" + (cp.stdout or "") + "\n" + (cp.stderr or "")
        )
    rows = [line for line in (cp.stdout or "").splitlines() if line and not line.startswith(";")]
    if not rows:
        raise RuntimeError("R6_4_PG_RESTORE_LIST_EMPTY")
    return len(rows)


def main() -> int:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"R6_4_WRONG_BRANCH expected={EXPECTED_BRANCH} actual={branch}")
    if head != EXPECTED_HEAD:
        raise RuntimeError(f"R6_4_WRONG_HEAD expected={EXPECTED_HEAD} actual={head}")

    before = _observe()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = DOWNLOADS / f"WND_R6_4_PLANNING_BASELINE_{stamp}.backup"
    evidence = DOWNLOADS / f"WND_R6_4_PLANNING_BASELINE_{stamp}.json"

    _dump(backup)
    archive_rows = _verify_dump(backup)

    payload = {
        "schema_version": 1,
        "contract": "R6_4_WND_FRESH_PRODUCTION_PLANNING_BASELINE",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_branch": EXPECTED_BRANCH,
        "source_checkpoint": EXPECTED_HEAD,
        "production_database": PRODUCTION_DATABASE,
        "production_head": before["head"],
        "production_observation": before,
        "backup": {
            "path": str(backup),
            "filename": backup.name,
            "sha256": _sha(backup),
            "size": backup.stat().st_size,
            "pg_restore_list": "PASS",
            "archive_list_rows": archive_rows,
        },
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
        "note": "planning/rehearsal baseline only; R6.5 must take a new final backup after application writers are stopped"
    }
    evidence.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    pointer = DOWNLOADS / "XBOS_R6_4_LATEST_PLANNING_BASELINE.txt"
    pointer.write_text(str(evidence) + "\n", encoding="utf-8")

    print("R6_4_PRODUCTION_PREFLIGHT_READ_ONLY=PASS")
    print(f"R6_4_PRODUCTION_HEAD={before['head']}")
    print(f"R6_4_PLANNING_BACKUP={backup}")
    print(f"R6_4_PLANNING_BACKUP_SHA256={payload['backup']['sha256']}")
    print(f"R6_4_PLANNING_BACKUP_SIZE={payload['backup']['size']}")
    print(f"R6_4_PLANNING_EVIDENCE={evidence}")
    print("R6_4_PRODUCTION_WRITES=NONE")
    print("R6_4_LIVE_CUTOVER_AUTHORIZED=NO")
    print("R6_4_PLANNING_BASELINE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
