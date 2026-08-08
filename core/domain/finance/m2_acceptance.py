"""M2 release-manifest validation and static hardening checks."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXPECTED_HEAD = "m25_financial_dimensions_007"
EXPECTED_LINEAGE = (
    "m13_source_state_001",
    "m13_financial_foundation_002",
    "m20_event_catalog_003",
    "m22_transactional_delivery_004",
    "m23_reversal_capacity_005",
    "m24_balanced_posting_006",
    "m25_financial_dimensions_007",
)


class M2AcceptanceError(RuntimeError):
    """Raised when the frozen M2 release authority no longer matches the tree."""

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
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M2AcceptanceError("invalid_contract_json", str(path)) from exc
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_release_manifest(root: Path) -> dict[str, Any]:
    path = root / "contracts" / "finance" / "v1" / "m2_release_manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M2AcceptanceError("invalid_release_manifest", str(path)) from exc


def _literal_assignment(tree: ast.Module, name: str) -> str | None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    return None


def migration_lineage(root: Path) -> tuple[str, ...]:
    versions = root / "alembic_neutral" / "versions"
    parents: dict[str, str | None] = {}
    for path in sorted(versions.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = _literal_assignment(tree, "revision")
            parent = _literal_assignment(tree, "down_revision")
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            raise M2AcceptanceError("invalid_migration_source", str(path)) from exc
        if not revision:
            raise M2AcceptanceError("missing_migration_revision", str(path))
        if revision in parents:
            raise M2AcceptanceError("duplicate_migration_revision", revision)
        parents[revision] = parent

    heads = set(parents) - {parent for parent in parents.values() if parent is not None}
    if heads != {EXPECTED_HEAD}:
        raise M2AcceptanceError("unexpected_migration_heads", repr(sorted(heads)))

    ordered: list[str] = []
    current: str | None = EXPECTED_HEAD
    while current is not None:
        if current not in parents:
            raise M2AcceptanceError("broken_migration_lineage", current)
        ordered.append(current)
        current = parents[current]
    ordered.reverse()
    return tuple(ordered)


def validate_static_boundaries(root: Path) -> None:
    versions = root / "alembic_neutral" / "versions"
    forbidden_migrations = tuple(versions.glob("m26_*.py")) + tuple(
        versions.glob("m27_*.py")
    )
    if forbidden_migrations:
        raise M2AcceptanceError(
            "unexpected_m2_closure_migration",
            ",".join(path.name for path in forbidden_migrations),
        )

    finance_root = root / "core" / "domain" / "finance"
    for path in sorted(finance_root.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise M2AcceptanceError("invalid_finance_source", str(path)) from exc
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            for module in imported:
                legacy_prefixes = (
                    "core.api",
                    "core.domain.accounting",
                    "core.domain.inventory",
                    "core.domain.orders",
                    "core.domain.payments",
                    "core.domain.sales",
                )
                if module == "fastapi" or module.startswith("fastapi.") or module.startswith(legacy_prefixes):
                    raise M2AcceptanceError("framework_coupling_detected", f"{path.name}: {module}")


def validate_release_manifest(root: Path) -> ManifestCheck:
    manifest = load_release_manifest(root)
    if manifest.get("baseline_code") != "XBOS_M2_CANONICAL_EVENT_ENGINE_RELEASE":
        raise M2AcceptanceError("unexpected_release_manifest", "baseline_code")
    if manifest.get("canonical_head") != EXPECTED_HEAD:
        raise M2AcceptanceError("unexpected_manifest_head", repr(manifest.get("canonical_head")))

    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 20:
        raise M2AcceptanceError("unexpected_manifest_components", repr(components))
    for expected_sequence, component in enumerate(components, start=1):
        if component.get("sequence") != expected_sequence:
            raise M2AcceptanceError("invalid_component_sequence", repr(component))
        relative = component.get("path")
        expected_hash = component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise M2AcceptanceError("invalid_component_record", repr(component))
        path = root / relative
        if not path.is_file():
            raise M2AcceptanceError("missing_contract_component", relative)
        actual_hash = semantic_sha256(path)
        if actual_hash != expected_hash:
            raise M2AcceptanceError(
                "semantic_fingerprint_mismatch",
                f"{relative}: expected {expected_hash}, found {actual_hash}",
            )

    lineage = migration_lineage(root)
    if lineage != EXPECTED_LINEAGE:
        raise M2AcceptanceError("unexpected_migration_lineage", repr(lineage))
    if tuple(manifest.get("canonical_migration_lineage", ())) != EXPECTED_LINEAGE:
        raise M2AcceptanceError("manifest_lineage_mismatch", "canonical_migration_lineage")
    validate_static_boundaries(root)
    return ManifestCheck(
        checked_components=len(components),
        canonical_head=EXPECTED_HEAD,
        lineage=lineage,
    )
