"""R4 Restaurant pack-registration composition contracts.

R4 owns no Pack Platform state. It defines the immutable Restaurant industry-pack
composition and produces commands that are executed by PK0-PK6 public authorities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pack_platform.contracts import PackManifest, RegisterPackVersion
from pack_platform.pk456_contracts import CertifyPackVersion


@dataclass(frozen=True)
class RestaurantSemanticContribution:
    namespace_code: str
    scope: str
    source_key: str
    taxonomy_systems: tuple[str, ...]
    closed_value_sets: bool = False


@dataclass(frozen=True)
class RestaurantConfigurationDeclaration:
    key: str
    owner: str
    default_policy: str
    tenant_overridable: bool = True


@dataclass(frozen=True)
class RestaurantExperienceMetadata:
    profile_family: str
    workspace_slots: tuple[str, ...]
    navigation_candidates: tuple[str, ...]
    frontend_implemented: bool
    engine_implemented: bool
    tables_required: bool


@dataclass(frozen=True)
class RestaurantPackRegistrationPlan:
    manifest: PackManifest
    register_command: RegisterPackVersion
    certification_command: CertifyPackVersion
    semantic_contribution: RestaurantSemanticContribution
    configuration: tuple[RestaurantConfigurationDeclaration, ...]
    experience: RestaurantExperienceMetadata
    tenant_installation_authorized: bool = False
    template_application_authorized: bool = False
    wnd_cutover_authorized: bool = False
    metadata: dict[str, Any] | None = None
