"""Static semantic-manifest and authority-boundary validation for the M7 freeze."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .m4_acceptance import (
    HistoricalLineageError,
    live_migration_lineage,
    semantic_sha256,
    validate_historical_lineage_prefix,
)
from .m6_acceptance import EXPECTED_HEAD, EXPECTED_LINEAGE

EXPECTED_TAG = "track-b-m7-finance-facing-wnd-migration-support-20260811"


class M7AcceptanceError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ManifestCheck:
    checked_components: int
    canonical_head: str
    lineage: tuple[str, ...]


def _read_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M7AcceptanceError(code, str(path)) from exc
    if not isinstance(value, dict):
        raise M7AcceptanceError(code, f"expected object: {path}")
    return value


def validate_release_manifest(root: Path) -> ManifestCheck:
    manifest = _read_json(
        root / "contracts" / "finance" / "v1" / "m7_release_manifest.json",
        "invalid_release_manifest",
    )
    if manifest.get("baseline_code") != "XBOS_M7_FINANCE_FACING_WND_MIGRATION_SUPPORT_RELEASE":
        raise M7AcceptanceError("unexpected_manifest", "baseline_code")
    if manifest.get("approved_commit_parent") != "5eea325":
        raise M7AcceptanceError("unexpected_parent", repr(manifest.get("approved_commit_parent")))
    if manifest.get("canonical_head") != EXPECTED_HEAD:
        raise M7AcceptanceError("unexpected_head", repr(manifest.get("canonical_head")))
    if "canonical_migration_lineage" in manifest:
        raise M7AcceptanceError(
            "manifest_lineage_changed",
            "historical M7 manifest did not declare canonical_migration_lineage",
        )
    if manifest.get("release_tag") != EXPECTED_TAG:
        raise M7AcceptanceError("unexpected_release_tag", repr(manifest.get("release_tag")))
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 5:
        raise M7AcceptanceError("component_count", repr(components))
    for sequence, component in enumerate(components, 1):
        if component.get("sequence") != sequence or component.get("milestone") != f"M7.{sequence - 1}":
            raise M7AcceptanceError("component_sequence", repr(component))
        relative = component.get("path")
        expected = component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise M7AcceptanceError("invalid_component", repr(component))
        actual = semantic_sha256(root / relative)
        if actual != expected:
            raise M7AcceptanceError(
                "semantic_fingerprint_mismatch",
                f"{relative}: expected {expected}, found {actual}",
            )
    live_lineage = live_migration_lineage(root)
    try:
        lineage = validate_historical_lineage_prefix(live_lineage, EXPECTED_LINEAGE)
    except HistoricalLineageError as exc:
        raise M7AcceptanceError("unexpected_migration_lineage", str(exc)) from exc
    if tuple((root / "alembic_neutral" / "versions").glob("m7*.py")):
        raise M7AcceptanceError("unexpected_m7_migration", "M7 must remain schema neutral")
    return ManifestCheck(len(components), EXPECTED_HEAD, lineage)


def validate_authority_boundaries(root: Path) -> None:
    contract = _read_json(
        root / "contracts" / "finance" / "v1" / "m75_finance_migration_support_acceptance_and_freeze.json",
        "invalid_freeze_contract",
    )
    required = {
        "migration": False,
        "writer_routing": "unchanged",
        "cutover_authorized": False,
        "retirement_execution_allowed": False,
        "live_cutover_owner": "R6",
    }
    for key, expected in required.items():
        if contract.get(key) != expected:
            raise M7AcceptanceError("authority_boundary_changed", f"{key}={contract.get(key)!r}")
    markers = {
        "core/persistence/m70_finance_migration_support.py": (
            "SCHEMA_NEUTRAL = True", "REROUTES_LEGACY_WRITERS = False", "LIVE_CUTOVER_OWNER = \"R6\"",
        ),
        "core/persistence/m71_wnd_financial_mapping.py": (
            "SCHEMA_NEUTRAL = True", "EXECUTES_CANONICAL_COMMANDS = False", "REROUTES_LEGACY_WRITERS = False",
        ),
        "core/persistence/m72_wnd_inventory_document_mapping.py": (
            "SCHEMA_NEUTRAL = True", "EXECUTES_CANONICAL_COMMANDS = False", "REGENERATES_HISTORICAL_DOCUMENTS = False",
        ),
        "core/persistence/m73_wnd_shadow_rehearsal.py": (
            "SCHEMA_NEUTRAL = True", "PRODUCTION_WRITES_ALLOWED = False", "PERFORMS_LIVE_CUTOVER = False",
        ),
        "core/persistence/m74_wnd_cutover_support.py": (
            "SCHEMA_NEUTRAL = True", "CUTOVER_AUTHORIZED = False", "RETIREMENT_EXECUTION_ALLOWED = False",
            "REROUTES_LEGACY_WRITERS = False", "DISABLES_LEGACY_WRITERS = False",
        ),
    }
    for relative, expected_markers in markers.items():
        source = (root / relative).read_text(encoding="utf-8")
        for marker in expected_markers:
            if marker not in source:
                raise M7AcceptanceError("missing_authority_guard", f"{relative}: {marker}")


def validate_public_artifacts(root: Path) -> None:
    for milestone in range(5):
        for suffix in ("RUN_ACCEPTANCE.cmd", "INSTALL_AND_VERIFY.txt"):
            relative = f"XBOS_M7_{milestone}_{suffix}"
            if not (root / relative).is_file():
                raise M7AcceptanceError("missing_public_artifact", relative)
