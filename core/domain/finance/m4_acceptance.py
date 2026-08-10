"""Static release-manifest and migration-lineage authority for the M4 freeze."""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_HEAD = "m46_provider_financials_015"
EXPECTED_LINEAGE = (
    "m13_source_state_001",
    "m13_financial_foundation_002",
    "m20_event_catalog_003",
    "m22_transactional_delivery_004",
    "m23_reversal_capacity_005",
    "m24_balanced_posting_006",
    "m25_financial_dimensions_007",
    "m30_obligation_foundation_008",
    "m32_allocation_engine_009",
    "m34_obligation_aging_010",
    "m40_payment_foundation_011",
    "m42_payment_attempts_012",
    "m43_payment_settlements_013",
    "m44_payment_patterns_014",
    "m46_provider_financials_015",
)


class M4AcceptanceError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ManifestCheck:
    checked_components: int
    canonical_head: str
    lineage: tuple[str, ...]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def semantic_sha256(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M4AcceptanceError("invalid_contract_json", str(path)) from exc
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _literal_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def live_migration_lineage(root: Path) -> tuple[str, ...]:
    parents: dict[str, str | None] = {}
    for path in sorted((root / "alembic_neutral" / "versions").glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = _literal_assignment(tree, "revision")
            parent = _literal_assignment(tree, "down_revision")
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            raise M4AcceptanceError("invalid_migration_source", str(path)) from exc
        if not revision or revision in parents:
            raise M4AcceptanceError("invalid_migration_revision", str(path))
        parents[revision] = parent
    heads = set(parents) - {parent for parent in parents.values() if parent is not None}
    if len(heads) != 1:
        raise M4AcceptanceError("unexpected_migration_heads", repr(sorted(heads)))
    ordered: list[str] = []
    current: str | None = next(iter(heads))
    while current is not None:
        if current not in parents:
            raise M4AcceptanceError("broken_migration_lineage", current)
        ordered.append(current)
        current = parents[current]
    ordered.reverse()
    return tuple(ordered)


def validate_release_manifest(root: Path) -> ManifestCheck:
    path = root / "contracts" / "finance" / "v1" / "m4_release_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M4AcceptanceError("invalid_release_manifest", str(path)) from exc
    if manifest.get("baseline_code") != "XBOS_M4_PAYMENTS_SETTLEMENT_ORCHESTRATION_RELEASE":
        raise M4AcceptanceError("unexpected_release_manifest", "baseline_code")
    if manifest.get("canonical_head") != EXPECTED_HEAD:
        raise M4AcceptanceError("unexpected_manifest_head", repr(manifest.get("canonical_head")))
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 7:
        raise M4AcceptanceError("unexpected_manifest_components", repr(components))
    for sequence, component in enumerate(components, 1):
        if component.get("sequence") != sequence:
            raise M4AcceptanceError("invalid_component_sequence", repr(component))
        relative = component.get("path")
        expected = component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise M4AcceptanceError("invalid_component_record", repr(component))
        actual = semantic_sha256(root / relative)
        if actual != expected:
            raise M4AcceptanceError("semantic_fingerprint_mismatch", f"{relative}: expected {expected}, found {actual}")
    lineage = live_migration_lineage(root)
    if lineage != EXPECTED_LINEAGE:
        raise M4AcceptanceError("unexpected_migration_lineage", repr(lineage))
    if tuple(manifest.get("canonical_migration_lineage", ())) != EXPECTED_LINEAGE:
        raise M4AcceptanceError("manifest_lineage_mismatch", "canonical_migration_lineage")
    if tuple((root / "alembic_neutral" / "versions").glob("m47_*.py")):
        raise M4AcceptanceError("unexpected_m4_closure_migration", "M4.7 must not add a migration")
    return ManifestCheck(len(components), EXPECTED_HEAD, lineage)
