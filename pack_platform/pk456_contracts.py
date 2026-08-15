"""PK4-PK6 pack conformance, template registry, application and upgrade contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class ConformanceResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class TemplateRequirementKind(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class PackCertificationEvidence:
    checks: dict[str, ConformanceResult]
    evidence_sha256: tuple[str, ...]
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CertifyPackVersion:
    command_key: str
    pack_code: str
    version: str
    certification_code: str
    suite_version: str
    evidence: PackCertificationEvidence


@dataclass(frozen=True)
class PackCertificationRecord:
    public_id: UUID
    pack_code: str
    version: str
    certification_code: str
    suite_version: str
    manifest_sha256: str
    evidence_sha256: str
    result: ConformanceResult


@dataclass(frozen=True)
class TemplatePackRequirement:
    pack_code: str
    version: str
    kind: TemplateRequirementKind


@dataclass(frozen=True)
class TemplateDefinition:
    template_code: str
    version: str
    owner_code: str
    industry_semantic_ref: str
    operating_model_semantic_ref: str
    requirements: tuple[TemplatePackRequirement, ...]
    allowed_override_paths: tuple[str, ...] = ()
    configuration_defaults: dict[str, Any] = field(default_factory=dict)
    terminology: dict[str, str] = field(default_factory=dict)
    xa: dict[str, Any] = field(default_factory=dict)
    semantic_references: tuple[str, ...] = ()
    finance_workspace_exposed: bool = True
    finance_kernel_required: bool = True


@dataclass(frozen=True)
class RegisterTemplateVersion:
    command_key: str
    template: TemplateDefinition


@dataclass(frozen=True)
class TemplateVersionRecord:
    public_id: UUID
    template_code: str
    version: str
    owner_code: str
    template_sha256: str
    industry_semantic_ref: str
    operating_model_semantic_ref: str


@dataclass(frozen=True)
class PlanTemplateApplication:
    tenant_id: int
    template_code: str
    version: str
    selected_optional_packs: tuple[str, ...] = ()
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplyTemplate:
    command_key: str
    tenant_id: int
    template_code: str
    version: str
    plan_sha256: str
    selected_optional_packs: tuple[str, ...] = ()
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanTemplateUpgrade:
    tenant_id: int
    template_code: str
    target_version: str


@dataclass(frozen=True)
class UpgradeTemplate:
    command_key: str
    tenant_id: int
    template_code: str
    target_version: str
    plan_sha256: str
    expected_row_version: int
    reason: str


@dataclass(frozen=True)
class TemplatePlan:
    tenant_id: int
    template_code: str
    from_version: str | None
    to_version: str
    required_packs: tuple[str, ...]
    optional_packs: tuple[str, ...]
    actions: tuple[str, ...]
    conflicts: tuple[str, ...]
    preserved_overrides: dict[str, Any]
    plan_sha256: str


@dataclass(frozen=True)
class TenantTemplateState:
    public_id: UUID
    tenant_id: int
    template_code: str
    version: str
    row_version: int
    template_sha256: str
    overrides: dict[str, Any]
    effective_configuration: dict[str, Any]
