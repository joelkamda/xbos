"""Independent prospective PC0 successor verifier: no legacy PC0 modifications.

This proves candidate source ownership and default-deny imports. It DOES NOT
supersede historical PC0 CI, mount any router, or admit runtime deployment.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path

CONTRACT_REL = "contracts/platform/v2/pc0_local_first_restaurant_successor.json"
EXPECTED_SCHEMA = "xbos.platform.pc0-local-first-restaurant-successor.v2"
FIXED_ROOTS = ["core/api/restaurant", "core/domain/restaurant"]
FIXED_FILES = {
    "core/api/restaurant/local_first_lan_router.py",
    "core/domain/restaurant/local_first_shift_session.py",
    "core/domain/restaurant/local_first_stock_draft.py",
    "core/domain/restaurant/local_first_receipt_service.py",
}
# Independent compile-time pins prevent mutating both a v1 file and JSON to
# disguise historical drift. These constants are part of this proposed gate.
PINNED_FROZEN_PC0 = {'contracts/platform/v1/pc0_dependency_policy.json': '299de659767a13b67d925b76fd37e1a410affa321f43b0b5d39f59063b32183a', 'contracts/platform/v1/pc0_module_map.json': '8ee2b0f1f706306f42f7023a99e10400c8f538b31d2ef6be87c8563a864e8e23', 'core/platform/architecture_contract.py': 'ddf14884560c56c9813481e8dfbb922f0a9a4206a1b7c75fe75682529567764f', 'tests/contracts/test_pc0_kernel_boundaries.py': '7b60eb4fa4efe4ac82b2808873e407179819088ef9087ac876f27e7e4df4f2a8'}
PINNED_W_SOURCE = {'core/api/restaurant/local_first_lan_router.py': '7f4487999ffccab39291930394f70351ef3bf4561cd88f518a1ededd108386f2', 'core/domain/restaurant/local_first_receipt_service.py': '2eb91ba58b504eece152fd743fc77cf262a187106431b091a74417e42a8f2881', 'core/domain/restaurant/local_first_shift_session.py': '77b5f89885dfcc0e4da3e8a3a3b6f3ae4f3437763c5064f9e1a825d5858bf385', 'core/domain/restaurant/local_first_stock_draft.py': 'abffd9e3332a08e42d70c620ce9e61e7906ea51d6219938d81ffc0cfb075489b'}
FROZEN_PATHS = set(PINNED_FROZEN_PC0)

class ProspectivePC0Denied(ValueError):
    pass

def _fail(code: str) -> None:
    raise ProspectivePC0Denied(code)

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_local_first_restaurant_successor(repo_root: Path) -> dict:
    """Inspect source only. Fail on source drift, unknown ownership or imports."""
    root = Path(repo_root)
    try:
        contract = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProspectivePC0Denied("SUCCESSOR_CONTRACT_UNREADABLE") from exc

    if (contract.get("schema") != EXPECTED_SCHEMA or contract.get("version") != 2
        or contract.get("admission") != "PROSPECTIVE_SOURCE_ONLY"
        or contract.get("certification") != "SOURCE_CONTRACT_TESTS_ONLY_NOT_RUNTIME_ADMISSION"):
        _fail("UNAUTHORIZED_SUCCESSOR_OR_RUNTIME_ADMISSION")
    historical = contract.get("historical_pc0_sha256")
    if not isinstance(historical, dict) or historical != PINNED_FROZEN_PC0:
        _fail("HISTORICAL_PC0_INVENTORY_DRIFT")
    for rel, expected in historical.items():
        path = root / rel
        if not path.is_file() or _sha(path) != expected:
            _fail("HISTORICAL_PC0_MODIFIED")
    try:
        frozen_map = json.loads((root / "contracts/platform/v1/pc0_module_map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProspectivePC0Denied("FROZEN_MODULE_MAP_UNREADABLE") from exc
    known = {m["code"] for m in frozen_map["modules"]}
    roots = {src for mod in frozen_map["modules"] for src in mod["source_roots"]}
    mod = contract.get("module")
    if not isinstance(mod, dict) or (
        mod.get("code") != "restaurant_local"
        or mod.get("owner") != "W / Restaurant Pack"
        or mod.get("kind") != "local_operational"
        or mod.get("source_roots") != FIXED_ROOTS):
        _fail("RESTAURANT_MODULE_OWNER_DRIFT")
    if mod["code"] in known or any(
        f == r or f.startswith(r+"/") or r.startswith(f+"/")
        for f in FIXED_ROOTS for r in roots
    ):
        _fail("FROZEN_PC0_OWNERSHIP_COLLISION")
    src = mod.get("source_files")
    if not isinstance(src, dict) or set(src) != FIXED_FILES:
        _fail("RESTAURANT_SOURCE_SCOPE_CHANGED")
    if src != PINNED_W_SOURCE:
        _fail("RESTAURANT_SOURCE_PROVENANCE_DRIFT")
    policy = contract.get("dependency_policy")
    if not isinstance(policy,dict) or (
        policy.get("default") != "deny" or policy.get("wildcard_exceptions") is not False
        or policy.get("allowed_internal_imports") != []
        or policy.get("independent_injected_authorities") !=
          ["server_verified_pc5", "server_verified_epoch", "server_verified_finance_readback"]):
        _fail("PROSPECTIVE_DEPENDENCY_LAW_WEAKENED")
    if contract.get("out_of_scope") != [
        "NO_LIVE_PC0_GATE_REPLACEMENT", "NO_GITHUB_RULESET_CHANGE",
        "NO_ROUTER_MOUNT", "NO_PG17_MIGRATION", "NO_KEY_SIGNING",
        "NO_WND_PRODUCTION"]:
        _fail("PROSPECTIVE_OPERATIVE_BOUNDARY_CHANGED")

    for name in FIXED_ROOTS:
        folder = root / name
        if not folder.is_dir():
            _fail("MISSING_RESTAURANT_MODULE_ROOT")
        actual = {p.relative_to(root).as_posix() for p in folder.rglob("*.py")}
        if actual - FIXED_FILES:
            _fail("NEW_RESTAURANT_SOURCE_UNREVIEWED")
    for rel, expected in src.items():
        path = root/rel
        if not path.is_file() or _sha(path) != expected:
            _fail("RESTAURANT_SOURCE_HASH_DRIFT")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeError) as exc:
            raise ProspectivePC0Denied("RESTAURANT_INVALID_SOURCE") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    _fail("RESTAURANT_RELATIVE_IMPORT_UNREVIEWED")
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                # Pure standard-library imports only in prospective source;
                # later production dependencies require an explicit successor revision.
                if module not in {"dataclasses", "typing"}:
                    _fail("RESTAURANT_DIRECT_IMPORT_UNAUTHORIZED")
    return {
        "status": "PROSPECTIVE_SOURCE_QUALIFIED_NOT_HOSTED",
        "historical_pc0_intact": True,
        "module": "restaurant_local",
        "files": sorted(FIXED_FILES),
        "real_postgres_or_offline_certified": False,
    }
