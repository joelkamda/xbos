"""Static release-manifest and lineage authority for the M3 freeze."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_HEAD = "m34_obligation_aging_010"
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
)


class M3AcceptanceError(RuntimeError):
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
        raise M3AcceptanceError("invalid_contract_json", str(path)) from exc
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _literal_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def live_migration_lineage(root: Path) -> tuple[str, ...]:
    """Return the repository's complete single canonical lineage."""

    parents: dict[str, str | None] = {}
    for path in sorted((root / "alembic_neutral/versions").glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = _literal_assignment(tree, "revision")
            parent = _literal_assignment(tree, "down_revision")
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            raise M3AcceptanceError("invalid_migration_source", str(path)) from exc
        if not revision:
            raise M3AcceptanceError("missing_migration_revision", str(path))
        if revision in parents:
            raise M3AcceptanceError("duplicate_migration_revision", revision)
        parents[revision] = parent
    heads = set(parents) - {parent for parent in parents.values() if parent is not None}
    if len(heads) != 1:
        raise M3AcceptanceError("unexpected_migration_heads", repr(sorted(heads)))
    ordered: list[str] = []
    current: str | None = next(iter(heads))
    while current is not None:
        if current not in parents:
            raise M3AcceptanceError("broken_migration_lineage", current)
        ordered.append(current)
        current = parents[current]
    ordered.reverse()
    return tuple(ordered)


def repository_migration_lineage(root: Path) -> tuple[str, ...]:
    """Return and validate the immutable M3 prefix of the live lineage.

    The approved M3 head is a release checkpoint, not a permanent repository
    head. Later milestones may extend the same lineage, but may not alter,
    bypass, fork, or reorder the frozen M3 prefix.
    """

    lineage = live_migration_lineage(root)
    try:
        checkpoint_index = lineage.index(EXPECTED_HEAD)
    except ValueError as exc:
        raise M3AcceptanceError("missing_m3_migration_checkpoint", EXPECTED_HEAD) from exc
    frozen_prefix = lineage[: checkpoint_index + 1]
    if frozen_prefix != EXPECTED_LINEAGE:
        raise M3AcceptanceError("unexpected_migration_lineage", repr(frozen_prefix))
    return frozen_prefix


def revision_preserves_m3_checkpoint(root: Path, revision: str | None) -> bool:
    """Return whether a database revision is M3 itself or a linear descendant."""

    if revision is None:
        return False
    lineage = live_migration_lineage(root)
    try:
        return lineage.index(revision) >= lineage.index(EXPECTED_HEAD)
    except ValueError:
        return False


def validate_static_boundaries(root: Path) -> None:
    versions = root / "alembic_neutral/versions"
    forbidden = tuple(versions.glob("m35_*.py")) + tuple(versions.glob("m36_*.py"))
    if forbidden:
        raise M3AcceptanceError("unexpected_m3_closure_migration", ",".join(path.name for path in forbidden))
    required_verifiers = tuple(root / "scripts" / f"verify_m3{n}_{suffix}.py" for n, suffix in (
        (0, "obligation_foundation"),
        (1, "typed_obligation_lifecycle_balances"),
        (2, "allocation_engine"),
        (3, "value_application_workflows"),
        (4, "obligation_aging"),
        (5, "obligation_settlement_trace"),
    ))
    missing = tuple(path for path in required_verifiers if not path.is_file())
    if missing:
        raise M3AcceptanceError("missing_capability_verifier", ",".join(path.name for path in missing))


def validate_release_manifest(root: Path) -> ManifestCheck:
    path = root / "contracts/finance/v1/m3_release_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M3AcceptanceError("invalid_release_manifest", str(path)) from exc
    if manifest.get("baseline_code") != "XBOS_M3_OBLIGATIONS_BALANCES_ALLOCATIONS_RELEASE":
        raise M3AcceptanceError("unexpected_release_manifest", "baseline_code")
    if manifest.get("canonical_head") != EXPECTED_HEAD:
        raise M3AcceptanceError("unexpected_manifest_head", repr(manifest.get("canonical_head")))
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 6:
        raise M3AcceptanceError("unexpected_manifest_components", repr(components))
    for sequence, component in enumerate(components, start=1):
        if component.get("sequence") != sequence:
            raise M3AcceptanceError("invalid_component_sequence", repr(component))
        relative = component.get("path")
        expected_hash = component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise M3AcceptanceError("invalid_component_record", repr(component))
        actual_hash = semantic_sha256(root / relative)
        if actual_hash != expected_hash:
            raise M3AcceptanceError("semantic_fingerprint_mismatch", f"{relative}: expected {expected_hash}, found {actual_hash}")
    lineage = repository_migration_lineage(root)
    if lineage != EXPECTED_LINEAGE:
        raise M3AcceptanceError("unexpected_migration_lineage", repr(lineage))
    if tuple(manifest.get("canonical_migration_lineage", ())) != EXPECTED_LINEAGE:
        raise M3AcceptanceError("manifest_lineage_mismatch", "canonical_migration_lineage")
    validate_static_boundaries(root)
    return ManifestCheck(len(components), EXPECTED_HEAD, lineage)
