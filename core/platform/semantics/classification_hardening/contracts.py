"""Pre-R0 semantic-classification hardening contracts.

This descendant layer extends frozen PC3 without mutating its release artifacts.
It keeps semantic identity, operational objects, packs/templates and Finance in
separate native authorities while adding global-capable taxonomy placement,
tenant overlays, governed target assignment and read-model contracts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class SemanticSource(StrEnum):
    KERNEL = "kernel"
    FINANCE = "finance"
    PACK = "pack"
    TENANT = "tenant"
    EXTERNAL = "external"
    TEMPLATE = "template"
    MIGRATION = "migration"


class AssignmentMode(StrEnum):
    EXPLICIT = "explicit"
    INHERITED = "inherited"
    DERIVED = "derived"
    IMPORTED = "imported"


class TargetScope(StrEnum):
    TENANT = "tenant"
    GLOBAL = "global"
    MIXED = "mixed"


class HealthSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class TaxonomySystemDefinition:
    id: int
    public_id: UUID
    system_code: str
    owner_code: str
    tenant_id: int | None
    namespace_code: str | None
    lifecycle: str


@dataclass(frozen=True)
class SemanticTaxonomyNode:
    id: int
    public_id: UUID
    taxonomy_system_id: int
    system_code: str
    semantic_concept_id: int
    concept_qualified_code: str
    node_code: str
    tenant_id: int | None
    lifecycle: str
    row_version: int


@dataclass(frozen=True)
class TaxonomyPlacementVersion:
    id: int
    public_id: UUID
    semantic_taxonomy_node_id: int
    placement_version: int
    parent_node_public_id: UUID | None
    sort_order: int
    effective_from: datetime
    effective_to: datetime | None
    source_type: SemanticSource
    source_key: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class TenantTaxonomyOverlay:
    id: int
    public_id: UUID
    tenant_id: int
    semantic_taxonomy_node_id: int
    overlay_version: int
    local_label: str | None
    local_sort_order: int | None
    parent_override_public_id: UUID | None
    has_parent_override: bool
    is_suppressed: bool
    effective_from: datetime
    effective_to: datetime | None
    source_type: SemanticSource
    source_key: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ClassificationRecord:
    assignment_id: int
    tenant_id: int
    target_type: str
    target_key: str
    concept_qualified_code: str
    concept_version: int
    definition_fingerprint: str
    semantic_taxonomy_node_public_id: UUID | None
    assignment_mode: AssignmentMode
    source_type: SemanticSource
    source_key: str
    effective_from: datetime
    effective_to: datetime | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class EffectiveTaxonomyNode:
    node_public_id: UUID
    system_code: str
    node_code: str
    concept_qualified_code: str
    label: str
    tenant_id: int | None
    parent_public_id: UUID | None
    sort_order: int
    source_type: SemanticSource
    source_key: str
    inherited: bool
    depth: int
    path: tuple[str, ...]


@dataclass(frozen=True)
class ClassificationView:
    tenant_id: int
    target_type: str
    target_key: str
    system_code: str | None
    node_public_id: UUID | None
    node_code: str | None
    concept_qualified_code: str
    concept_version: int
    label: str
    path: tuple[str, ...]
    assignment_mode: AssignmentMode
    source_type: SemanticSource
    source_key: str
    effective_from: datetime
    effective_to: datetime | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class HealthIssue:
    severity: HealthSeverity
    code: str
    object_type: str
    object_key: str
    system_code: str | None
    detail: str
    remediation: str


@dataclass(frozen=True)
class TargetTypeDefinition:
    target_type: str
    owner_code: str
    scope: TargetScope
    reference_format: str


@dataclass(frozen=True)
class CreateTaxonomySystem:
    command_key: str
    system_code: str
    owner_code: str
    namespace_code: str
    tenant_id: int | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CreateTaxonomyNode:
    command_key: str
    system_code: str
    concept_qualified_code: str
    node_code: str
    effective_from: datetime
    tenant_id: int | None = None
    parent_node_public_id: UUID | None = None
    sort_order: int = 0
    source_type: SemanticSource = SemanticSource.KERNEL
    source_key: str = "kernel"
    provenance: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReparentTaxonomyNode:
    command_key: str
    node_public_id: UUID
    expected_placement_version: int
    effective_from: datetime
    parent_node_public_id: UUID | None
    sort_order: int = 0
    tenant_id: int | None = None
    source_type: SemanticSource = SemanticSource.KERNEL
    source_key: str = "kernel"
    provenance: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetTenantTaxonomyOverlay:
    command_key: str
    tenant_id: int
    node_public_id: UUID
    expected_overlay_version: int | None
    effective_from: datetime
    local_label: str | None = None
    local_sort_order: int | None = None
    parent_override_public_id: UUID | None = None
    has_parent_override: bool = False
    is_suppressed: bool = False
    source_type: SemanticSource = SemanticSource.TENANT
    source_key: str = "tenant"
    provenance: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClearTenantTaxonomyOverlay:
    command_key: str
    tenant_id: int
    node_public_id: UUID
    expected_overlay_version: int
    effective_from: datetime

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssignSemanticClassification:
    command_key: str
    tenant_id: int
    target_type: str
    target_key: str
    concept_qualified_code: str
    classified_at: datetime
    semantic_taxonomy_node_public_id: UUID | None = None
    assignment_mode: AssignmentMode = AssignmentMode.EXPLICIT
    source_type: SemanticSource = SemanticSource.TENANT
    source_key: str = "tenant"
    provenance: dict[str, Any] | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EndSemanticClassification:
    command_key: str
    tenant_id: int
    assignment_id: int
    expected_effective_from: datetime
    effective_to: datetime

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)
