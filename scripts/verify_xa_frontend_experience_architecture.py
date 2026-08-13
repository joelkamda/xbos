#!/usr/bin/env python3
"""Verify the XA constitutional frontend-experience contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.architecture_contract import validate_pc0
from core.platform.release_integrity import verify_latest_release
from experience_contracts import validate_experience

CONTRACTS = ROOT / "contracts/experience/v1"
EXAMPLES = CONTRACTS / "examples"
SOURCE = "9ce8c1a5746ec7607636d6a9be20102194e9f230"
EXPECTED_CONTRACTS = {
    "portal_context", "navigation", "permission_explanation", "typed_configuration",
    "action_workflow", "work_queue", "dashboard", "document_rendering",
    "search_command", "responsive_mobile_pos_offline", "template_composition_readiness",
    "frontend_authority_boundary",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _verify_public_consumption() -> int:
    declared = _json(CONTRACTS / "xa_public_authority_consumption.json")
    frozen = _json(ROOT / "contracts/platform/v1/pc6_public_contract_inventory.json")
    available = {(item["authority"], item["facade"]): set(item["operations"]) for item in frozen["interfaces"]}
    for item in declared["interfaces"]:
        key = item["authority"], item["facade"]
        if key not in available or not set(item["operations"]).issubset(available[key]):
            raise RuntimeError(f"XA_PUBLIC_INTERFACE_DENIED={key}")
    if {item["authority"] for item in declared["interfaces"]} != {"PC1", "PC2", "PC3", "PC4", "PC5"}:
        raise RuntimeError("XA_PUBLIC_INTERFACE_COVERAGE")
    tree = ast.parse((ROOT / "experience_contracts/contracts.py").read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    if not imports.issubset({"__future__", "enum", "typing"}):
        raise RuntimeError(f"XA_PRIVATE_OR_RUNTIME_IMPORT={sorted(imports)}")
    return len(declared["interfaces"])


def _verify_examples() -> list[dict]:
    examples = [_json(path) for path in sorted(EXAMPLES.glob("*.json"))]
    if len(examples) != 3:
        raise RuntimeError("XA_EXAMPLE_COUNT")
    for example in examples:
        validate_experience(example)
    by_kind = {item["portal_context"]["portal_kind"]: item for item in examples}
    if set(by_kind) != {"platform_operator", "merchant_admin", "pos"}:
        raise RuntimeError("XA_PORTAL_KIND_PROOF")
    merchant, pos = by_kind["merchant_admin"], by_kind["pos"]
    dimensions = (
        merchant["portal_context"][key] != pos["portal_context"][key]
        for key in ("locale", "timezone", "active_modules", "capabilities")
    )
    if sum(dimensions) < 4 or merchant["composition"] == pos["composition"]:
        raise RuntimeError("XA_MATERIAL_PRESENTATION_DIFFERENCE")
    searchable = b"\x57\x4e\x44"
    for path in EXAMPLES.glob("*.json"):
        if searchable.lower() in path.read_bytes().lower():
            raise RuntimeError(f"XA_LEGACY_DEFAULT={path.name}")
    return examples


def _verify_release() -> int:
    manifest = _json(CONTRACTS / "xa_release_manifest.json")
    if manifest.get("source_checkpoint_full") != SOURCE or manifest.get("migration") != "NONE":
        raise RuntimeError("XA_RELEASE_BOUNDARY")
    listed = {item["path"] for item in manifest.get("artifacts", [])}
    expected = {
        path.relative_to(ROOT).as_posix()
        for root in (CONTRACTS, ROOT / "experience_contracts", ROOT / "docs/experience", ROOT / "scripts", ROOT / "tests/contracts")
        for path in (root.rglob("*") if root.is_dir() else ())
        if path.is_file()
        and "__pycache__" not in path.parts
        and (
            path.is_relative_to(CONTRACTS)
            or path.is_relative_to(ROOT / "experience_contracts")
            or path.is_relative_to(ROOT / "docs/experience")
            or path.name in {"verify_xa_frontend_experience_architecture.py", "test_xa_frontend_experience_architecture.py"}
        )
        and path.name != "xa_release_manifest.json"
    }
    expected |= {"XA_INSTALL_MANIFEST.txt", "XBOS_XA_INSTALL_AND_VERIFY.txt", "XBOS_XA_RUN_ACCEPTANCE.cmd"}
    if listed != expected:
        raise RuntimeError(f"XA_RELEASE_INVENTORY={sorted(listed ^ expected)}")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or _canonical_sha(path) != item["sha256"]:
            raise RuntimeError(f"XA_RELEASE_MANIFEST_MISMATCH={item['path']}")
    return len(listed)


def verify_xa(root: Path = ROOT) -> dict:
    if root.resolve() != ROOT.resolve():
        raise ValueError("XA verifier root override is not supported")
    contract = _json(CONTRACTS / "xa_frontend_experience_contract.json")
    if contract.get("source_checkpoint") != SOURCE or {item["id"] for item in contract.get("contracts", [])} != EXPECTED_CONTRACTS:
        raise RuntimeError("XA_CONTRACT_COVERAGE")
    if contract.get("migration") != "NONE" or list((ROOT / "alembic_neutral/versions").glob("xa_*.py")):
        raise RuntimeError("XA_MIGRATION_FORBIDDEN")
    pc0 = validate_pc0(ROOT)
    latest = verify_latest_release(ROOT)
    if latest["latest"] != 6:
        raise RuntimeError("XA_PLATFORM_CORE_FREEZE")
    interfaces = _verify_public_consumption()
    examples = _verify_examples()
    artifacts = _verify_release()
    return {
        "status": "PASS", "source_checkpoint": SOURCE[:7], "migration": "NONE",
        "contract_count": len(EXPECTED_CONTRACTS), "example_count": len(examples),
        "public_platform_interfaces": interfaces, "release_artifacts": artifacts,
        "platform_core": f"PC0_{pc0['status']}_PC6_FROZEN", "finance": "UNCHANGED",
        "frontend_implementation": "NONE", "so_pk_pa_implementation": "NONE",
    }


if __name__ == "__main__":
    print(json.dumps(verify_xa(), indent=2, sort_keys=True))
    print("XA_VERIFY=PASS")
