"""R5 WND tenant-profile and Restaurant-template proof contracts.

R5 composes frozen PC/PK/SO/Finance authorities. It owns no duplicate financial,
catalog, inventory, resource, semantic, or pack-platform persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

from pack_platform.pk456_contracts import TemplateDefinition


@dataclass(frozen=True)
class WNDStructureProfile:
    tenant_code: str
    tenant_name: str
    country_code: str
    currency: str
    locale: str
    timezone: str
    legal_entity_code: str
    legal_entity_name: str
    organization_code: str
    organization_name: str
    location_code: str
    location_name: str


@dataclass(frozen=True)
class WNDCalendarProfile:
    calendar_code: str
    timezone: str
    business_day_boundary: time
    day_start: time
    day_end: time
    night_start: time
    night_end: time
    payment_shift_cutoff: time
    commission_attribution_basis: str


@dataclass(frozen=True)
class WNDBrandingProfile:
    business_display_name: str
    branding_asset_reference: str
    terminology: dict[str, str]


@dataclass(frozen=True)
class WNDTenantProfile:
    profile_code: str
    structure: WNDStructureProfile
    template_code: str
    template_version: str
    template_overrides: dict[str, Any]
    calendar: WNDCalendarProfile
    payment_configuration: dict[str, Any]
    branding: WNDBrandingProfile
    migration_mappings: dict[str, Any]
    production_cutover_authorized: bool = False


@dataclass(frozen=True)
class RestaurantTemplateSet:
    counter_service: TemplateDefinition
    full_service: TemplateDefinition


@dataclass(frozen=True)
class WNDCompositionPlan:
    profile: WNDTenantProfile
    templates: RestaurantTemplateSet
    pack_code: str
    pack_version: str
    database_schema_change: str
    production_cutover_authorized: bool
    metadata: dict[str, Any]
