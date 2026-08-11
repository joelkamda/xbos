"""Static semantic-manifest and migration-lineage authority for the M6 freeze."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .m4_acceptance import EXPECTED_LINEAGE as M4_LINEAGE
from .m4_acceptance import live_migration_lineage, semantic_sha256

EXPECTED_HEAD = "m64_reconciliation_controls_020"
EXPECTED_LINEAGE = M4_LINEAGE + (
    "m60_operational_balance_authority_016",
    "m61_transfers_reconciliation_017",
    "m62_reconciliation_windows_018",
    "m63_reconciliation_close_019",
    EXPECTED_HEAD,
)
EXPECTED_TAG = "track-b-m6-treasury-reconciliation-close-control-20260811"


class M6AcceptanceError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ManifestCheck:
    checked_components: int
    canonical_head: str
    lineage: tuple[str, ...]


def validate_frozen_m4_manifest(root: Path) -> int:
    """Validate M4 content while M6 owns the repository's extended lineage."""
    path = root / "contracts" / "finance" / "v1" / "m4_release_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M6AcceptanceError("invalid_m4_release_manifest", str(path)) from exc
    if manifest.get("baseline_code") != "XBOS_M4_PAYMENTS_SETTLEMENT_ORCHESTRATION_RELEASE":
        raise M6AcceptanceError("unexpected_m4_manifest", "baseline_code")
    if manifest.get("canonical_head") != M4_LINEAGE[-1]:
        raise M6AcceptanceError("unexpected_m4_head", repr(manifest.get("canonical_head")))
    if tuple(manifest.get("canonical_migration_lineage", ())) != M4_LINEAGE:
        raise M6AcceptanceError("m4_lineage_changed", "canonical_migration_lineage")
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 7:
        raise M6AcceptanceError("m4_component_count", repr(components))
    for sequence, component in enumerate(components, 1):
        if component.get("sequence") != sequence:
            raise M6AcceptanceError("m4_component_sequence", repr(component))
        relative = component.get("path")
        expected = component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise M6AcceptanceError("invalid_m4_component", repr(component))
        actual = semantic_sha256(root / relative)
        if actual != expected:
            raise M6AcceptanceError("m4_semantic_fingerprint_mismatch", f"{relative}: expected {expected}, found {actual}")
    return len(components)


def validate_release_manifest(root: Path) -> ManifestCheck:
    path = root / "contracts" / "finance" / "v1" / "m6_release_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M6AcceptanceError("invalid_release_manifest", str(path)) from exc
    if manifest.get("baseline_code") != "XBOS_M6_TREASURY_RECONCILIATION_CLOSE_CONTROL_RELEASE":
        raise M6AcceptanceError("unexpected_manifest", "baseline_code")
    if manifest.get("canonical_head") != EXPECTED_HEAD:
        raise M6AcceptanceError("unexpected_head", repr(manifest.get("canonical_head")))
    if manifest.get("release_tag") != EXPECTED_TAG:
        raise M6AcceptanceError("unexpected_release_tag", repr(manifest.get("release_tag")))
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 5:
        raise M6AcceptanceError("component_count", repr(components))
    for sequence, component in enumerate(components, 1):
        if component.get("sequence") != sequence or component.get("milestone") != f"M6.{sequence-1}":
            raise M6AcceptanceError("component_sequence", repr(component))
        relative = component.get("path")
        expected = component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise M6AcceptanceError("invalid_component", repr(component))
        actual = semantic_sha256(root / relative)
        if actual != expected:
            raise M6AcceptanceError("semantic_fingerprint_mismatch", f"{relative}: expected {expected}, found {actual}")
    lineage = live_migration_lineage(root)
    if lineage != EXPECTED_LINEAGE:
        raise M6AcceptanceError("unexpected_migration_lineage", repr(lineage))
    if tuple((root / "alembic_neutral" / "versions").glob("m65_*.py")):
        raise M6AcceptanceError("unexpected_m6_closure_migration", "M6.5 must be schema neutral")
    return ManifestCheck(len(components), EXPECTED_HEAD, lineage)


def validate_concurrency_guards(root: Path) -> None:
    repository_paths = (
        "core/domain/finance/operational_transfer_repository.py",
        "core/domain/finance/reconciliation_window_repository.py",
        "core/domain/finance/reconciliation_close_repository.py",
        "core/domain/finance/reconciliation_control_repository.py",
    )
    for relative in repository_paths:
        if "FOR UPDATE" not in (root / relative).read_text(encoding="utf-8"):
            raise M6AcceptanceError("missing_lock_guard", relative)
    migration_paths = (
        "alembic_neutral/sql/m60_operational_balance_authority_up.sql",
        "alembic_neutral/sql/m62_reconciliation_windows_up.sql",
        "alembic_neutral/sql/m63_reconciliation_close_governance_up.sql",
        "alembic_neutral/sql/m64_reconciliation_controls_up.sql",
    )
    for relative in migration_paths:
        source = (root / relative).read_text(encoding="utf-8")
        if "UNIQUE" not in source or "idempotency" not in source:
            raise M6AcceptanceError("missing_uniqueness_guard", relative)
