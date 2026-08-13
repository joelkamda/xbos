"""Stable, effective-dated PC3 semantic contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID


class NamespaceScope(StrEnum):
    KERNEL = "kernel"
    FINANCE = "finance"
    PACK = "pack"
    TENANT = "tenant"
    EXTERNAL = "external"


class SemanticLifecycle(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class MappingType(StrEnum):
    EXACT = "exact"
    BROADER = "broader"
    NARROWER = "narrower"
    RELATED = "related"
    LEGACY_REPLACEMENT = "legacy_replacement"


@dataclass(frozen=True)
class SemanticNamespace:
    id: int
    public_id: UUID
    namespace_code: str
    scope: NamespaceScope
    owner_code: str
    tenant_id: int | None
    lifecycle: SemanticLifecycle


@dataclass(frozen=True)
class SemanticConcept:
    id: int
    public_id: UUID
    namespace_id: int
    namespace_code: str
    code: str
    lifecycle: SemanticLifecycle

    @property
    def qualified_code(self) -> str:
        return f"{self.namespace_code}:{self.code}"


@dataclass(frozen=True)
class SemanticVersion:
    id: int
    public_id: UUID
    concept_id: int
    version_number: int
    effective_from: date
    effective_to: date | None
    canonical_label: str
    definition: str
    definition_fingerprint: str


@dataclass(frozen=True)
class SemanticMapping:
    id: int
    public_id: UUID
    mapping_set_code: str
    source_concept_id: int
    target_concept_id: int
    mapping_type: MappingType
    effective_from: date
    effective_to: date | None


@dataclass(frozen=True)
class ClassificationSnapshot:
    assignment_id: int
    subject_type: str
    subject_key: str
    concept_qualified_code: str
    concept_version: int
    definition_fingerprint: str
    taxonomy_node_id: int | None
    assigned_on: date


@dataclass(frozen=True)
class TaxonomyPlacement:
    tenant_id: int
    taxonomy_node_id: int
    parent_id: int | None
    semantic_row_version: int


@dataclass(frozen=True)
class CreateNamespace:
    command_key: str
    namespace_code: str
    scope: NamespaceScope
    owner_code: str
    tenant_id: int | None = None

    def canonical_payload(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class CreateConcept:
    command_key: str
    namespace_code: str
    owner_code: str
    code: str

    def canonical_payload(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class CreateSemanticVersion:
    command_key: str
    namespace_code: str
    owner_code: str
    concept_code: str
    version_number: int
    effective_from: date
    effective_to: date | None
    canonical_label: str
    definition: str

    def canonical_payload(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class CreateMapping:
    command_key: str
    mapping_set_code: str
    owner_code: str
    source_qualified_code: str
    target_qualified_code: str
    mapping_type: MappingType
    effective_from: date
    effective_to: date | None = None

    def canonical_payload(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class AssignClassification:
    command_key: str
    tenant_id: int
    subject_type: str
    subject_key: str
    concept_qualified_code: str
    classified_on: date
    taxonomy_node_id: int | None = None

    def canonical_payload(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class MoveTaxonomyNode:
    tenant_id: int
    taxonomy_node_id: int
    parent_id: int | None
    expected_version: int
