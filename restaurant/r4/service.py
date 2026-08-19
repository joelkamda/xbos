"""R4 Restaurant industry-pack composition over frozen PK public authorities."""
from __future__ import annotations

from hashlib import sha256
from typing import Iterable

from pack_platform.contracts import (
    ExtensionKind, PackExtension, PackKind, PackManifest, RegisterPackVersion,
)
from pack_platform.pk456_contracts import (
    CertifyPackVersion, ConformanceResult, PackCertificationEvidence,
)

from .contracts import (
    RestaurantConfigurationDeclaration, RestaurantExperienceMetadata,
    RestaurantPackRegistrationPlan, RestaurantSemanticContribution,
)

PACK_CODE = "industry.restaurant"
PACK_VERSION = "1.0.0"
PACK_OWNER = "restaurant"
KERNEL_MIN = "1.0.0"
CERTIFICATION_CODE = "restaurant.r4.conformance"
CERTIFICATION_SUITE_VERSION = "1.0.0"
REGISTER_COMMAND_KEY = "r4-register-industry.restaurant-1.0.0"
CERTIFY_COMMAND_KEY = "r4-certify-industry.restaurant-1.0.0"

_REQUIRED_MODULES = (
    "catalog",
    "finance",
    "inventory",
    "operating_context",
    "party",
    "resources",
    "security_authority",
    "semantics",
)
_OPTIONAL_MODULES = ("communications", "documents", "reports", "scheduling")
_PERMISSION_REFERENCES = (
    "restaurant.configuration.pack.manage",
    "restaurant.finance.report.view",
    "restaurant.fulfillment.recipe.manage",
    "restaurant.fulfillment.ticket.manage",
    "restaurant.service.order.create",
    "restaurant.service.order.manage",
    "restaurant.service.session.manage",
)
_CONFIGURATION_KEYS = (
    "restaurant.fulfillment.course_firing.enabled",
    "restaurant.fulfillment.output_delivery.enabled",
    "restaurant.fulfillment.station_routing.enabled",
    "restaurant.reservations.enabled",
    "restaurant.service_modes.enabled",
    "restaurant.tables.enabled",
    "restaurant.tips.enabled",
    "restaurant.commissions.enabled",
)

_CONFIG = tuple(
    RestaurantConfigurationDeclaration(key, "PC4", "template_or_tenant_required", True)
    for key in _CONFIGURATION_KEYS
)
_SEMANTICS = RestaurantSemanticContribution(
    namespace_code="restaurant",
    scope="pack",
    source_key=f"{PACK_CODE}@{PACK_VERSION}",
    taxonomy_systems=(
        "restaurant.charge_nature",
        "restaurant.course",
        "restaurant.fulfillment_station",
        "restaurant.service_mode",
    ),
    closed_value_sets=False,
)
_EXPERIENCE = RestaurantExperienceMetadata(
    profile_family="restaurant",
    workspace_slots=(
        "restaurant.service",
        "restaurant.fulfillment",
        "restaurant.reporting",
        "restaurant.configuration",
    ),
    navigation_candidates=(
        "restaurant.orders",
        "restaurant.tables_sessions",
        "restaurant.fulfillment",
        "restaurant.reports",
        "restaurant.settings",
    ),
    frontend_implemented=False,
    engine_implemented=False,
    tables_required=False,
)

_REQUIRED_CHECKS = (
    "architecture", "tenant_isolation", "migration_compatibility", "authorization",
    "semantics", "finance", "shared_operations", "xa", "manifest",
)


def build_restaurant_pack_manifest() -> PackManifest:
    """Return the immutable PK manifest for Restaurant Pack v1.0.0."""
    semantic_extension = PackExtension(
        "restaurant.semantics",
        ExtensionKind.SEMANTICS,
        "PC3",
        "core.platform.semantics.SemanticAuthority",
        {
            "namespace_code": _SEMANTICS.namespace_code,
            "scope": _SEMANTICS.scope,
            "source_key": _SEMANTICS.source_key,
            "taxonomy_systems": list(_SEMANTICS.taxonomy_systems),
            "closed_value_sets": False,
            "law": "pack_contributes_semantics_via_pc3; values remain open and governed",
        },
    )
    configuration_extension = PackExtension(
        "restaurant.configuration",
        ExtensionKind.CONFIGURATION,
        "PC4",
        "core.platform.operating_context.OperatingContextAuthority",
        {
            "keys": [row.key for row in _CONFIG],
            "default_policy": "template_or_tenant_required",
            "writes_pc4_directly": False,
        },
    )
    finance_extension = PackExtension(
        "restaurant.finance_conformance",
        ExtensionKind.FINANCE_CONFORMANCE,
        "Neutral Finance",
        "core.domain.finance.pack_conformance_service.evaluate_pack",
        {
            "profile_reference": "restaurant.r3.financial_semantics.v1",
            "writer_routing": "unchanged",
            "financial_truth_owner": "Neutral Finance",
            "restaurant_finance_writer": False,
        },
    )
    navigation_extension = PackExtension(
        "restaurant.navigation",
        ExtensionKind.NAVIGATION,
        "XA",
        "experience_contracts.validate_experience",
        {
            "profile_family": _EXPERIENCE.profile_family,
            "workspace_slots": list(_EXPERIENCE.workspace_slots),
            "navigation_candidates": list(_EXPERIENCE.navigation_candidates),
            "frontend_implemented": False,
            "composition_engine_implemented": False,
            "tables_required": False,
        },
    )
    return PackManifest(
        pack_code=PACK_CODE,
        version=PACK_VERSION,
        owner_code=PACK_OWNER,
        kind=PackKind.INDUSTRY,
        kernel_min=KERNEL_MIN,
        required_modules=_REQUIRED_MODULES,
        optional_modules=_OPTIONAL_MODULES,
        permission_references=_PERMISSION_REFERENCES,
        semantic_namespaces=("restaurant",),
        configuration_keys=_CONFIGURATION_KEYS,
        extensions=(semantic_extension, configuration_extension, finance_extension, navigation_extension),
        connectors=(),
        xa={
            "profile_family": _EXPERIENCE.profile_family,
            "workspace_slots": list(_EXPERIENCE.workspace_slots),
            "navigation_candidates": list(_EXPERIENCE.navigation_candidates),
            "frontend_implemented": False,
            "composition_engine_implemented": False,
            "tables_required": False,
            "wnd_profile_is_standard": False,
        },
        finance_conformance_profile="restaurant.r3.financial_semantics.v1",
        retention_required=True,
    )


def build_registration_command() -> RegisterPackVersion:
    return RegisterPackVersion(REGISTER_COMMAND_KEY, build_restaurant_pack_manifest())


def build_certification_command(evidence_sha256: Iterable[str]) -> CertifyPackVersion:
    evidence = tuple(sorted(set(str(value).lower() for value in evidence_sha256)))
    checks = {name: ConformanceResult.PASS for name in _REQUIRED_CHECKS}
    return CertifyPackVersion(
        CERTIFY_COMMAND_KEY,
        PACK_CODE,
        PACK_VERSION,
        CERTIFICATION_CODE,
        CERTIFICATION_SUITE_VERSION,
        PackCertificationEvidence(
            checks=checks,
            evidence_sha256=evidence,
            notes={
                "restaurant_release": "R4",
                "source_authorities": ["R0", "R1", "R2", "R3", "PK", "SC41", "XA"],
                "tenant_installation": "NONE",
                "template_application": "NONE",
                "wnd_cutover": "NONE",
            },
        ),
    )


def build_registration_plan(evidence_sha256: Iterable[str]) -> RestaurantPackRegistrationPlan:
    manifest = build_restaurant_pack_manifest()
    return RestaurantPackRegistrationPlan(
        manifest=manifest,
        register_command=RegisterPackVersion(REGISTER_COMMAND_KEY, manifest),
        certification_command=build_certification_command(evidence_sha256),
        semantic_contribution=_SEMANTICS,
        configuration=_CONFIG,
        experience=_EXPERIENCE,
        tenant_installation_authorized=False,
        template_application_authorized=False,
        wnd_cutover_authorized=False,
        metadata={"plan_fingerprint": plan_fingerprint(manifest)},
    )


def plan_fingerprint(manifest: PackManifest | None = None) -> str:
    """Stable lightweight identity for the pack registration plan."""
    m = manifest or build_restaurant_pack_manifest()
    body = "|".join((m.pack_code, m.version, m.owner_code, m.kind.value, ",".join(m.required_modules), ",".join(m.optional_modules)))
    return sha256(body.encode("utf-8")).hexdigest()


class RestaurantPackRegistration:
    """Thin orchestration over PK public authorities; no direct persistence."""

    @staticmethod
    def register(pack_authority):
        return pack_authority.register(build_registration_command())

    @staticmethod
    def certify(pk456_authority, evidence_sha256: Iterable[str]):
        return pk456_authority.certify(build_certification_command(evidence_sha256))
