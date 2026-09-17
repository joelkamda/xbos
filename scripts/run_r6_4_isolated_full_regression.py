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

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import DATABASE_URL
import scripts.verify_r6_1_wnd_rehearsal_adoption as r61

PRODUCTION_DATABASE = "xbos"
TEST_DATABASE = "xbos_track_b_test"
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
LEGACY_HEAD = "5c706797029a"
DOWNLOADS = Path.home() / "Downloads"
RESULT = DOWNLOADS / "XBOS_R6_4_FULL_REGRESSION_RESULT.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _clean_python_caches() -> int:
    removed = 0
    for cache in sorted(ROOT.rglob("__pycache__"), reverse=True):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
            removed += 1
    for pattern in ("*.pyc", "*.pyo"):
        for compiled in ROOT.rglob(pattern):
            try:
                compiled.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    return removed


def _latest_baseline() -> tuple[Path, dict[str, Any], Path]:
    pointer = DOWNLOADS / "XBOS_R6_4_LATEST_PLANNING_BASELINE.txt"
    candidates: list[Path] = []
    if pointer.is_file():
        raw = pointer.read_text(encoding="utf-8", errors="replace").strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend(sorted(
        DOWNLOADS.glob("WND_R6_4_PLANNING_BASELINE_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ))
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("contract") != "R6_4_WND_FRESH_PRODUCTION_PLANNING_BASELINE":
            continue
        if data.get("production_database") != PRODUCTION_DATABASE:
            continue
        if data.get("production_head") != LEGACY_HEAD:
            continue
        if data.get("production_writes") != "NONE":
            continue
        backup = Path(data["backup"]["path"])
        if not backup.is_file():
            continue
        if backup.stat().st_size != int(data["backup"]["size"]):
            continue
        if _sha(backup).lower() != str(data["backup"]["sha256"]).lower():
            continue
        return path, data, backup
    raise RuntimeError("R6_4_FRESH_PLANNING_BASELINE_NOT_FOUND_OR_INVALID")


def _base_url():
    url = make_url(DATABASE_URL)
    if url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(f"R6_4_REGRESSION_REMOTE_HOST_REFUSED={url.host}")
    if url.database != PRODUCTION_DATABASE:
        raise RuntimeError(
            f"R6_4_CONTROL_ENV_NOT_PRODUCTION_BASE expected={PRODUCTION_DATABASE} actual={url.database}"
        )
    if TEST_DATABASE == PRODUCTION_DATABASE:
        raise RuntimeError("R6_4_REGRESSION_DATABASE_COLLIDES_WITH_PRODUCTION")
    return url


def _restore_test_database(backup: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    url = _base_url()
    admin = create_engine(
        url.set(database="postgres"),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:db AND pid<>pg_backend_pid()"
                ),
                {"db": TEST_DATABASE},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}"'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    finally:
        admin.dispose()

    pg_restore = r61._locate_pg_tool("pg_restore")
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    proc = subprocess.run(
        [
            str(pg_restore),
            "--host", url.host or "localhost",
            "--port", str(url.port or 5432),
            "--username", url.username or "postgres",
            "--dbname", TEST_DATABASE,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            str(backup),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError("R6_4_REGRESSION_PG_RESTORE_FAILED\n" + (proc.stdout or ""))

    engine = create_engine(url.set(database=TEST_DATABASE), poolclass=NullPool)
    try:
        head = r61._current_head(engine)
        counts = r61._counts(engine)
        totals = r61._control_totals(engine)
    finally:
        engine.dispose()

    expected = baseline["production_observation"]
    expected_counts = {k: int(v) for k, v in expected["counts"].items()}
    expected_totals = {k: str(v) for k, v in expected["totals"].items()}
    actual_totals = {k: str(v) for k, v in totals.items()}

    if head != LEGACY_HEAD:
        raise RuntimeError(f"R6_4_REGRESSION_DB_HEAD expected={LEGACY_HEAD} actual={head}")
    if counts != expected_counts:
        raise RuntimeError("R6_4_REGRESSION_DB_COUNT_PARITY_FAILED")
    if actual_totals != expected_totals:
        raise RuntimeError("R6_4_REGRESSION_DB_TOTAL_PARITY_FAILED")
    return {"head": head}


def main() -> int:
    removed = _clean_python_caches()
    baseline_path, baseline, backup = _latest_baseline()
    restored = _restore_test_database(backup, baseline)

    # Hard safety boundary: pytest receives only the disposable regression DB.
    url = _base_url()
    env = os.environ.copy()
    env["DATABASE_URL"] = url.set(database=TEST_DATABASE).render_as_string(hide_password=False)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"

    print(f"R6_4_BYTECODE_CACHE_CLEAN=PASS removed={removed}", flush=True)
    print(f"R6_4_REGRESSION_DATABASE={TEST_DATABASE}", flush=True)
    print("R6_4_REGRESSION_DATABASE_RESTORE=PASS", flush=True)
    print("R6_4_REGRESSION_PRODUCTION_DATABASE_EXCLUDED=PASS", flush=True)

    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, env=env)

    RESULT.write_text(json.dumps({
        "schema_version": 1,
        "contract": "R6_4_ISOLATED_FULL_REGRESSION",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_evidence": str(baseline_path),
        "backup_sha256": baseline["backup"]["sha256"],
        "test_database": TEST_DATABASE,
        "test_database_head_before_tests": restored["head"],
        "production_database": PRODUCTION_DATABASE,
        "production_database_supplied_to_pytest": False,
        "python_dont_write_bytecode": True,
        "pytest_exit_code": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if proc.returncode:
        print("R6_4_FULL_REGRESSION=FAIL", flush=True)
        return proc.returncode
    print("R6_4_FULL_REGRESSION=PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
