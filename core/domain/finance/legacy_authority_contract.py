"""Typed, schema-neutral M7.0 legacy-authority inventory contract."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class LegacyAuthorityError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class AuthorityMode(str, Enum):
    READER = "reader"
    WRITER = "writer"
    READER_WRITER = "reader_writer"


class MigrationDisposition(str, Enum):
    SHADOW_CANDIDATE = "shadow_candidate"
    CONTROL_TOTAL_SOURCE = "control_total_source"
    DUAL_READ_CANDIDATE = "dual_read_candidate"
    RETIREMENT_CANDIDATE = "retirement_candidate"


@dataclass(frozen=True)
class LegacyAuthoritySurface:
    code: str
    source_path: str
    source_symbol: str
    authority_mode: AuthorityMode
    legacy_stores: tuple[str, ...]
    canonical_targets: tuple[str, ...]
    mapping_package: str
    disposition: MigrationDisposition
    evidence_markers: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LegacyAuthoritySurface":
        try:
            result = cls(
                code=str(value["code"]),
                source_path=str(value["source_path"]),
                source_symbol=str(value["source_symbol"]),
                authority_mode=AuthorityMode(value["authority_mode"]),
                legacy_stores=tuple(value["legacy_stores"]),
                canonical_targets=tuple(value["canonical_targets"]),
                mapping_package=str(value["mapping_package"]),
                disposition=MigrationDisposition(value["disposition"]),
                evidence_markers=tuple(value["evidence_markers"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LegacyAuthorityError("invalid_surface", repr(value)) from exc
        if not result.code or not result.source_symbol:
            raise LegacyAuthorityError("invalid_surface_identity", result.code)
        if Path(result.source_path).is_absolute() or ".." in Path(result.source_path).parts:
            raise LegacyAuthorityError("unsafe_source_path", result.source_path)
        if not result.legacy_stores or not result.canonical_targets or not result.evidence_markers:
            raise LegacyAuthorityError("incomplete_surface", result.code)
        if result.mapping_package not in {"M7.1", "M7.2", "M7.3", "M7.4"}:
            raise LegacyAuthorityError("invalid_mapping_package", result.mapping_package)
        return result


@dataclass(frozen=True)
class LegacyAuthorityInventory:
    canonical_head: str
    writer_routing: str
    live_cutover_owner: str
    adapter_mode: str
    surfaces: tuple[LegacyAuthoritySurface, ...]
    semantic_fingerprint: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def inventory_fingerprint(payload: Mapping[str, Any]) -> str:
    semantic = {key: value for key, value in payload.items() if key != "source_checkpoint"}
    return hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
