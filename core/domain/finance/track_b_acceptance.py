"""Static release-lineage and authority validation for the Track B approved exit."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .m2_acceptance import validate_release_manifest as validate_m2
from .m3_acceptance import validate_release_manifest as validate_m3
from .m4_acceptance import live_migration_lineage, semantic_sha256
from .m5_acceptance import validate_release_manifest as validate_m5
from .m6_acceptance import (
    EXPECTED_HEAD,
    EXPECTED_LINEAGE,
    validate_frozen_m4_manifest,
    validate_release_manifest as validate_m6,
)
from .m7_acceptance import (
    validate_authority_boundaries,
    validate_public_artifacts as validate_m7_public_artifacts,
    validate_release_manifest as validate_m7,
)
from .pack_conformance_service import find_hidden_financial_writers, validate_generic_harness_neutrality

EXIT_MANIFEST = "contracts/finance/v1/track_b_financial_approved_exit_manifest.json"
PROPOSED_TAG = "track-b-financial-hardening-and-approved-exit-20260812"


class TrackBAcceptanceError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TrackBManifestCheck:
    checked_components: int
    canonical_head: str
    lineage: tuple[str, ...]
    historical_release_counts: tuple[int, ...]


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrackBAcceptanceError("invalid_json", str(path)) from exc
    if not isinstance(value, dict):
        raise TrackBAcceptanceError("invalid_json_object", str(path))
    return value


def validate_release_manifest(root: Path) -> TrackBManifestCheck:
    manifest = _read_json(root / EXIT_MANIFEST)
    if manifest.get("baseline_code") != "XBOS_TRACK_B_FINANCIAL_HARDENING_AND_APPROVED_EXIT":
        raise TrackBAcceptanceError("unexpected_manifest", "baseline_code")
    if manifest.get("source_checkpoint") != "ab43fbd":
        raise TrackBAcceptanceError("unexpected_checkpoint", repr(manifest.get("source_checkpoint")))
    if manifest.get("canonical_head") != EXPECTED_HEAD:
        raise TrackBAcceptanceError("unexpected_head", repr(manifest.get("canonical_head")))
    if manifest.get("migration") is not False or manifest.get("schema_neutral") is not True:
        raise TrackBAcceptanceError("schema_boundary_changed", "M8.5 must be schema neutral")
    if manifest.get("proposed_release_tag") != PROPOSED_TAG:
        raise TrackBAcceptanceError("unexpected_proposed_tag", repr(manifest.get("proposed_release_tag")))
    if manifest.get("cutover") != "NOT_AUTHORIZED" or manifest.get("writer_retirement") != "NOT_EXECUTED":
        raise TrackBAcceptanceError("R6_boundary_exceeded", "cutover or retirement")
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != 12:
        raise TrackBAcceptanceError("component_count", repr(components))
    for sequence, component in enumerate(components, 1):
        if component.get("sequence") != sequence:
            raise TrackBAcceptanceError("component_sequence", repr(component))
        relative, expected = component.get("path"), component.get("semantic_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise TrackBAcceptanceError("invalid_component", repr(component))
        actual = semantic_sha256(root / relative)
        if actual != expected:
            raise TrackBAcceptanceError("semantic_fingerprint_mismatch", f"{relative}: expected {expected}, found {actual}")
    if tuple(manifest.get("canonical_migration_lineage", ())) != EXPECTED_LINEAGE:
        raise TrackBAcceptanceError("manifest_lineage_changed", "canonical_migration_lineage")
    lineage = live_migration_lineage(root)
    if lineage != EXPECTED_LINEAGE:
        raise TrackBAcceptanceError("repository_lineage_changed", repr(lineage))
    if tuple((root / "alembic_neutral/versions").glob("m8*.py")):
        raise TrackBAcceptanceError("unexpected_m8_migration", "M8 must remain schema neutral")

    counts = (
        validate_m2(root).checked_components,
        validate_m3(root).checked_components,
        validate_frozen_m4_manifest(root),
        validate_m5(root),
        validate_m6(root).checked_components,
        validate_m7(root).checked_components,
    )
    validate_authority_boundaries(root)
    return TrackBManifestCheck(len(components), EXPECTED_HEAD, lineage, counts)


def validate_public_artifacts(root: Path) -> None:
    validate_m7_public_artifacts(root)
    for milestone in range(5):
        for suffix in ("RUN_ACCEPTANCE.cmd", "INSTALL_AND_VERIFY.txt"):
            relative = f"XBOS_M8_{milestone}_{suffix}"
            if not (root / relative).is_file():
                raise TrackBAcceptanceError("missing_public_artifact", relative)


def validate_authority_exit(root: Path) -> None:
    contract = _read_json(root / "contracts/finance/v1/m85_track_b_aggregate_conformance_freeze_and_approved_exit.json")
    boundaries = contract.get("boundaries", {})
    expected = {
        "schema_neutral": True,
        "new_financial_authority": False,
        "production_data_mutation": False,
        "writer_routing": "unchanged",
        "cutover": "NOT_AUTHORIZED",
        "writer_retirement": "NOT_EXECUTED",
        "live_cutover_owner": "R6",
    }
    for key, value in expected.items():
        if boundaries.get(key) != value:
            raise TrackBAcceptanceError("authority_boundary_changed", f"{key}={boundaries.get(key)!r}")
    source = (root / "core/persistence/m85_track_b_approved_exit.py").read_text(encoding="utf-8")
    for marker in (
        "SCHEMA_NEUTRAL = True", "MIGRATION = None", "CREATES_FINANCIAL_AUTHORITY = False",
        "MUTATES_DEVELOPMENT_DATA = False", "REROUTES_LEGACY_WRITERS = False",
        "CUTOVER_AUTHORIZED = False", "WRITER_RETIREMENT_EXECUTED = False", 'LIVE_CUTOVER_OWNER = "R6"',
    ):
        if marker not in source:
            raise TrackBAcceptanceError("missing_exit_guard", marker)
    validate_generic_harness_neutrality(root)
    pack_paths = (
        "core/domain/finance/wnd_financial_mapping_service.py",
        "core/domain/finance/wnd_inventory_document_service.py",
        "core/domain/finance/wnd_shadow_rehearsal_service.py",
        "core/domain/finance/wnd_cutover_support_service.py",
        "core/domain/finance/wnd_pack_conformance_profile.py",
    )
    hidden = find_hidden_financial_writers(root, pack_paths)
    if hidden:
        raise TrackBAcceptanceError("hidden_financial_writers", repr(hidden))
