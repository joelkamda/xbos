#!/usr/bin/env python3
"""Verify the SO0 Shared Operations constitutional foundation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.architecture_contract import validate_pc0
from core.platform.neutral_proof.dependency_authority import verify_dependency_authority
from core.platform.release_integrity import canonical_sha256, verify_latest_release
from scripts.verify_xa_frontend_experience_architecture import verify_xa
from shared_operations_contracts import evaluate_private_import, validate_module_declaration

CONTRACTS = ROOT / "contracts/shared_operations/v1"
SOURCE = "56cbbb8a220fe881fcceb05b4e217e0b6c79da3c"
HEAD = "pc5_identity_policy_audit_025"
MODULES = [f"SO{number}" for number in range(1, 11)]
DEPENDENCY_FINGERPRINTS = {
    "requirements-prod.txt": "d581097821755ae27c5899eaf0d06be52adbf05c2f4bab13b46872e87980fff5",
    "contracts/platform/v1/pc6_dependency_authority.json": "460012afe419380cb222a53b8238a3a51be31ba6a291c45481235438d83c1920",
}
ERRORS = {
    "validation_failure", "not_found", "scope_mismatch", "permission_denied",
    "approval_required", "step_up_required", "conflict", "stale_version",
    "unavailable_capability", "invalid_state_transition", "dependency_unavailable",
}
XA_HOOKS = {"navigation", "actions", "work_queue", "configuration", "dashboard", "documents", "search", "offline"}


def _json(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _canonical_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _verify_release() -> int:
    manifest = _json("so0_release_manifest.json")
    if (manifest.get("source_checkpoint_full"), manifest.get("migration"), manifest.get("accepted_head")) != (SOURCE, "NONE", HEAD):
        raise RuntimeError("SO0-RELEASE-BOUNDARY")
    expected = {
        path.relative_to(ROOT).as_posix()
        for base in (CONTRACTS, ROOT / "shared_operations_contracts", ROOT / "docs/shared_operations")
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.name != "so0_release_manifest.json"
    }
    expected |= {
        "SO0_INSTALL_MANIFEST.txt", "XBOS_SO0_INSTALL_AND_VERIFY.txt", "XBOS_SO0_RUN_ACCEPTANCE.cmd",
        "scripts/verify_so0_shared_operations.py", "tests/contracts/test_so0_shared_operations_constitution.py",
    }
    listed = {item["path"] for item in manifest.get("artifacts", [])}
    if listed != expected:
        raise RuntimeError(f"SO0-RELEASE-INVENTORY={sorted(listed ^ expected)}")
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        if not path.is_file() or _canonical_sha(path) != item["sha256"]:
            raise RuntimeError(f"SO0-RELEASE-MISMATCH={item['path']}")
    return len(listed)


def verify_dependency_fingerprints(root: Path) -> None:
    """Verify the exact PC6 authority using Git/archive canonical text bytes."""
    for relative, expected in DEPENDENCY_FINGERPRINTS.items():
        path = root / relative
        actual = canonical_sha256(path, relative_path=relative, repository_root=root) if path.is_file() else None
        if actual != expected:
            raise RuntimeError(f"SO0-PRODUCTION-DEPENDENCY-AUTHORITY-CHANGED={relative}")


def verify_production_dependency_authority(root: Path = ROOT) -> dict[str, object]:
    verify_dependency_fingerprints(root)
    contract = json.loads((root / "contracts/platform/v1/pc6_dependency_authority.json").read_text(encoding="utf-8"))
    report = verify_dependency_authority(root, contract)
    if report != {
        "status": "PASS", "pin_count": 14,
        "third_party_imports": ["alembic", "babel", "fastapi", "httpx", "jose", "passlib", "pycountry", "pydantic", "pydantic_settings", "pytz", "sqlalchemy", "starlette", "uvicorn"],
        "python": "3.13.3",
    }:
        raise RuntimeError(f"SO0-PRODUCTION-DEPENDENCY-AUTHORITY-RESULT={report}")
    return report


def verify_so0() -> dict:
    constitution = _json("so0_shared_operations_constitution.json")
    module_contract = _json("so0_module_contract.json")
    boundaries = _json("so0_public_private_boundaries.json")
    if (constitution.get("source_checkpoint"), constitution.get("migration"), constitution.get("accepted_head")) != (SOURCE, "NONE", HEAD):
        raise RuntimeError("SO0-SOURCE-OR-MIGRATION-BOUNDARY")
    domains = constitution.get("domains", [])
    codes = [item.get("code") for item in domains]
    owners = [item.get("owner") for item in domains]
    if codes != MODULES or len(owners) != len(set(owners)) or any(item.get("implementation_status") != "NOT_IMPLEMENTED" for item in domains):
        raise RuntimeError("SO0-DOMAIN-INVENTORY")
    authorities = {item["authority"] for item in constitution["external_authorities"]}
    if authorities != {"PC1", "PC2", "PC3", "PC4", "PC5", "Neutral Finance", "XA", "PK"}:
        raise RuntimeError("SO0-EXTERNAL-AUTHORITY-COVERAGE")
    if constitution["atomic_unit_boundary"]["canonical_future_owner"] != "SO1" or constitution["atomic_unit_boundary"]["SO0_persistence_change"] != "NONE":
        raise RuntimeError("SO0-ATOMIC-UNIT-BOUNDARY")
    delivery = constitution["delivery_boundary"]
    if not delivery["finance_retains"] or not delivery["SO8_future_scope"] or delivery["implementation"] != "NONE":
        raise RuntimeError("SO0-DELIVERY-FINANCE-BOUNDARY")
    if constitution["finance_boundary"]["equation"] != "operational_fact_not_equal_financial_event":
        raise RuntimeError("SO0-FACT-FINANCE-DISTINCTION")
    if set(module_contract["required_fields"]) != {
        "module_code", "name", "capability_codes", "public_commands", "public_queries", "operational_facts",
        "platform_authorities", "finance_integration_points", "required_permissions", "configuration_dependencies",
        "semantic_dependencies", "xa_hooks", "lifecycle", "pack_declaration_hooks", "ownership_classification",
    }:
        raise RuntimeError("SO0-MODULE-CONTRACT-COVERAGE")
    validate_module_declaration(module_contract["example"])
    if set(module_contract["error_contract"]["categories"]) != ERRORS or set(module_contract["field_law"]["xa_hooks"]["allowed"]) != XA_HOOKS:
        raise RuntimeError("SO0-ERROR-OR-XA-CONTRACT")
    if boundaries["wildcard_exceptions"] != "FORBIDDEN" or boundaries["future_module_dependency_declaration"] != "MANDATORY":
        raise RuntimeError("SO0-PUBLIC-PRIVATE-BOUNDARY")
    if evaluate_private_import("SO1", "shared_operations.SO2.repository.sql_repository") != "SO0-CROSS-MODULE-PRIVATE-IMPORT":
        raise RuntimeError("SO0-PRIVATE-IMPORT-ENFORCEMENT")
    if evaluate_private_import("SO1", "shared_operations.SO2.contracts.public") is not None:
        raise RuntimeError("SO0-PUBLIC-IMPORT-ENFORCEMENT")
    if list((ROOT / "alembic_neutral/versions").glob("so0_*.py")) or (ROOT / "core/shared_operations").exists():
        raise RuntimeError("SO0-FEATURE-OR-MIGRATION-IMPLEMENTATION")
    dependency = verify_production_dependency_authority(ROOT)
    active = [ROOT / "shared_operations_contracts", CONTRACTS]
    forbidden = (bytes((87, 78, 68)), b"Wine & Dine", b"Logpom")
    for base in active:
        for path in base.rglob("*"):
            if path.is_file() and path.name != "so0_release_manifest.json":
                data = path.read_bytes()
                if any(term.lower() in data.lower() for term in forbidden):
                    raise RuntimeError(f"SO0-ACTIVE-INDUSTRY-LEAKAGE={path.relative_to(ROOT)}")
    pc0 = validate_pc0(ROOT)
    pc6 = verify_latest_release(ROOT)
    xa = verify_xa()
    if pc6["latest"] != 6 or xa["status"] != "PASS":
        raise RuntimeError("SO0-FROZEN-UPSTREAM-CONTRACT")
    artifacts = _verify_release()
    return {
        "status": "PASS", "source_checkpoint": SOURCE[:7], "migration": "NONE",
        "domain_count": len(domains), "module_contract_fields": len(module_contract["required_fields"]),
        "error_codes": len(ERRORS), "xa_hooks": len(XA_HOOKS), "release_artifacts": artifacts,
        "platform_core": f"PC0_{pc0['status']}_PC6_FROZEN", "xa": "FROZEN_CONSUMED",
        "finance": "UNCHANGED", "dependency_authority": dependency, "dependency_changes": "NONE", "so1_plus_features": "NONE",
    }


if __name__ == "__main__":
    try:
        print(json.dumps(verify_so0(), indent=2, sort_keys=True))
        print("SO0_VERIFY=PASS")
    except Exception as exc:
        print(f"SO0_VERIFY=FAIL\n{exc}", file=sys.stderr)
        raise SystemExit(1)
