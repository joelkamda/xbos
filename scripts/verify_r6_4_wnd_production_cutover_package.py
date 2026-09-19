from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.verify_r6_1_wnd_rehearsal_adoption as r61
import scripts.verify_r6_3_wnd_application_compatibility as r63
from restaurant.r6.production_cutover import (
    CutoverFingerprint,
    assert_legacy_truth_preserved,
    rollback_mode,
)

EXPECTED_BRANCH = "restaurant/r6-4-wnd-production-cutover-package-runbook"
EXPECTED_HEAD = "b97d3850b120aff92261ad9edcb3bf3151ebbcb3"
EXPECTED_SOURCE_SHA256 = "891dd822b0430a197d4e1dada026aff69b2cc50b06a7c568c6738f9dc4eb40a1"
EXPECTED_SOURCE_SIZE = 6272632
R6_3_TAG = "restaurant-r6-3-wnd-application-compatibility-uat-20260822"

SOURCE_DB = "xbos_r6_4_source"
CANDIDATE_DB = "xbos_r6_4_candidate"
DISPOSABLE = frozenset({SOURCE_DB, CANDIDATE_DB})
TARGET_HEAD = "r63_legacy_inventory_writer_compat_044"
TRACK_B_PORT = 8004
REFERENCE_PORT_CANDIDATES = (8002, 18002, 28002, 38002)
TRACK_B_PORT_CANDIDATES = (8004, 18004, 28004, 38004)

AUTHORITY = "contracts/restaurant/v1/r6_4_production_cutover_package_authority.json"
RUNBOOK = "contracts/restaurant/v1/r6_4_r6_5_cutover_runbook.json"
HYPERCARE = "contracts/restaurant/v1/r6_4_hypercare_retirement_boundary.json"
RELEASE = "contracts/restaurant/v1/r6_4_release_manifest.json"
REFERENCE = "contracts/restaurant/v1/r6_3_reference_application_contract.json"
DESCENDANT_CORRECTION = "contracts/restaurant/v1/r6_4_freeze_integrity_correction.json"
ORIGINAL_FREEZE_COMMIT = "330694145cb1d06ea915c3c484451f664ebd75f3"
ORIGINAL_FREEZE_TAG = "restaurant-r6-5-production-forward-baseline-v1-20260917"
ORIGINAL_INSTALL_MANIFEST_SHA256 = "3ff1cf7cba91cd6391bd8d6f2a9d951c262379f8bc03c5799ff3991d78df09e0"
ORIGINAL_RELEASE_MANIFEST_SHA256 = "cc0850be82e13c2ff3c4f8944eaf17ac3b58b733f8381ebcfd8a2423afb4e2ca"
INVENTORY_SERVICE_PATH = "restaurant/r6/wnd_api_compat/inventory_service.py"
INVENTORY_SERVICE_ORIGINAL_MANIFEST_SIZE = 54552
INVENTORY_SERVICE_ORIGINAL_MANIFEST_SHA256 = "329e9ddc1c5e8d1798ad270caaa5c777067ad3d2f365ee565d8ceb92fd673e3f"
INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SIZE = 53723
INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SHA256 = "2000f54f377d01748b1c01a353eec8000af86905fdae37daa103b53ef07e1ece"
HISTORICAL_OMISSIONS = (
    ("R6_4_REVISION_9_WND_COMPAT_OPENAPI_BINDING.txt", 1670, "0860f93386e915c236564370d9437b128ab0ec40e85b546e12418dbdd7436fd6"),
    ("R6_4_REVISION_8_WND_API_COMPATIBILITY_BRIDGE.txt", 2220, "317363db4ad8f904197555cd72465da2ac0a79ade51059f9048812fffb5f9139"),
    ("R6_4_REVISION_7_COLLISION_SAFE_DIAGNOSTIC_PORTS.txt", 1233, "ea45e8ebb8e9439da29fb2ee8aa5beb52198faef9f013d843b952e93a6ec9d9c"),
    ("R6_4_REVISION_6_BCRYPT_CONTROL_BACKEND.txt", 1022, "d6b7b063d6253d87687412d49e220523e0c3d01a5d2db884cb6adf88bccec935"),
    ("R6_4_REVISION_5_ISOLATED_FULL_REGRESSION.txt", 1265, "14f2798384f36d2308d584b356bb801315be0f848bcf67db32eafe098608d8b2"),
    ("R6_4_REVISION_4_DOWNSTREAM_RELEASE_INTEGRITY_CHAIN.txt", 1743, "2fd61835d14cac9dfb8199ad0e6b0d1cd40bb5b07c11ad2d87a3264a451aeff3"),
    ("R6_4_REVISION_3_CUMULATIVE_PLATFORM_INTEGRITY.txt", 1962, "7149ba7d9cc3660f467f30f0cc53d0711d7e592f25ac51cdfc13ec59a4969283"),
    ("R6_4_REVISION_2_WND_SERVER_RUNTIME.txt", 1034, "2e379014e41dc43ba24ca66fa864f544a3efe9afbfaed5bed6995f9fbfc37b0a"),
)

DOWNLOADS = Path.home() / "Downloads"
WORKSPACE = DOWNLOADS / "XBOS_R6_4_ACCEPTANCE_WORKSPACE"
RESULT = DOWNLOADS / "XBOS_R6_4_ACCEPTANCE_RESULT.json"


def _run(args, **kwargs):
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(args, **kwargs)


def _load(rel: str) -> dict[str, Any]:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _git(*args: str) -> str:
    cp = _run(["git", *args], cwd=ROOT, capture_output=True)
    if cp.returncode:
        raise RuntimeError((cp.stdout or "") + "\n" + (cp.stderr or ""))
    return (cp.stdout or "").strip()


def _canonical_sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _git_show_bytes(commit: str, path: str) -> bytes:
    cp = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
    )
    if cp.returncode:
        raise RuntimeError(
            "R6_4_DESCENDANT_GIT_OBJECT_MISSING="
            + f"{commit}:{path} "
            + cp.stderr.decode("utf-8", errors="replace")
        )
    return cp.stdout


def _git_path_exists_at(commit: str, path: str) -> bool:
    cp = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
    )
    return cp.returncode == 0


def _verify_descendant_freeze_integrity_correction(head: str) -> dict[str, Any]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ORIGINAL_FREEZE_COMMIT, head],
        cwd=ROOT,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise RuntimeError("R6_4_DESCENDANT_FREEZE_NOT_ANCESTOR")

    tag_target = _git("rev-parse", f"{ORIGINAL_FREEZE_TAG}^{{}}")
    if tag_target != ORIGINAL_FREEZE_COMMIT:
        raise RuntimeError(
            f"R6_4_DESCENDANT_FREEZE_TAG_DRIFT expected={ORIGINAL_FREEZE_COMMIT} actual={tag_target}"
        )

    contract = _load(DESCENDANT_CORRECTION)
    required_identity = {
        "correction_class": "DESCENDANT_FREEZE_INTEGRITY_CORRECTION",
        "original_freeze_commit": ORIGINAL_FREEZE_COMMIT,
        "original_freeze_tag": ORIGINAL_FREEZE_TAG,
        "original_install_manifest_sha256": ORIGINAL_INSTALL_MANIFEST_SHA256,
        "original_release_manifest_sha256": ORIGINAL_RELEASE_MANIFEST_SHA256,
        "byte_identical_recovery_count": 0,
        "deterministic_regeneration_count": 0,
        "historical_artifact_byte_identity": "UNRECOVERABLE",
        "underlying_semantics": "INDEPENDENTLY_PROVEN",
        "historical_omission_count": 8,
        "historical_rewrite": "NO",
        "artifact_fabrication": "NO",
        "historical_install_manifest_mutation": "NO",
        "historical_commit_tag_mutation": "NO",
        "correction_scope": "DESCENDANT_INTEGRITY_REPRESENTATION_ONLY",
    }
    for key, expected in required_identity.items():
        if contract.get(key) != expected:
            raise RuntimeError(
                f"R6_4_DESCENDANT_CORRECTION_IDENTITY_{key} expected={expected!r} actual={contract.get(key)!r}"
            )

    historical_install = _git_show_bytes(ORIGINAL_FREEZE_COMMIT, "R6_4_INSTALL_MANIFEST.txt")
    if _canonical_sha_bytes(historical_install) != ORIGINAL_INSTALL_MANIFEST_SHA256:
        raise RuntimeError("R6_4_DESCENDANT_HISTORICAL_INSTALL_MANIFEST_HASH")
    current_install = (ROOT / "R6_4_INSTALL_MANIFEST.txt").read_bytes()
    if _canonical_sha_bytes(current_install) != ORIGINAL_INSTALL_MANIFEST_SHA256:
        raise RuntimeError("R6_4_DESCENDANT_CURRENT_INSTALL_MANIFEST_MUTATION")

    historical_release = _git_show_bytes(
        ORIGINAL_FREEZE_COMMIT,
        "contracts/restaurant/v1/r6_4_release_manifest.json",
    )
    if _canonical_sha_bytes(historical_release) != ORIGINAL_RELEASE_MANIFEST_SHA256:
        raise RuntimeError("R6_4_DESCENDANT_HISTORICAL_RELEASE_MANIFEST_HASH")

    omissions = contract.get("historical_omissions") or []
    if len(omissions) != 8:
        raise RuntimeError("R6_4_DESCENDANT_OMISSION_COUNT")
    by_path = {row.get("path"): row for row in omissions}
    expected_paths = {path for path, _, _ in HISTORICAL_OMISSIONS}
    if set(by_path) != expected_paths:
        raise RuntimeError("R6_4_DESCENDANT_OMISSION_PATH_SET")
    for path, size, sha256 in HISTORICAL_OMISSIONS:
        row = by_path[path]
        if row.get("size") != size or row.get("sha256") != sha256:
            raise RuntimeError("R6_4_DESCENDANT_OMISSION_IDENTITY=" + path)
        if row.get("semantic_evidence") != "COMPLETE":
            raise RuntimeError("R6_4_DESCENDANT_SEMANTIC_EVIDENCE=" + path)
        if row.get("historical_artifact_byte_identity") != "UNRECOVERABLE":
            raise RuntimeError("R6_4_DESCENDANT_BYTE_IDENTITY=" + path)
        if row.get("underlying_semantics") != "INDEPENDENTLY_PROVEN":
            raise RuntimeError("R6_4_DESCENDANT_UNDERLYING_SEMANTICS=" + path)
        supporting = row.get("supporting_paths") or []
        if not supporting:
            raise RuntimeError("R6_4_DESCENDANT_SUPPORTING_PATHS_EMPTY=" + path)
        for support in supporting:
            if not _git_path_exists_at(ORIGINAL_FREEZE_COMMIT, support):
                raise RuntimeError(
                    f"R6_4_DESCENDANT_SUPPORT_NOT_IMMUTABLE omission={path} support={support}"
                )

    authority_changes = contract.get("authority_changes") or {}
    expected_authority_keys = {
        "r6_4_semantic_change",
        "database_schema_change",
        "migration_change",
        "payment_authority_change",
        "inventory_authority_change",
        "writer_routing_change",
        "live_cutover_authority_change",
        "production_write_authority_change",
    }
    if set(authority_changes) != expected_authority_keys:
        raise RuntimeError("R6_4_DESCENDANT_AUTHORITY_CHANGE_KEYS")
    if any(authority_changes[key] != "NO" for key in expected_authority_keys):
        raise RuntimeError("R6_4_DESCENDANT_AUTHORITY_EXPANSION")

    release = _load(RELEASE)
    artifacts = release.get("artifacts") or []
    release_paths = {row.get("path") for row in artifacts}
    if expected_paths & release_paths:
        raise RuntimeError("R6_4_DESCENDANT_OMISSIONS_REMAIN_IN_RELEASE")
    if DESCENDANT_CORRECTION not in release_paths:
        raise RuntimeError("R6_4_DESCENDANT_CORRECTION_NOT_IN_RELEASE")
    if release.get("artifact_count") != 53 or len(artifacts) != 53:
        raise RuntimeError("R6_4_DESCENDANT_RELEASE_COUNT")

    if contract.get("additional_manifest_identity_defect_count") != 1:
        raise RuntimeError("R6_4_DESCENDANT_MANIFEST_IDENTITY_DEFECT_COUNT")
    defects = contract.get("manifest_identity_defects") or []
    if len(defects) != 1:
        raise RuntimeError("R6_4_DESCENDANT_MANIFEST_IDENTITY_DEFECT_ROWS")
    defect = defects[0]
    expected_defect = {
        "path": INVENTORY_SERVICE_PATH,
        "original_manifest_size": INVENTORY_SERVICE_ORIGINAL_MANIFEST_SIZE,
        "original_manifest_sha256": INVENTORY_SERVICE_ORIGINAL_MANIFEST_SHA256,
        "actual_frozen_git_blob_canonical_lf_size": INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SIZE,
        "actual_frozen_git_blob_canonical_lf_sha256": INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SHA256,
        "source_drift": "NO",
        "historical_blob_count": 1,
        "original_manifest_hash_matching_blob_count": 0,
    }
    if defect != expected_defect:
        raise RuntimeError("R6_4_DESCENDANT_MANIFEST_IDENTITY_DEFECT_MISMATCH")
    if contract.get("descendant_artifact_size_basis") != "CANONICAL_LF_BYTES":
        raise RuntimeError("R6_4_DESCENDANT_SIZE_BASIS")
    if contract.get("descendant_artifact_hash_basis") != "CANONICAL_LF_SHA256":
        raise RuntimeError("R6_4_DESCENDANT_HASH_BASIS")

    frozen_inventory = _git_show_bytes(ORIGINAL_FREEZE_COMMIT, INVENTORY_SERVICE_PATH)
    frozen_inventory_canonical = frozen_inventory.replace(bytes((13, 10)), bytes((10,)))
    if len(frozen_inventory_canonical) != INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SIZE:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_FROZEN_SIZE")
    if hashlib.sha256(frozen_inventory_canonical).hexdigest() != INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SHA256:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_FROZEN_HASH")

    current_inventory = (ROOT / INVENTORY_SERVICE_PATH).read_bytes().replace(bytes((13, 10)), bytes((10,)))
    if len(current_inventory) != INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SIZE:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_SOURCE_SIZE_DRIFT")
    if hashlib.sha256(current_inventory).hexdigest() != INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SHA256:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_SOURCE_HASH_DRIFT")

    inventory_row = next((row for row in artifacts if row.get("path") == INVENTORY_SERVICE_PATH), None)
    if inventory_row is None:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_ROW_MISSING")
    if inventory_row.get("size") != INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SIZE:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_ROW_SIZE")
    if inventory_row.get("sha256") != INVENTORY_SERVICE_FROZEN_BLOB_CANONICAL_LF_SHA256:
        raise RuntimeError("R6_4_DESCENDANT_INVENTORY_ROW_HASH")

    return {
        "status": "PASS",
        "original_freeze_commit": ORIGINAL_FREEZE_COMMIT,
        "original_freeze_tag_target": tag_target,
        "historical_install_manifest_sha256": ORIGINAL_INSTALL_MANIFEST_SHA256,
        "historical_release_manifest_sha256": ORIGINAL_RELEASE_MANIFEST_SHA256,
        "historical_omission_count": len(omissions),
        "byte_identical_recovery_count": contract["byte_identical_recovery_count"],
        "deterministic_regeneration_count": contract["deterministic_regeneration_count"],
        "semantic_evidence_complete_count": sum(
            row.get("semantic_evidence") == "COMPLETE" for row in omissions
        ),
    }


def _verify_release_manifest(*, canonical_lf_identity: bool = False) -> int:
    data = _load(RELEASE)
    if data.get("self_excluded") is not True:
        raise RuntimeError("R6_4_RELEASE_SELF_EXCLUSION")
    artifacts = data.get("artifacts") or []
    if data.get("artifact_count") != len(artifacts):
        raise RuntimeError("R6_4_RELEASE_COUNT")
    for row in artifacts:
        p = ROOT / row["path"]
        if not p.is_file():
            raise RuntimeError("R6_4_RELEASE_MISSING=" + row["path"])
        raw = p.read_bytes()
        canonical = raw.replace(bytes((13, 10)), bytes((10,)))
        identity = canonical if canonical_lf_identity else raw
        if len(identity) != row["size"]:
            raise RuntimeError("R6_4_RELEASE_SIZE=" + row["path"])
        if hashlib.sha256(canonical).hexdigest() != row["sha256"]:
            raise RuntimeError("R6_4_RELEASE_HASH=" + row["path"])
    return len(artifacts)


def _static(*, descendant_freeze_integrity_correction: bool = False) -> dict[str, Any]:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    descendant_correction: dict[str, Any] | None = None
    if descendant_freeze_integrity_correction:
        descendant_correction = _verify_descendant_freeze_integrity_correction(head)
    else:
        if branch != EXPECTED_BRANCH:
            raise RuntimeError(f"R6_4_WRONG_BRANCH expected={EXPECTED_BRANCH} actual={branch}")
        if head != EXPECTED_HEAD:
            raise RuntimeError(f"R6_4_SOURCE_DRIFT expected={EXPECTED_HEAD} actual={head}")

    tag_target = _git("rev-parse", f"{R6_3_TAG}^{{}}")
    if tag_target != EXPECTED_HEAD:
        raise RuntimeError(f"R6_4_R6_3_TAG_DRIFT={tag_target}")

    authority = _load(AUTHORITY)
    if authority["source_checkpoint"] != EXPECTED_HEAD:
        raise RuntimeError("R6_4_AUTHORITY_SOURCE_DRIFT")
    if authority["source_archive_sha256"] != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("R6_4_SOURCE_SHA_DRIFT")
    if authority["source_archive_size"] != EXPECTED_SOURCE_SIZE:
        raise RuntimeError("R6_4_SOURCE_SIZE_DRIFT")
    if authority["production_write_authorized"] is not False:
        raise RuntimeError("R6_4_PRODUCTION_WRITE_AUTHORITY_LEAK")
    if authority["production_schema_migration_authorized"] is not False:
        raise RuntimeError("R6_4_PRODUCTION_SCHEMA_AUTHORITY_LEAK")
    if authority["writer_routing"] != "unchanged":
        raise RuntimeError("R6_4_WRITER_ROUTING_LEAK")
    if authority["legacy_writer_retirement_allowed"] is not False:
        raise RuntimeError("R6_4_RETIREMENT_AUTHORITY_LEAK")
    if authority["live_cutover_authorized"] is not False:
        raise RuntimeError("R6_4_LIVE_CUTOVER_AUTHORITY_LEAK")

    regression = authority.get("full_regression_safety") or {}
    if regression.get("production_database") != "xbos":
        raise RuntimeError("R6_4_REGRESSION_PRODUCTION_DB_DRIFT")
    if regression.get("disposable_regression_database") != "xbos_track_b_test":
        raise RuntimeError("R6_4_REGRESSION_DB_DRIFT")
    if regression.get("production_database_supplied_to_pytest") is not False:
        raise RuntimeError("R6_4_REGRESSION_PRODUCTION_DB_LEAK")
    if regression.get("database_restore_allowed") != ["xbos_track_b_test"]:
        raise RuntimeError("R6_4_REGRESSION_MUTATION_SCOPE_DRIFT")
    if regression.get("python_dont_write_bytecode") is not True:
        raise RuntimeError("R6_4_REGRESSION_BYTECODE_POLICY_DRIFT")

    runbook = _load(RUNBOOK)
    phase_ids = [p["id"] for p in runbook["phases"]]
    expected = [
        "P0_AUTHORIZATION", "P1_MAINTENANCE_ENTRY", "P2_FINAL_BACKUP",
        "P3_RESTORE_PROOF", "P4_LIVE_SCHEMA_ADOPTION", "P5_TRACK_B_RUNTIME",
        "P6_MAINTENANCE_VALIDATION", "P7_REOPEN", "P8_HYPERCARE_ENTRY"
    ]
    if phase_ids != expected:
        raise RuntimeError("R6_4_RUNBOOK_PHASE_DRIFT")
    if runbook["point_of_operational_commit"] != "first successful business write after P7 reopen":
        raise RuntimeError("R6_4_OPERATIONAL_COMMIT_BOUNDARY_DRIFT")
    if runbook["writer_retirement"] != "deferred until post-cutover hypercare acceptance":
        raise RuntimeError("R6_4_RETIREMENT_BOUNDARY_DRIFT")

    hyper = _load(HYPERCARE)
    if hyper["retirement_during_r6_5"] is not False:
        raise RuntimeError("R6_4_HYPERCARE_RETIREMENT_DRIFT")

    # R6.4 introduces no new production schema migration. The accepted R6.3
    # compatibility head remains the R6.5 migration target.
    if list((ROOT / "alembic_neutral/versions").glob("r64*")):
        raise RuntimeError("R6_4_NEW_SCHEMA_MIGRATION_FORBIDDEN")
    if list((ROOT / "alembic_neutral/sql").glob("r64*")):
        raise RuntimeError("R6_4_NEW_SCHEMA_SQL_FORBIDDEN")

    # Accepted R6.3 UAT remains immutable predecessor evidence.
    uat = _load("contracts/restaurant/v1/r6_3_visual_uat_evidence.json")
    if uat.get("status") != "PASS" or uat.get("candidate_head") != TARGET_HEAD:
        raise RuntimeError("R6_4_R6_3_UAT_EVIDENCE_DRIFT")

    return {
        "status": "PASS",
        "branch": branch,
        "head": head,
        "r6_3_tag": R6_3_TAG,
        "release_artifacts": _verify_release_manifest(
            canonical_lf_identity=descendant_freeze_integrity_correction
        ),
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
        "descendant_freeze_integrity_correction": descendant_correction,
    }


def _find_baseline() -> tuple[Path, dict[str, Any], Path]:
    pointer = DOWNLOADS / "XBOS_R6_4_LATEST_PLANNING_BASELINE.txt"
    candidates = []
    if pointer.is_file():
        raw = pointer.read_text(encoding="utf-8", errors="replace").strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend(sorted(
        DOWNLOADS.glob("WND_R6_4_PLANNING_BASELINE_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ))
    seen = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("contract") != "R6_4_WND_FRESH_PRODUCTION_PLANNING_BASELINE":
            continue
        if data.get("source_checkpoint") != EXPECTED_HEAD:
            continue
        if data.get("production_head") != r61.SOURCE_REVISION:
            continue
        backup = Path(data["backup"]["path"])
        if not backup.is_file():
            continue
        if backup.stat().st_size != int(data["backup"]["size"]):
            continue
        if _sha(backup).lower() != str(data["backup"]["sha256"]).lower():
            continue
        return path, data, backup
    raise RuntimeError(
        "R6_4_FRESH_PLANNING_BASELINE_NOT_FOUND. Run XBOS_R6_4_CAPTURE_PLANNING_BASELINE.cmd first."
    )


def _prepare_harness() -> None:
    r61.SOURCE_DATABASE = SOURCE_DB
    r61.CANDIDATE_DATABASE = CANDIDATE_DB
    r61.DISPOSABLE_DATABASES = DISPOSABLE

    r63.SOURCE_DATABASE = SOURCE_DB
    r63.CANDIDATE_DATABASE = CANDIDATE_DB
    r63.DISPOSABLE_DATABASES = DISPOSABLE
    r63.WORKSPACE = WORKSPACE / "reference_app"


def _engine(name: str):
    _prepare_harness()
    return r61._database_engine(name)


def _controls(name: str) -> tuple[str, dict[str, int], dict[str, Any]]:
    e = _engine(name)
    try:
        return (
            r61._current_head(e),
            r61._counts(e),
            r61._control_totals(e),
        )
    finally:
        e.dispose()


def _restore(name: str, backup: Path) -> None:
    _prepare_harness()
    r61._restore(name, backup)


def _adopt() -> dict[str, Any]:
    _prepare_harness()
    # Proven R6.1 adoption through R2.
    r61._adopt_candidate()
    # Accepted R6.3 compatibility head.
    with r61._database_environment(CANDIDATE_DB):
        command.upgrade(r61._alembic_config(CANDIDATE_DB), TARGET_HEAD)
    # Existing WND tenant composition.
    return r61._register_and_compose_candidate()


def _fingerprint(name: str, composition: dict[str, Any]) -> CutoverFingerprint:
    head, counts, totals = _controls(name)
    return CutoverFingerprint(head, counts, totals, composition)


def _port_free(port: int) -> bool:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _select_free_port(candidates: tuple[int, ...], label: str) -> int:
    for port in candidates:
        if _port_free(port):
            return port
    raise RuntimeError(
        f"R6_4_NO_FREE_{label}_PORT candidates={','.join(str(p) for p in candidates)}"
    )


def _track_b_env() -> dict[str, str]:
    _prepare_harness()
    env = os.environ.copy()
    env["DATABASE_URL"] = r61._database_url().set(database=CANDIDATE_DB).render_as_string(hide_password=False)
    env["GATEWAY_API_KEY"] = "R6_4_REHEARSAL_ONLY"
    env["JWT_SECRET"] = r63.EPHEMERAL_JWT_SECRET
    env["JWT_ALGORITHM"] = "HS256"
    env["ENV"] = "development"
    env["DEV_TENANT_CODE"] = "CM001"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _track_b_openapi() -> dict[str, Any]:
    output = WORKSPACE / "track_b_openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "import json,pathlib; from restaurant.r6 import wnd_compat_runtime as runtime; "
        f"pathlib.Path(r'{str(output)}').write_text(json.dumps(runtime.app.openapi(),sort_keys=True),encoding='utf-8')"
    )
    cp = _run(
        [sys.executable, "-X", "utf8", "-c", script],
        cwd=ROOT,
        env=_track_b_env(),
        capture_output=True,
        timeout=120,
    )
    if cp.returncode:
        raise RuntimeError("R6_4_TRACK_B_OPENAPI_FAILED\n" + (cp.stdout or "") + "\n" + (cp.stderr or ""))
    schema = json.loads(output.read_text(encoding="utf-8"))
    r63.assert_required_routes(schema, _load(REFERENCE)["required_openapi_routes"])
    bridge = _load(ROOT / "contracts/restaurant/v1/r6_4_wnd_api_compatibility_bridge.json")
    r63.assert_required_routes(schema, bridge["track_a_only_routes"])
    return schema


def _track_b_runtime_read_smoke(port: int) -> dict[str, int]:
    if not _port_free(port):
        raise RuntimeError(f"R6_4_TRACK_B_SELECTED_PORT_{port}_BECAME_UNAVAILABLE")

    log_path = WORKSPACE / "track_b_runtime.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [
                sys.executable, "-X", "utf8", "-m", "uvicorn", "restaurant.r6.wnd_compat_runtime:app",
                "--host", "127.0.0.1", "--port", str(port),
            ],
            cwd=ROOT,
            env=_track_b_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.time() + 60
            while time.time() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("R6_4_TRACK_B_RUNTIME_EXITED_EARLY")
                try:
                    status, _ = r63._http_json(
                        f"http://127.0.0.1:{port}/health", timeout=2
                    )
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("R6_4_TRACK_B_HEALTH_TIMEOUT")

            engine = _engine(CANDIDATE_DB)
            try:
                with engine.connect() as c:
                    user_id = c.execute(
                        text("SELECT id FROM users WHERE tenant_id=:t ORDER BY id LIMIT 1"),
                        {"t": r61.PRODUCTION_TENANT_ID},
                    ).scalar_one()
            finally:
                engine.dispose()

            now = int(time.time())
            token = r63._jwt({
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
            for path in _load(REFERENCE)["representative_read_smoke"]:
                status, body = r63._http_json(
                    f"http://127.0.0.1:{port}{path}",
                    token=token,
                    timeout=30,
                )
                statuses[path] = status
                if status != 200:
                    raise RuntimeError(
                        f"R6_4_TRACK_B_READ_FAILED path={path} status={status} body={body}"
                    )
            return statuses
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def _fresh_rehearsal(baseline_path: Path, baseline: dict[str, Any], backup: Path) -> dict[str, Any]:
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir(parents=True)

    _restore(SOURCE_DB, backup)
    source_head, source_counts, source_totals = _controls(SOURCE_DB)
    if source_head != r61.SOURCE_REVISION:
        raise RuntimeError(f"R6_4_SOURCE_HEAD_DRIFT={source_head}")

    _restore(CANDIDATE_DB, backup)
    raw_head, raw_counts, raw_totals = _controls(CANDIDATE_DB)
    if raw_head != source_head or raw_counts != source_counts:
        raise RuntimeError("R6_4_RAW_RESTORE_PARITY_FAILED")
    assert_legacy_truth_preserved(source_counts, raw_counts, source_totals, raw_totals)

    composition1 = _adopt()
    head1, counts1, totals1 = _controls(CANDIDATE_DB)
    if head1 != TARGET_HEAD:
        raise RuntimeError(f"R6_4_CANDIDATE_HEAD={head1}")
    assert_legacy_truth_preserved(source_counts, counts1, source_totals, totals1)
    fp1 = _fingerprint(CANDIDATE_DB, composition1).digest()

    # Recovery/replay proof against the exact fresh planning backup.
    _restore(CANDIDATE_DB, backup)
    composition2 = _adopt()
    head2, counts2, totals2 = _controls(CANDIDATE_DB)
    assert_legacy_truth_preserved(source_counts, counts2, source_totals, totals2)
    fp2 = _fingerprint(CANDIDATE_DB, composition2).digest()
    if fp1 != fp2:
        raise RuntimeError(f"R6_4_RECOVERY_REPLAY_FINGERPRINT_MISMATCH {fp1} != {fp2}")

    # Fresh-data compatibility against the exact accepted Track A application.
    _prepare_harness()
    bundle = r63._find_reference_inputs()
    r63._verify_reference_inputs(bundle)
    backend_dir, _ = r63._extract_reference_workspace(bundle)
    ref_openapi = r63._openapi_from_reference_backend(backend_dir)
    legacy_probe = r63._legacy_inventory_writer_probe(backend_dir)

    reference_port = _select_free_port(REFERENCE_PORT_CANDIDATES, "REFERENCE")
    original_r63_backend_port = r63.BACKEND_PORT
    r63.BACKEND_PORT = reference_port
    try:
        ref_reads = r63._runtime_smoke(backend_dir)
    finally:
        r63.BACKEND_PORT = original_r63_backend_port

    # The Track B runtime that R6.5 would deploy must preserve the same WND API
    # contract on the same fresh candidate.
    track_b_port = _select_free_port(TRACK_B_PORT_CANDIDATES, "TRACK_B")
    track_b_openapi = _track_b_openapi()
    track_b_probe = r63._legacy_inventory_writer_probe(ROOT)
    track_b_reads = _track_b_runtime_read_smoke(track_b_port)

    final_head, final_counts, final_totals = _controls(CANDIDATE_DB)
    assert_legacy_truth_preserved(source_counts, final_counts, source_totals, final_totals)

    return {
        "status": "PASS",
        "baseline_evidence": str(baseline_path),
        "planning_backup": str(backup),
        "planning_backup_sha256": baseline["backup"]["sha256"],
        "planning_backup_size": baseline["backup"]["size"],
        "source_head": source_head,
        "candidate_head": final_head,
        "source_counts": source_counts,
        "source_totals": {k: str(v) for k, v in source_totals.items()},
        "candidate_fingerprint": fp2,
        "recovery_replay": "PASS",
        "reference_backend_openapi_paths": len(ref_openapi.get("paths") or {}),
        "reference_backend_reads": ref_reads,
        "reference_backend_legacy_writer_probe": legacy_probe,
        "reference_backend_diagnostic_port": reference_port,
        "track_b_runtime_entrypoint": "restaurant.r6.wnd_compat_runtime:app",
        "track_b_openapi_paths": len(track_b_openapi.get("paths") or {}),
        "track_b_reads": track_b_reads,
        "track_b_diagnostic_port": track_b_port,
        "track_b_legacy_writer_probe": track_b_probe,
        "production_database_touched": False,
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "live_cutover_authorized": False,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--descendant-freeze-integrity-correction", action="store_true")
    args = parser.parse_args()

    if args.acceptance and args.descendant_freeze_integrity_correction:
        raise RuntimeError("R6_4_DESCENDANT_CORRECTION_ACCEPTANCE_MODE_FORBIDDEN")

    static = _static(
        descendant_freeze_integrity_correction=args.descendant_freeze_integrity_correction
    )
    if not args.acceptance:
        print(json.dumps(static, indent=2, sort_keys=True))
        print("R6_4_STATIC_VERIFY=PASS")
        return 0

    baseline_path, baseline, backup = _find_baseline()
    rehearsal = _fresh_rehearsal(baseline_path, baseline, backup)
    result = {
        "static": static,
        "rehearsal": rehearsal,
        "rollback_before_reopen": rollback_mode(reopened=False, post_cutover_business_write=False),
        "rollback_after_first_write": rollback_mode(reopened=True, post_cutover_business_write=True),
        "r6_5_operating_mode": _load(AUTHORITY)["r6_5_operating_mode"],
        "r6_5_live_cutover_authorized": False,
        "r6_5_readiness": True,
        "status": "PASS",
    }
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    print("R6_4_FRESH_PRODUCTION_REHEARSAL=PASS")
    print("R6_4_TRACK_A_ROLLBACK_COMPATIBILITY=PASS")
    print("R6_4_TRACK_B_RUNTIME_COMPATIBILITY=PASS")
    print("R6_4_RECOVERY_RESTORE_REPLAY=PASS")
    print("R6_4_PRODUCTION_WRITES=NONE")
    print("R6_4_PRODUCTION_WRITER_ROUTING=UNCHANGED")
    print("R6_4_LEGACY_WRITER_RETIREMENT=DEFERRED_TO_POST_HYPERCARE")
    print("R6_4_LIVE_CUTOVER_AUTHORIZED=NO")
    print("R6_4_R6_5_READINESS=PASS")
    print("R6_4_SINGLE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
