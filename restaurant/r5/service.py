"""R5 WND profile + Restaurant template composition over public XBOS authorities."""
from __future__ import annotations

from datetime import datetime, time, timezone
from hashlib import sha256
import json
from typing import Any, Iterable

from core.platform.operating_context import (
    BusinessCalendarVersion,
    ConfigScope,
    ConfigType,
    DefineConfiguration,
    LocalizationProfile,
    RegisterBusinessCalendar,
    SetConfiguration,
    SetLocalizationProfile,
    ShiftRule,
)
from core.platform.structure import LocationKind, ProvisionTenant
from pack_platform.contracts import ActivatePack, InstallPack, StagePack
from pack_platform.pk456_contracts import (
    ApplyTemplate,
    PlanTemplateApplication,
    RegisterTemplateVersion,
    TemplateDefinition,
    TemplatePackRequirement,
    TemplateRequirementKind,
)

from .contracts import (
    RestaurantTemplateSet,
    WNDBrandingProfile,
    WNDCalendarProfile,
    WNDCompositionPlan,
    WNDStructureProfile,
    WNDTenantProfile,
)

PACK_CODE = "industry.restaurant"
PACK_VERSION = "1.0.0"

COUNTER_TEMPLATE_CODE = "restaurant.counter_service"
FULL_SERVICE_TEMPLATE_CODE = "restaurant.full_service"
TEMPLATE_VERSION = "1.0.0"

WND_PROFILE_CODE = "wnd.logpom"
WND_PROOF_TENANT_CODE = "wnd-r5-proof"
EFFECTIVE_FROM = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)

_COUNTER_DEFAULTS = {
    "restaurant": {
        "tables": {"enabled": False},
        "reservations": {"enabled": False},
        "fulfillment": {
            "course_firing": {"enabled": False},
            "output_delivery": {"enabled": True},
            "station_routing": {"enabled": True},
        },
        "service_modes": {"enabled": ["counter", "takeaway", "delivery"]},
        "tips": {"enabled": True},
        "commissions": {"enabled": False},
    }
}

_FULL_SERVICE_DEFAULTS = {
    "restaurant": {
        "tables": {"enabled": True},
        "reservations": {"enabled": True},
        "fulfillment": {
            "course_firing": {"enabled": True},
            "output_delivery": {"enabled": True},
            "station_routing": {"enabled": True},
        },
        "service_modes": {"enabled": ["dine_in", "takeaway", "delivery"]},
        "tips": {"enabled": True},
        "commissions": {"enabled": True},
    }
}

_ALLOWED_OVERRIDES = (
    "restaurant.commissions.enabled",
    "restaurant.fulfillment.course_firing.enabled",
    "restaurant.fulfillment.output_delivery.enabled",
    "restaurant.fulfillment.station_routing.enabled",
    "restaurant.reservations.enabled",
    "restaurant.service_modes.enabled",
    "restaurant.tables.enabled",
    "restaurant.tips.enabled",
)

_GENERIC_CONFIG_DEFINITIONS = (
    ("restaurant.tables.enabled", ConfigType.BOOLEAN),
    ("restaurant.reservations.enabled", ConfigType.BOOLEAN),
    ("restaurant.fulfillment.course_firing.enabled", ConfigType.BOOLEAN),
    ("restaurant.fulfillment.output_delivery.enabled", ConfigType.BOOLEAN),
    ("restaurant.fulfillment.station_routing.enabled", ConfigType.BOOLEAN),
    ("restaurant.service_modes.enabled", ConfigType.JSON),
    ("restaurant.tips.enabled", ConfigType.BOOLEAN),
    ("restaurant.commissions.enabled", ConfigType.BOOLEAN),
)

_WND_CONFIG_DEFINITIONS = (
    ("wnd.payment_shift.cutoff_local_time", ConfigType.TIME, None),
    ("wnd.payments.enabled_methods", ConfigType.JSON, None),
    ("wnd.commission.attribution_basis", ConfigType.CODE, {"enum": ["original_order_creator"]}),
)


def _template(
    code: str,
    operating_model: str,
    defaults: dict[str, Any],
    terminology: dict[str, str],
) -> TemplateDefinition:
    return TemplateDefinition(
        template_code=code,
        version=TEMPLATE_VERSION,
        owner_code="restaurant",
        industry_semantic_ref="restaurant:industry",
        operating_model_semantic_ref=f"restaurant:{operating_model}",
        requirements=(
            TemplatePackRequirement(PACK_CODE, PACK_VERSION, TemplateRequirementKind.REQUIRED),
        ),
        allowed_override_paths=_ALLOWED_OVERRIDES,
        configuration_defaults=defaults,
        terminology=terminology,
        xa={
            "profile_family": "restaurant",
            "workspace_slots": [
                "restaurant.service",
                "restaurant.fulfillment",
                "restaurant.reporting",
                "restaurant.configuration",
            ],
            "tables_required": defaults["restaurant"]["tables"]["enabled"],
            "frontend_implemented": False,
        },
        semantic_references=(
            "restaurant:service_mode",
            "restaurant:fulfillment_station",
            "restaurant:course",
            "restaurant:charge_nature",
        ),
        finance_workspace_exposed=True,
        finance_kernel_required=True,
    )


def build_restaurant_templates() -> RestaurantTemplateSet:
    return RestaurantTemplateSet(
        counter_service=_template(
            COUNTER_TEMPLATE_CODE,
            "counter_service",
            _COUNTER_DEFAULTS,
            {
                "service_session": "Service",
                "order": "Order",
                "station": "Kitchen / Bar",
                "table": "Table",
            },
        ),
        full_service=_template(
            FULL_SERVICE_TEMPLATE_CODE,
            "full_service",
            _FULL_SERVICE_DEFAULTS,
            {
                "service_session": "Dining Service",
                "order": "Order",
                "station": "Kitchen / Bar",
                "table": "Table",
            },
        ),
    )


def build_wnd_profile() -> WNDTenantProfile:
    return WNDTenantProfile(
        profile_code=WND_PROFILE_CODE,
        structure=WNDStructureProfile(
            tenant_code=WND_PROOF_TENANT_CODE,
            tenant_name="Wine & Dine — Track B Proof",
            country_code="CM",
            currency="XAF",
            locale="fr-CM",
            timezone="Africa/Douala",
            legal_entity_code="WND-CM",
            legal_entity_name="Wine & Dine Cameroon",
            organization_code="WND",
            organization_name="Wine & Dine",
            location_code="LOGPOM",
            location_name="Logpom",
        ),
        template_code=COUNTER_TEMPLATE_CODE,
        template_version=TEMPLATE_VERSION,
        template_overrides={
            "restaurant.service_modes.enabled": ["dine_in", "takeaway", "delivery"],
            "restaurant.tips.enabled": False,
            "restaurant.commissions.enabled": True,
        },
        calendar=WNDCalendarProfile(
            calendar_code="wnd.operations",
            timezone="Africa/Douala",
            business_day_boundary=time(8, 0),
            day_start=time(8, 0),
            day_end=time(18, 0),
            night_start=time(18, 0),
            night_end=time(8, 0),
            payment_shift_cutoff=time(18, 0),
            commission_attribution_basis="original_order_creator",
        ),
        payment_configuration={
            "settlement_methods": ["cash", "mtn", "orange"],
            "composition_options": ["split", "unpaid_receivable"],
            "accounting_channels": ["cash", "mtn", "orange", "xafpay", "bank", "ar", "ap"],
        },
        branding=WNDBrandingProfile(
            business_display_name="Wine & Dine",
            branding_asset_reference="asset:tenant/wnd/logo-primary",
            terminology={
                "order": "Order",
                "cashier": "Cashier",
                "kitchen": "Kitchen",
                "waiter": "Waiter",
                "sales_archive": "Sales Archive",
            },
        ),
        migration_mappings={
            "menu_catalog": "legacy atomic_units/taxonomy -> SO1 catalog + R2 menu projections at R6",
            "staff_roles": "legacy WND roles -> PC5 tenant roles + R1 operational attribution at R6",
            "taxonomy_overlay": "legacy WND taxonomy -> PC3/SC41 tenant overlay/mapping plan at R6",
            "finance": "R3 semantic plans -> Neutral Finance; legacy financial writers retire only at R6",
            "documents": "kitchen bon/receipts -> SO7/SO8 handoff; no provider topology embedded in Restaurant",
            "inventory": "legacy inventory evidence -> SO3 under Track A exactly-once invariants at R6",
        },
        production_cutover_authorized=False,
    )


def build_composition_plan() -> WNDCompositionPlan:
    profile = build_wnd_profile()
    templates = build_restaurant_templates()
    body = {
        "profile_code": profile.profile_code,
        "template": f"{profile.template_code}@{profile.template_version}",
        "pack": f"{PACK_CODE}@{PACK_VERSION}",
        "location": profile.structure.location_code,
        "business_day_boundary": profile.calendar.business_day_boundary.isoformat(),
        "payment_shift_cutoff": profile.calendar.payment_shift_cutoff.isoformat(),
        "production_cutover": False,
    }
    return WNDCompositionPlan(
        profile=profile,
        templates=templates,
        pack_code=PACK_CODE,
        pack_version=PACK_VERSION,
        database_schema_change="NONE",
        production_cutover_authorized=False,
        metadata={"plan_fingerprint": sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()},
    )


def build_provision_command() -> ProvisionTenant:
    p = build_wnd_profile().structure
    return ProvisionTenant(
        "r5-provision-wnd-logpom-proof",
        p.tenant_code,
        p.tenant_name,
        p.country_code,
        p.currency,
        p.locale,
        p.timezone,
        p.legal_entity_code,
        p.legal_entity_name,
        p.organization_code,
        p.organization_name,
        p.location_code,
        p.location_name,
        LocationKind.PHYSICAL,
    )


def register_templates(pk456_authority):
    templates = build_restaurant_templates()
    return (
        pk456_authority.register_template(
            RegisterTemplateVersion("r5-register-restaurant-counter-service-1.0.0", templates.counter_service)
        ),
        pk456_authority.register_template(
            RegisterTemplateVersion("r5-register-restaurant-full-service-1.0.0", templates.full_service)
        ),
    )


def activate_restaurant_pack(pack_authority, tenant_id: int):
    staged = pack_authority.stage(
        StagePack("r5-stage-industry.restaurant-1.0.0", tenant_id, PACK_CODE, PACK_VERSION)
    )
    installed = pack_authority.install(
        InstallPack(
            "r5-install-industry.restaurant-1.0.0",
            tenant_id,
            PACK_CODE,
            PACK_VERSION,
            1,
        )
    )
    active = pack_authority.activate(
        ActivatePack(
            "r5-activate-industry.restaurant-1.0.0",
            tenant_id,
            PACK_CODE,
            PACK_VERSION,
            2,
        )
    )
    return active


def plan_and_apply_wnd_template(pk456_authority, tenant_id: int):
    profile = build_wnd_profile()
    plan = pk456_authority.plan_application(
        PlanTemplateApplication(
            tenant_id=tenant_id,
            template_code=profile.template_code,
            version=profile.template_version,
            selected_optional_packs=(),
            overrides=profile.template_overrides,
        )
    )
    state = pk456_authority.apply_template(
        ApplyTemplate(
            "r5-apply-wnd-logpom-restaurant-template-1.0.0",
            tenant_id,
            profile.template_code,
            profile.template_version,
            plan.plan_sha256,
            (),
            profile.template_overrides,
        )
    )
    return plan, state


def _flatten_configuration(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, child in sorted(value.items()):
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(_flatten_configuration(child, path))
        else:
            result[path] = child
    return result



def build_wnd_calendar(tenant_id: int) -> BusinessCalendarVersion:
    profile = build_wnd_profile()
    return BusinessCalendarVersion(
        tenant_id=tenant_id,
        calendar_code=profile.calendar.calendar_code,
        version=1,
        timezone_name=profile.calendar.timezone,
        business_day_boundary=profile.calendar.business_day_boundary,
        operating_weekdays=(0, 1, 2, 3, 4, 5, 6),
        effective_from=EFFECTIVE_FROM,
        effective_to=None,
        shifts=(
            ShiftRule("day", "Day", profile.calendar.day_start, profile.calendar.day_end),
            ShiftRule("night", "Night", profile.calendar.night_start, profile.calendar.night_end),
        ),
    )


def build_wnd_localization(tenant_id: int) -> LocalizationProfile:
    profile = build_wnd_profile()
    return LocalizationProfile(
        tenant_id=tenant_id,
        locale_code=profile.structure.locale,
        timezone_name=profile.structure.timezone,
        date_format="DD/MM/YYYY",
        decimal_separator=",",
        currency_display="XAF",
        business_display_name=profile.branding.business_display_name,
        branding_asset_reference=profile.branding.branding_asset_reference,
        terminology=profile.branding.terminology,
    )


def apply_wnd_operating_context(operating_authority, tenant_id: int, effective_configuration: dict[str, Any]):
    profile = build_wnd_profile()

    for key, kind in _GENERIC_CONFIG_DEFINITIONS:
        operating_authority.define(
            DefineConfiguration(
                f"r5-define-{key}",
                key,
                kind,
                "restaurant",
                (ConfigScope.TENANT,),
                (ConfigScope.TENANT,),
                False,
                False,
                True,
                None,
                None,
            )
        )

    for key, kind, constraints in _WND_CONFIG_DEFINITIONS:
        operating_authority.define(
            DefineConfiguration(
                f"r5-define-{key}",
                key,
                kind,
                "wnd",
                (ConfigScope.TENANT,),
                (ConfigScope.TENANT,),
                True,
                False,
                False,
                constraints,
                None,
            )
        )

    flat = _flatten_configuration(effective_configuration)
    expected = {key for key, _kind in _GENERIC_CONFIG_DEFINITIONS}
    if set(flat) != expected:
        raise ValueError(f"R5_TEMPLATE_CONFIGURATION_KEYS={sorted(flat)}")

    for key, value in sorted(flat.items()):
        operating_authority.set_value(
            SetConfiguration(
                f"r5-set-{tenant_id}-{key}",
                tenant_id,
                key,
                ConfigScope.TENANT,
                tenant_id,
                value,
                EFFECTIVE_FROM,
            )
        )

    operating_authority.set_value(
        SetConfiguration(
            f"r5-set-{tenant_id}-wnd.payment_shift.cutoff_local_time",
            tenant_id,
            "wnd.payment_shift.cutoff_local_time",
            ConfigScope.TENANT,
            tenant_id,
            profile.calendar.payment_shift_cutoff,
            EFFECTIVE_FROM,
        )
    )
    operating_authority.set_value(
        SetConfiguration(
            f"r5-set-{tenant_id}-wnd.payments.enabled_methods",
            tenant_id,
            "wnd.payments.enabled_methods",
            ConfigScope.TENANT,
            tenant_id,
            profile.payment_configuration,
            EFFECTIVE_FROM,
        )
    )
    operating_authority.set_value(
        SetConfiguration(
            f"r5-set-{tenant_id}-wnd.commission.attribution_basis",
            tenant_id,
            "wnd.commission.attribution_basis",
            ConfigScope.TENANT,
            tenant_id,
            profile.calendar.commission_attribution_basis,
            EFFECTIVE_FROM,
        )
    )

    calendar = build_wnd_calendar(tenant_id)
    operating_authority.register_calendar(
        RegisterBusinessCalendar("r5-register-wnd-operations-calendar-v1", calendar)
    )
    operating_authority.set_localization(
        SetLocalizationProfile(
            "r5-set-wnd-localization",
            build_wnd_localization(tenant_id),
            EFFECTIVE_FROM,
        )
    )
    return calendar


def configuration_keys() -> tuple[str, ...]:
    return tuple(key for key, _kind in _GENERIC_CONFIG_DEFINITIONS) + tuple(
        key for key, _kind, _constraints in _WND_CONFIG_DEFINITIONS
    )


def plan_fingerprint() -> str:
    return build_composition_plan().metadata["plan_fingerprint"]
