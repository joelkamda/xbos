from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_r6_1_wnd_rehearsal_adoption as r61
from restaurant.r6.application_compatibility import (
    assert_required_routes,
    schema_fingerprint,
    semantic_hash,
    validate_uat_evidence,
)

EXPECTED_BRANCH = "restaurant/r6-3-wnd-application-compatibility-uat"
SOURCE_COMMIT = "9a8c69dfb0caf18fe010d858caceef84b863a4c2"
SOURCE_ARCHIVE_SHA256 = "b09b6f212ed1513b404187ae7e553917769ff7eb38a88c20c167fbf200fd80cd"
SOURCE_ARCHIVE_SIZE = 6222837
R6_2_FREEZE_TAG = "restaurant-r6-2-wnd-production-cutover-rehearsal-20260821"
R63_TARGET_HEAD = "r63_legacy_inventory_writer_compat_044"

AUTHORITY_PATH = "contracts/restaurant/v1/r6_3_application_compatibility_authority.json"
REFERENCE_PATH = "contracts/restaurant/v1/r6_3_reference_application_contract.json"
UAT_MATRIX_PATH = "contracts/restaurant/v1/r6_3_uat_matrix.json"
RELEASE_MANIFEST_PATH = "contracts/restaurant/v1/r6_3_release_manifest.json"
UAT_EVIDENCE_PATH = ROOT / "contracts/restaurant/v1/r6_3_visual_uat_evidence.json"

SOURCE_DATABASE = "xbos_r6_3_source"
CANDIDATE_DATABASE = "xbos_r6_3_candidate"
DISPOSABLE_DATABASES = frozenset({SOURCE_DATABASE, CANDIDATE_DATABASE})

WORKSPACE = Path.home() / "Downloads" / "XBOS_R6_3_UAT_WORKSPACE"
AUTOMATED_RESULT = Path.home() / "Downloads" / "XBOS_R6_3_AUTOMATED_COMPATIBILITY_RESULT.json"
SOURCE_INPUT_FILENAME = "XBOS_R6_3_WND_REFERENCE_SOURCE_INPUTS.zip"

EPHEMERAL_JWT_SECRET = "R6_3_UAT_EPHEMERAL_SECRET_NOT_FOR_PRODUCTION"
BACKEND_PORT = 8002
FRONTEND_PORT = 5174


def _run_text(args, **kwargs):
    """Run a captured subprocess with deterministic UTF-8 decoding.

    Windows console code pages must not decide how R6.3 evidence is decoded.
    Non-UTF8 bytes are retained as replacement characters in the diagnostic
    logs instead of killing Python's subprocess reader thread.
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(args, **kwargs)


def _load(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _verify_release_manifest() -> int:
    manifest = _load(RELEASE_MANIFEST_PATH)
    if manifest.get("self_excluded") is not True:
        raise RuntimeError("R6_3_RELEASE_MANIFEST_SELF_EXCLUSION")
    artifacts = manifest.get("artifacts") or []
    if manifest.get("artifact_count") != len(artifacts):
        raise RuntimeError("R6_3_RELEASE_MANIFEST_COUNT")
    paths = [row["path"] for row in artifacts]
    if len(paths) != len(set(paths)) or RELEASE_MANIFEST_PATH in paths:
        raise RuntimeError("R6_3_RELEASE_MANIFEST_PATH_SET")
    for row in artifacts:
        path = ROOT / row["path"]
        if not path.is_file():
            raise RuntimeError("R6_3_RELEASE_ARTIFACT_MISSING=" + row["path"])
        raw = path.read_bytes()
        canonical = raw.replace(b"\r\n", b"\n")
        if hashlib.sha256(canonical).hexdigest() != row["sha256"]:
            raise RuntimeError("R6_3_RELEASE_ARTIFACT_HASH=" + row["path"])
        if len(raw) != row["size"]:
            raise RuntimeError("R6_3_RELEASE_ARTIFACT_SIZE=" + row["path"])
    return len(artifacts)


def _find_reference_inputs() -> Path:
    expected = _load(AUTHORITY_PATH)["reference_source_input_bundle"]
    explicit = os.environ.get("R6_3_REFERENCE_INPUTS")
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.home() / "Downloads" / SOURCE_INPUT_FILENAME)
    for path in candidates:
        path = path.resolve()
        if not path.is_file():
            continue
        if path.stat().st_size != expected["size"]:
            continue
        if _sha(path).lower() != expected["sha256"].lower():
            continue
        return path
    raise RuntimeError(
        "R6_3_REFERENCE_SOURCE_INPUTS_NOT_FOUND_OR_HASH_MISMATCH. "
        f"Place {SOURCE_INPUT_FILENAME} in Downloads or set R6_3_REFERENCE_INPUTS."
    )


def _verify_reference_inputs(bundle: Path) -> dict[str, Any]:
    authority = _load(AUTHORITY_PATH)
    expected = authority["reference_source_input_bundle"]
    with zipfile.ZipFile(bundle) as z:
        if z.testzip() is not None:
            raise RuntimeError("R6_3_REFERENCE_INPUT_ZIP_CORRUPT")
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        backend_raw = z.read(manifest["backend"]["archive"])
        frontend_raw = z.read(manifest["frontend"]["archive"])

    if hashlib.sha256(backend_raw).hexdigest() != expected["backend_archive_sha256"]:
        raise RuntimeError("R6_3_REFERENCE_BACKEND_ARCHIVE_HASH")
    if len(backend_raw) != expected["backend_archive_size"]:
        raise RuntimeError("R6_3_REFERENCE_BACKEND_ARCHIVE_SIZE")
    if hashlib.sha256(frontend_raw).hexdigest() != expected["frontend_archive_sha256"]:
        raise RuntimeError("R6_3_REFERENCE_FRONTEND_ARCHIVE_HASH")
    if len(frontend_raw) != expected["frontend_archive_size"]:
        raise RuntimeError("R6_3_REFERENCE_FRONTEND_ARCHIVE_SIZE")
    if manifest["backend"]["commit"] != authority["reference_backend_commit"]:
        raise RuntimeError("R6_3_REFERENCE_BACKEND_COMMIT")
    if manifest["frontend"]["commit"] != authority["reference_frontend_commit"]:
        raise RuntimeError("R6_3_REFERENCE_FRONTEND_COMMIT")
    return manifest


def _static_verify() -> dict[str, Any]:
    branch = _run_text(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    head = _run_text(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"R6_3_WRONG_BRANCH expected={EXPECTED_BRANCH} actual={branch}")
    if head != SOURCE_COMMIT:
        raise RuntimeError(f"R6_3_SOURCE_HEAD_DRIFT expected={SOURCE_COMMIT} actual={head}")

    tag_target = _run_text(
        ["git", "rev-parse", f"{R6_2_FREEZE_TAG}^{{}}"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.strip()
    if tag_target != SOURCE_COMMIT:
        raise RuntimeError(f"R6_3_R6_2_FREEZE_TAG_DRIFT={tag_target}")

    authority = _load(AUTHORITY_PATH)
    if authority["source_checkpoint"] != SOURCE_COMMIT:
        raise RuntimeError("R6_3_SOURCE_CONTRACT_DRIFT")
    if authority["source_archive_sha256"] != SOURCE_ARCHIVE_SHA256:
        raise RuntimeError("R6_3_SOURCE_ARCHIVE_SHA_DRIFT")
    if authority["source_archive_size"] != SOURCE_ARCHIVE_SIZE:
        raise RuntimeError("R6_3_SOURCE_ARCHIVE_SIZE_DRIFT")
    if authority["production_write_authorized"] is not False:
        raise RuntimeError("R6_3_PRODUCTION_WRITE_AUTHORITY_LEAK")
    if authority["writer_routing"] != "unchanged":
        raise RuntimeError("R6_3_WRITER_ROUTING_LEAK")
    if authority["live_cutover_authorized"] is not False:
        raise RuntimeError("R6_3_LIVE_CUTOVER_AUTHORITY_LEAK")
    if authority["candidate_database"] != CANDIDATE_DATABASE or authority["source_database"] != SOURCE_DATABASE:
        raise RuntimeError("R6_3_DATABASE_SCOPE_DRIFT")

    expected_version = ROOT / "alembic_neutral/versions/r63_legacy_inventory_writer_compat_044.py"
    expected_up = ROOT / "alembic_neutral/sql/r63_legacy_inventory_writer_compat_up.sql"
    expected_down = ROOT / "alembic_neutral/sql/r63_legacy_inventory_writer_compat_down.sql"
    if not expected_version.is_file() or not expected_up.is_file() or not expected_down.is_file():
        raise RuntimeError("R6_3_COMPATIBILITY_MIGRATION_MISSING")

    migration_source = expected_version.read_text(encoding="utf-8")
    if 'revision = "r63_legacy_inventory_writer_compat_044"' not in migration_source:
        raise RuntimeError("R6_3_COMPATIBILITY_REVISION_DRIFT")
    if 'down_revision = "r2_restaurant_menu_fulfillment_043"' not in migration_source:
        raise RuntimeError("R6_3_COMPATIBILITY_PARENT_DRIFT")

    up_sql = expected_up.read_text(encoding="utf-8")
    for marker in (
        "trg_r63_legacy_inventory_item_fill_neutral_fields",
        "trg_r63_legacy_inventory_movement_fill_neutral_fields",
        "NEW.stock_location_id",
        "NEW.occurred_at",
        "NEW.reason_code",
        "NEW.source_reference",
    ):
        if marker not in up_sql:
            raise RuntimeError("R6_3_COMPATIBILITY_SQL_MARKER_MISSING=" + marker)

    bundle = _find_reference_inputs()
    source_manifest = _verify_reference_inputs(bundle)
    artifacts = _verify_release_manifest()
    return {
        "status": "PASS",
        "source_branch": branch,
        "source_head": head,
        "r6_2_freeze_tag": R6_2_FREEZE_TAG,
        "reference_input_bundle": str(bundle),
        "reference_input_sha256": _sha(bundle),
        "reference_backend_commit": source_manifest["backend"]["commit"],
        "reference_frontend_commit": source_manifest["frontend"]["commit"],
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
        "release_artifacts": artifacts,
    }


def _prepare_r61_harness() -> None:
    r61.SOURCE_DATABASE = SOURCE_DATABASE
    r61.CANDIDATE_DATABASE = CANDIDATE_DATABASE
    r61.DISPOSABLE_DATABASES = DISPOSABLE_DATABASES


def _engine(name: str):
    _prepare_r61_harness()
    return r61._database_engine(name)


def _restore(name: str, backup: Path) -> None:
    _prepare_r61_harness()
    r61._restore(name, backup)


def _adopt_and_compose() -> dict[str, Any]:
    _prepare_r61_harness()
    r61._adopt_candidate()
    with r61._database_environment(CANDIDATE_DATABASE):
        command.upgrade(
            r61._alembic_config(CANDIDATE_DATABASE),
            R63_TARGET_HEAD,
        )
    return r61._register_and_compose_candidate()


def _schema_rows(engine) -> list[dict[str, Any]]:
    sql = (
        "SELECT table_name,column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns "
        "WHERE table_schema='public' ORDER BY table_name,column_name"
    )
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(sql)).mappings().all()]


def _candidate_url() -> str:
    _prepare_r61_harness()
    url = r61._database_url().set(database=CANDIDATE_DATABASE)
    return url.render_as_string(hide_password=False)


def _extract_reference_workspace(bundle: Path) -> tuple[Path, Path]:
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    backend_dir = WORKSPACE / "backend"
    frontend_dir = WORKSPACE / "frontend"
    backend_dir.mkdir(parents=True)
    frontend_dir.mkdir(parents=True)

    with zipfile.ZipFile(bundle) as outer:
        manifest = json.loads(outer.read("manifest.json").decode("utf-8"))
        backend_raw = outer.read(manifest["backend"]["archive"])
        frontend_raw = outer.read(manifest["frontend"]["archive"])

    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        b = temp / "backend.zip"
        f = temp / "frontend.zip"
        b.write_bytes(backend_raw)
        f.write_bytes(frontend_raw)
        with zipfile.ZipFile(b) as z:
            z.extractall(backend_dir)
        with zipfile.ZipFile(f) as z:
            z.extractall(frontend_dir)
    return backend_dir, frontend_dir


def _frontend_contract(frontend_dir: Path) -> dict[str, Any]:
    contract = _load(REFERENCE_PATH)
    for relative, markers in contract["frontend_source_markers"].items():
        path = frontend_dir / relative
        if not path.is_file():
            raise RuntimeError("R6_3_FRONTEND_REQUIRED_FILE_MISSING=" + relative)
        selected = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in selected:
                raise RuntimeError(f"R6_3_FRONTEND_MARKER_MISSING={relative}:{marker}")

    router = (frontend_dir / "src/app/router.tsx").read_text(encoding="utf-8")
    missing = []
    for route in contract["frontend_required_routes"]:
        if route == "/":
            ok = "<Home" in router
        elif route in {"/login", "/select-context"}:
            ok = f'path: "{route}"' in router
        else:
            leaf = route.strip("/").split("/")[-1]
            ok = f'path: "{leaf}"' in router or route in router
        if not ok:
            missing.append(route)
    if missing:
        raise RuntimeError("R6_3_FRONTEND_ROUTE_MARKERS_MISSING=" + ",".join(missing))
    return {
        "required_files": len(contract["frontend_source_markers"]),
        "required_routes": len(contract["frontend_required_routes"]),
    }


def _backend_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = _candidate_url()
    env["GATEWAY_API_KEY"] = "R6_3_UAT_ONLY"
    env["JWT_SECRET"] = EPHEMERAL_JWT_SECRET
    env["JWT_ALGORITHM"] = "HS256"
    env["ENV"] = "development"
    env["DEV_TENANT_CODE"] = "CM001"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _openapi_from_reference_backend(backend_dir: Path) -> dict[str, Any]:
    output = WORKSPACE / "reference_openapi.json"
    script = (
        "import json,pathlib,main; "
        f"pathlib.Path(r'{str(output)}').write_text(json.dumps(main.app.openapi(),sort_keys=True),encoding='utf-8'); "
        "print('R6_3_REFERENCE_OPENAPI_GENERATED=PASS')"
    )
    cp = _run_text(
        [sys.executable, "-X", "utf8", "-c", script],
        cwd=backend_dir,
        env=_backend_env(),
        text=True,
        capture_output=True,
        timeout=120,
    )
    (WORKSPACE / "backend_openapi_stdout.log").write_text(cp.stdout, encoding="utf-8")
    (WORKSPACE / "backend_openapi_stderr.log").write_text(cp.stderr, encoding="utf-8")
    if cp.returncode:
        raise RuntimeError("R6_3_REFERENCE_BACKEND_OPENAPI_FAILED\n" + cp.stdout + "\n" + cp.stderr)
    if not output.is_file():
        raise RuntimeError("R6_3_REFERENCE_OPENAPI_FILE_MISSING")
    schema = json.loads(output.read_text(encoding="utf-8"))
    assert_required_routes(schema, _load(REFERENCE_PATH)["required_openapi_routes"])
    return schema


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt(payload: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    head = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(
        EPHEMERAL_JWT_SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256
    ).digest()
    return f"{head}.{body}.{_b64url(signature)}"


def _port_free(port: int) -> bool:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _http_json(url: str, token: str | None = None, timeout: int = 20) -> tuple[int, Any]:
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                value = json.loads(raw.decode("utf-8")) if raw else None
            except Exception:
                value = raw.decode("utf-8", errors="replace")
            return int(response.status), value
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            value = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            value = raw.decode("utf-8", errors="replace")
        return int(exc.code), value



def _legacy_inventory_writer_probe(backend_dir: Path) -> dict[str, Any]:
    output = WORKSPACE / "legacy_inventory_writer_probe.json"
    script = r"""
import json
import os
from sqlalchemy import text
from database import SessionLocal
# Mirror the real WND startup path before using ORM entities. The frozen
# application imports core.models_import so SQLAlchemy's string relationships
# (including InventoryItem.atomic_unit -> "AtomicUnit") are registered.
import core.models_import
from core.domain.inventory.models import InventoryItem, InventoryMovement

db = SessionLocal()
try:
    item = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.tenant_id == int(os.environ["R6_3_PROBE_TENANT_ID"]),
            InventoryItem.branch_id == int(os.environ["R6_3_PROBE_BRANCH_ID"]),
        )
        .order_by(InventoryItem.id)
        .first()
    )
    if item is None:
        raise RuntimeError("R6_3_LEGACY_PROBE_INVENTORY_ITEM_MISSING")

    movement = InventoryMovement(
        tenant_id=int(item.tenant_id),
        branch_id=int(item.branch_id),
        inventory_item_id=int(item.id),
        atomic_unit_id=int(item.atomic_unit_id),
        quantity_delta=0,
        movement_type="sale_commit",
        source="sales",
        reference_type="r6_3_compatibility_probe",
        reference_id=-630044,
    )
    db.add(movement)
    db.flush()

    row = db.execute(
        text(
            "SELECT stock_location_id, occurred_at, reason_code, source_reference "
            "FROM public.inventory_movements WHERE id=:id"
        ),
        {"id": int(movement.id)},
    ).mappings().one()

    payload = {
        "movement_id": int(movement.id),
        "stock_location_id": int(row["stock_location_id"]),
        "occurred_at": str(row["occurred_at"]),
        "reason_code": str(row["reason_code"]),
        "source_reference": str(row["source_reference"]),
    }
    if not payload["stock_location_id"]:
        raise RuntimeError("R6_3_LEGACY_PROBE_STOCK_LOCATION_EMPTY")
    if not payload["occurred_at"]:
        raise RuntimeError("R6_3_LEGACY_PROBE_OCCURRED_AT_EMPTY")
    if payload["reason_code"] != "sale-commit":
        raise RuntimeError("R6_3_LEGACY_PROBE_REASON_CODE_DRIFT")
    if payload["source_reference"] != "-630044":
        raise RuntimeError("R6_3_LEGACY_PROBE_SOURCE_REFERENCE_DRIFT")

    print(json.dumps(payload, sort_keys=True))
    db.rollback()
finally:
    db.close()
"""
    probe_env = _backend_env()
    probe_env["R6_3_PROBE_TENANT_ID"] = str(r61.PRODUCTION_TENANT_ID)
    probe_env["R6_3_PROBE_BRANCH_ID"] = str(r61.PRODUCTION_BRANCH_ID)
    cp = _run_text(
        [sys.executable, "-X", "utf8", "-c", script],
        cwd=backend_dir,
        env=probe_env,
        capture_output=True,
        timeout=120,
    )
    (WORKSPACE / "legacy_inventory_writer_probe_stdout.log").write_text(
        cp.stdout or "", encoding="utf-8"
    )
    (WORKSPACE / "legacy_inventory_writer_probe_stderr.log").write_text(
        cp.stderr or "", encoding="utf-8"
    )
    if cp.returncode:
        raise RuntimeError(
            "R6_3_LEGACY_INVENTORY_WRITER_PROBE_FAILED\n"
            + (cp.stdout or "")
            + "\n"
            + (cp.stderr or "")
        )
    rows = [line for line in (cp.stdout or "").splitlines() if line.strip().startswith("{")]
    if not rows:
        raise RuntimeError("R6_3_LEGACY_INVENTORY_WRITER_PROBE_NO_RESULT")
    payload = json.loads(rows[-1])
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload

def _runtime_smoke(backend_dir: Path) -> dict[str, int]:
    if not _port_free(BACKEND_PORT):
        raise RuntimeError(f"R6_3_BACKEND_PORT_{BACKEND_PORT}_IN_USE")
    log_path = WORKSPACE / "backend_runtime.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "uvicorn", "main:app",
             "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
            cwd=backend_dir,
            env=_backend_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.time() + 60
            while time.time() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("R6_3_REFERENCE_BACKEND_EXITED_EARLY")
                try:
                    status, _ = _http_json(f"http://127.0.0.1:{BACKEND_PORT}/health", timeout=2)
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("R6_3_REFERENCE_BACKEND_HEALTH_TIMEOUT")

            engine = _engine(CANDIDATE_DATABASE)
            try:
                with engine.connect() as connection:
                    user_id = connection.execute(
                        text("SELECT id FROM users WHERE tenant_id=:t ORDER BY id LIMIT 1"),
                        {"t": r61.PRODUCTION_TENANT_ID},
                    ).scalar_one()
            finally:
                engine.dispose()

            now = int(time.time())
            token = _jwt({
                "sub": str(int(user_id)),
                "tenant_id": int(r61.PRODUCTION_TENANT_ID),
                "branch_id": int(r61.PRODUCTION_BRANCH_ID),
                "role": "admin",
                "permissions": ["*"],
                "iat": now,
                "exp": now + 3600,
                "type": "access",
            })
            statuses = {}
            for path in _load(REFERENCE_PATH)["representative_read_smoke"]:
                status, body = _http_json(
                    f"http://127.0.0.1:{BACKEND_PORT}{path}", token=token, timeout=30
                )
                statuses[path] = status
                if status != 200:
                    raise RuntimeError(
                        f"R6_3_REFERENCE_READ_SMOKE_FAILED path={path} status={status} body={body}"
                    )
            return statuses
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def _frontend_build(frontend_dir: Path) -> dict[str, Any]:
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise RuntimeError("R6_3_NPM_NOT_FOUND")

    ci = _run_text(
        [npm, "ci", "--prefer-offline", "--no-audit", "--no-fund"],
        cwd=frontend_dir, text=True, capture_output=True, timeout=300
    )
    (WORKSPACE / "frontend_npm_ci.log").write_text(ci.stdout + "\n" + ci.stderr, encoding="utf-8")
    if ci.returncode:
        raise RuntimeError("R6_3_FRONTEND_NPM_CI_FAILED")

    build = _run_text(
        [npm, "run", "build"],
        cwd=frontend_dir, text=True, capture_output=True, timeout=300
    )
    (WORKSPACE / "frontend_build.log").write_text(build.stdout + "\n" + build.stderr, encoding="utf-8")
    if build.returncode:
        raise RuntimeError("R6_3_FRONTEND_BUILD_FAILED")

    vite_cfg = frontend_dir / "vite.r6-3-uat.config.ts"
    vite_text = (
        'import { defineConfig } from "vite";\n'
        'import react from "@vitejs/plugin-react";\n'
        'export default defineConfig({\n'
        '  plugins: [react()],\n'
        '  server: {\n'
        '    host: "127.0.0.1",\n'
        '    port: 5174,\n'
        '    proxy: {\n'
        '      "/api": {\n'
        '        target: "http://127.0.0.1:8002",\n'
        '        changeOrigin: true,\n'
        '        rewrite: (path) => path.replace(/^\\/api/, "/kernel"),\n'
        '      },\n'
        '      "/kernel": {\n'
        '        target: "http://127.0.0.1:8002",\n'
        '        changeOrigin: true,\n'
        '      },\n'
        '    },\n'
        '  },\n'
        '});\n'
    )
    vite_cfg.write_text(vite_text, encoding="utf-8")
    return {"npm_ci": "PASS", "build": "PASS", "uat_config": str(vite_cfg)}


def _prepare_candidate() -> dict[str, Any]:
    _prepare_r61_harness()
    backup = r61._find_backup()

    _restore(SOURCE_DATABASE, backup)
    source_engine = _engine(SOURCE_DATABASE)
    try:
        source_controls = r61._assert_source_controls(source_engine, "R6_3_SOURCE")
        source_control_totals = r61._control_totals(source_engine)
    finally:
        source_engine.dispose()

    _restore(CANDIDATE_DATABASE, backup)
    candidate_engine = _engine(CANDIDATE_DATABASE)
    try:
        r61._assert_source_controls(candidate_engine, "R6_3_CANDIDATE_RAW")
    finally:
        candidate_engine.dispose()

    composition = _adopt_and_compose()
    candidate_engine = _engine(CANDIDATE_DATABASE)
    try:
        if r61._current_head(candidate_engine) != R63_TARGET_HEAD:
            raise RuntimeError("R6_3_CANDIDATE_HEAD_DRIFT")
        if r61._counts(candidate_engine) != r61.EXPECTED_COUNTS:
            raise RuntimeError("R6_3_CANDIDATE_COUNTS_DRIFT")
        if r61._control_totals(candidate_engine) != source_control_totals:
            raise RuntimeError("R6_3_CANDIDATE_CONTROL_DRIFT")
    finally:
        candidate_engine.dispose()

    return {"backup": str(backup), "source_controls": source_controls, "composition": composition}


def _acceptance() -> dict[str, Any]:
    static = _static_verify()
    bundle = Path(static["reference_input_bundle"])
    reference_manifest = _verify_reference_inputs(bundle)
    candidate = _prepare_candidate()

    backend_dir, frontend_dir = _extract_reference_workspace(bundle)
    frontend_contract = _frontend_contract(frontend_dir)

    engine = _engine(CANDIDATE_DATABASE)
    try:
        before_schema = schema_fingerprint(_schema_rows(engine))
        before_counts = r61._counts(engine)
        before_controls = r61._control_totals(engine)
        before_reference = r61._legacy_reference_schema(engine)
    finally:
        engine.dispose()

    openapi = _openapi_from_reference_backend(backend_dir)

    engine = _engine(CANDIDATE_DATABASE)
    try:
        if schema_fingerprint(_schema_rows(engine)) != before_schema:
            raise RuntimeError("R6_3_REFERENCE_BACKEND_STARTUP_CHANGED_SCHEMA")
        if r61._counts(engine) != before_counts:
            raise RuntimeError("R6_3_REFERENCE_BACKEND_STARTUP_CHANGED_COUNTS")
        if r61._control_totals(engine) != before_controls:
            raise RuntimeError("R6_3_REFERENCE_BACKEND_STARTUP_CHANGED_CONTROLS")
        if r61._legacy_reference_schema(engine) != before_reference:
            raise RuntimeError("R6_3_REFERENCE_BACKEND_STARTUP_CHANGED_REFERENCE_SCHEMA")
    finally:
        engine.dispose()

    legacy_inventory_writer = _legacy_inventory_writer_probe(backend_dir)

    smoke = _runtime_smoke(backend_dir)

    engine = _engine(CANDIDATE_DATABASE)
    try:
        if schema_fingerprint(_schema_rows(engine)) != before_schema:
            raise RuntimeError("R6_3_READ_SMOKE_CHANGED_SCHEMA")
        if r61._counts(engine) != before_counts:
            raise RuntimeError("R6_3_READ_SMOKE_CHANGED_COUNTS")
        if r61._control_totals(engine) != before_controls:
            raise RuntimeError("R6_3_READ_SMOKE_CHANGED_CONTROLS")
    finally:
        engine.dispose()

    frontend_build = _frontend_build(frontend_dir)

    result = {
        "status": "PASS",
        "source_checkpoint": SOURCE_COMMIT,
        "r6_2_freeze_tag": R6_2_FREEZE_TAG,
        "reference_release_tag": _load(AUTHORITY_PATH)["reference_release_tag"],
        "reference_backend_commit": reference_manifest["backend"]["commit"],
        "reference_frontend_commit": reference_manifest["frontend"]["commit"],
        "candidate_database": CANDIDATE_DATABASE,
        "candidate_head": R63_TARGET_HEAD,
        "candidate_schema_fingerprint": before_schema,
        "candidate_legacy_counts": before_counts,
        "candidate_legacy_controls": before_controls,
        "candidate_composition": candidate["composition"],
        "reference_openapi_path_count": len(openapi.get("paths") or {}),
        "legacy_inventory_writer_probe": legacy_inventory_writer,
        "reference_read_smoke": smoke,
        "frontend_contract": frontend_contract,
        "frontend_build": frontend_build,
        "workspace": str(WORKSPACE),
        "production_database_touched": False,
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
    }
    result["fingerprint"] = semantic_hash(result)
    AUTOMATED_RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    result["result_file"] = str(AUTOMATED_RESULT)
    return result


def _load_automated_result() -> dict[str, Any]:
    if not AUTOMATED_RESULT.is_file():
        raise RuntimeError("R6_3_AUTOMATED_RESULT_MISSING. Run XBOS_R6_3_RUN_AUTOMATED_ACCEPTANCE.cmd first.")
    result = json.loads(AUTOMATED_RESULT.read_text(encoding="utf-8"))
    if result.get("status") != "PASS":
        raise RuntimeError("R6_3_AUTOMATED_RESULT_NOT_PASS")
    if result.get("source_checkpoint") != SOURCE_COMMIT:
        raise RuntimeError("R6_3_AUTOMATED_SOURCE_DRIFT")
    authority = _load(AUTHORITY_PATH)
    if result.get("reference_backend_commit") != authority["reference_backend_commit"]:
        raise RuntimeError("R6_3_AUTOMATED_BACKEND_DRIFT")
    if result.get("reference_frontend_commit") != authority["reference_frontend_commit"]:
        raise RuntimeError("R6_3_AUTOMATED_FRONTEND_DRIFT")
    if not WORKSPACE.is_dir():
        raise RuntimeError("R6_3_UAT_WORKSPACE_MISSING")
    return result


def _uat_ready() -> dict[str, Any]:
    static = _static_verify()
    automated = _load_automated_result()
    if not (WORKSPACE / "backend").is_dir() or not (WORKSPACE / "frontend").is_dir():
        raise RuntimeError("R6_3_UAT_SOURCE_WORKSPACE_INCOMPLETE")
    if not (WORKSPACE / "frontend/vite.r6-3-uat.config.ts").is_file():
        raise RuntimeError("R6_3_UAT_VITE_OVERRIDE_MISSING")
    engine = _engine(CANDIDATE_DATABASE)
    try:
        if r61._current_head(engine) != R63_TARGET_HEAD:
            raise RuntimeError("R6_3_UAT_CANDIDATE_HEAD_DRIFT")
    finally:
        engine.dispose()
    return {"status": "PASS", "automated_fingerprint": automated["fingerprint"], "static": static}


def _record_uat(operator: str) -> dict[str, Any]:
    if operator != "ACCEPT-R6.3-WND-UAT":
        raise RuntimeError("R6_3_UAT_OPERATOR_TOKEN_INVALID")
    automated = _load_automated_result()
    matrix = _load(UAT_MATRIX_PATH)
    evidence = {
        "schema_version": 1,
        "contract": "R6_3_WND_VISUAL_UAT_EVIDENCE",
        "status": "PASS",
        "accepted_at": datetime.now(timezone.utc).isoformat(),
        "operator_confirmation": operator,
        "reference_release_tag": _load(AUTHORITY_PATH)["reference_release_tag"],
        "backend_commit": _load(AUTHORITY_PATH)["reference_backend_commit"],
        "frontend_commit": _load(AUTHORITY_PATH)["reference_frontend_commit"],
        "candidate_database": CANDIDATE_DATABASE,
        "candidate_head": R63_TARGET_HEAD,
        "automated_compatibility_fingerprint": automated["fingerprint"],
        "items": {row["id"]: "PASS" for row in matrix["items"]},
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
    }
    validate_uat_evidence(evidence, matrix)
    UAT_EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def _final() -> dict[str, Any]:
    static = _static_verify()
    automated = _load_automated_result()
    if not UAT_EVIDENCE_PATH.is_file():
        raise RuntimeError("R6_3_VISUAL_UAT_EVIDENCE_MISSING")
    evidence = json.loads(UAT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    matrix = _load(UAT_MATRIX_PATH)
    validate_uat_evidence(evidence, matrix)
    if evidence.get("automated_compatibility_fingerprint") != automated.get("fingerprint"):
        raise RuntimeError("R6_3_UAT_AUTOMATED_FINGERPRINT_MISMATCH")
    authority = _load(AUTHORITY_PATH)
    if evidence.get("backend_commit") != authority["reference_backend_commit"]:
        raise RuntimeError("R6_3_UAT_BACKEND_DRIFT")
    if evidence.get("frontend_commit") != authority["reference_frontend_commit"]:
        raise RuntimeError("R6_3_UAT_FRONTEND_DRIFT")
    return {
        "status": "PASS",
        "source_checkpoint": SOURCE_COMMIT,
        "reference_backend_commit": evidence["backend_commit"],
        "reference_frontend_commit": evidence["frontend_commit"],
        "candidate_database": CANDIDATE_DATABASE,
        "automated_compatibility": "PASS",
        "visual_uat": "PASS",
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
        "r6_4_readiness": True,
        "static": static,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--uat-ready", action="store_true")
    parser.add_argument("--record-uat")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()

    if args.acceptance:
        result = _acceptance()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        print("R6_3_AUTOMATED_COMPATIBILITY=PASS")
        print("R6_3_REFERENCE_BACKEND_ON_NEUTRAL_CANDIDATE=PASS")
        print("R6_3_REFERENCE_FRONTEND_BUILD=PASS")
        print("R6_3_VISUAL_UAT_REQUIRED=YES")
        return 0
    if args.uat_ready:
        result = _uat_ready()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        print("R6_3_UAT_READY=PASS")
        return 0
    if args.record_uat is not None:
        result = _record_uat(args.record_uat)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        print("R6_3_VISUAL_UAT_EVIDENCE=PASS")
        return 0
    if args.final:
        result = _final()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        print("R6_3_VERIFY=PASS")
        return 0

    result = _static_verify()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print("R6_3_STATIC_VERIFY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
