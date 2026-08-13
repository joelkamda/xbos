"""PC6 proof-only orchestration over accepted PC1-PC5 public authorities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


PROFILE_SCHEMA = "xbos.pc6.tenant-profile.v1"
EXPORT_SCHEMA = "xbos.pc6.platform-core-portable-export.v1"
PORTABILITY_CLASSES = ("PORTABLE", "REFERENCE_ONLY", "EXCLUDED", "SECRET", "HISTORICAL_EVIDENCE")
FORBIDDEN_KEYS = frozenset({
    "password", "password_hash", "token", "access_token", "refresh_token", "api_key",
    "secret", "secret_material", "session_token", "signing_key", "private_key",
})


class NeutralProofError(ValueError):
    pass


@dataclass(frozen=True)
class TenantProfile:
    payload: Mapping[str, Any]
    canonical_bytes: bytes
    sha256: str

    @property
    def profile_id(self) -> str:
        return str(self.payload["profile_id"])


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str) + "\n").encode("utf-8")


def _walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", str(key).casefold(), child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _secret_safe(value: Mapping[str, Any]) -> None:
    for path, key, child in _walk(value):
        if key in FORBIDDEN_KEYS:
            raise NeutralProofError(f"credential_or_secret_field_forbidden={path}")
        if isinstance(child, str) and child.casefold().startswith(("postgresql://", "postgresql+psycopg2://", "data:", "file:")):
            raise NeutralProofError(f"credential_or_embedded_asset_forbidden={path}")


def validate_profile(payload: Mapping[str, Any]) -> TenantProfile:
    if payload.get("schema") != PROFILE_SCHEMA:
        raise NeutralProofError("unsupported_profile_schema")
    _secret_safe(payload)
    required = {"profile_id", "tenant", "structure", "parties", "semantics", "configuration", "calendar", "localization", "capability", "security", "proof_dimensions"}
    if set(payload) != required | {"schema"}:
        raise NeutralProofError("profile_sections_incomplete_or_unknown")
    tenant = payload["tenant"]
    if not all(str(tenant.get(key, "")).strip() for key in ("code", "name", "country_code", "currency", "locale", "timezone")):
        raise NeutralProofError("tenant_profile_identity_incomplete")
    if tenant["code"].casefold() in {"wnd", "wine-and-dine", "wine_dine"}:  # wnd_profile_forbidden
        raise NeutralProofError("wnd_profile_forbidden")
    dimensions = payload["proof_dimensions"]
    if not isinstance(dimensions, list) or len(set(dimensions)) < 6:
        raise NeutralProofError("second_tenant_not_materially_different")
    calendar = payload["calendar"]
    if not calendar.get("shifts") or calendar.get("business_day_boundary") in {"08:00:00", "18:00:00"}:
        raise NeutralProofError("tenant_calendar_not_independent")
    data = _canonical(payload)
    return TenantProfile(payload, data, hashlib.sha256(data).hexdigest())


def load_profile(path: str | Path) -> TenantProfile:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NeutralProofError(f"invalid_profile={exc}") from exc
    return validate_profile(payload)


def bootstrap_profile(profile: TenantProfile, authorities: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one profile through public authority facades; transaction scope is caller-owned."""
    from core.platform.operating_context import (
        BusinessCalendarVersion, ConfigScope, ConfigType, DefineConfiguration, GrantEntitlement,
        LocalizationProfile, RegisterBusinessCalendar, RegisterModule, SetConfiguration,
        SetFeatureFlag, SetLocalizationProfile, SetModuleEnablement, ShiftRule,
    )
    from core.platform.party import CreateOrganizationParty, CreatePartyRelationship, CreatePerson, LinkLegalEntityParty
    from core.platform.security_authority import PermissionDefinition, RoleAssignment, ScopeType, StructuralScope
    from core.platform.semantics import CreateConcept, CreateNamespace, CreateSemanticVersion, NamespaceScope
    from core.platform.structure import LocationKind, ProvisionTenant

    required = {"structure", "party", "semantics", "operating_context", "security"}
    if set(authorities) != required:
        raise NeutralProofError("public_authority_set_incomplete_or_private")
    value = profile.payload; prefix = f"pc6:{profile.profile_id}"
    tenant = value["tenant"]; structure = value["structure"]
    context = authorities["structure"].provision(ProvisionTenant(
        f"{prefix}:tenant", tenant["code"], tenant["name"], tenant["country_code"], tenant["currency"], tenant["locale"], tenant["timezone"],
        structure["legal_entity_code"], structure["legal_entity_name"], structure["root_organization_code"], structure["root_organization_name"],
        structure["primary_location_code"], structure["primary_location_name"], LocationKind(structure["primary_location_kind"]),
    ))
    tenant_id = context.tenant.id
    parties = value["parties"]
    organization = authorities["party"].create_organization(CreateOrganizationParty(f"{prefix}:legal-party", tenant_id, parties["legal_organization_external_key"], structure["legal_entity_name"]))
    person = authorities["party"].create_person(CreatePerson(f"{prefix}:administrator-party", tenant_id, parties["administrator_external_key"], parties["administrator_given_name"], parties["administrator_family_name"]))
    authorities["party"].link_legal_entity(LinkLegalEntityParty(f"{prefix}:legal-link", tenant_id, context.legal_entity.id, organization.party.id))
    authorities["party"].create_relationship(CreatePartyRelationship(f"{prefix}:administrator-relationship", tenant_id, person.party.id, organization.party.id, parties["administrator_relationship"], True, date.fromisoformat(value["semantics"]["effective_from"])))
    semantic = value["semantics"]
    authorities["semantics"].create_namespace(CreateNamespace(f"{prefix}:namespace", semantic["namespace_code"], NamespaceScope.TENANT, semantic["owner_code"], tenant_id))
    authorities["semantics"].create_concept(CreateConcept(f"{prefix}:concept", semantic["namespace_code"], semantic["owner_code"], semantic["concept_code"]))
    authorities["semantics"].create_version(CreateSemanticVersion(f"{prefix}:concept-version", semantic["namespace_code"], semantic["owner_code"], semantic["concept_code"], 1, date.fromisoformat(semantic["effective_from"]), None, semantic["canonical_label"], semantic["definition"]))
    operating = authorities["operating_context"]
    stamp = datetime.fromisoformat(value["calendar"]["effective_from"])
    scopes = {"tenant": tenant_id, "location": context.location.id}
    for item in value["configuration"]:
        scope = ConfigScope(item["scope"]); key = item["key"]
        operating.define(DefineConfiguration(f"{prefix}:definition:{key}", key, ConfigType(item["value_type"]), "pc6", (scope,), (scope,)))
        operating.set_value(SetConfiguration(f"{prefix}:configuration:{key}", tenant_id, key, scope, scopes[item["scope"]], item["value"], stamp))
    capability = value["capability"]
    operating.register_module(RegisterModule(f"{prefix}:module", capability["module_code"], "pc6", "1", (capability["capability_code"],)))
    operating.set_module_enablement(SetModuleEnablement(f"{prefix}:module-enablement", tenant_id, capability["module_code"], True, stamp))
    operating.grant_entitlement(GrantEntitlement(f"{prefix}:entitlement", tenant_id, capability["capability_code"], stamp))
    operating.set_feature_flag(SetFeatureFlag(f"{prefix}:feature", tenant_id, capability["feature_flag"], True, stamp))
    calendar = value["calendar"]
    calendar_value = BusinessCalendarVersion(tenant_id, calendar["code"], 1, calendar["timezone"], time.fromisoformat(calendar["business_day_boundary"]), tuple(calendar["operating_weekdays"]), stamp, None, tuple(ShiftRule(item["code"], item["display_name"], time.fromisoformat(item["starts_at"]), time.fromisoformat(item["ends_at"])) for item in calendar["shifts"]))
    operating.register_calendar(RegisterBusinessCalendar(f"{prefix}:calendar", calendar_value))
    localization = value["localization"]
    operating.set_localization(SetLocalizationProfile(f"{prefix}:localization", LocalizationProfile(tenant_id, tenant["locale"], tenant["timezone"], localization["date_format"], localization["decimal_separator"], localization["currency_display"], localization["business_display_name"], localization["branding_asset_reference"], localization["terminology"]), stamp))
    security = value["security"]; authority = authorities["security"]
    identity = authority.create_identity(command_key=f"{prefix}:identity", login_name=security["administrator_login"], party_id=person.party.id)
    authority.add_membership(command_key=f"{prefix}:membership", identity_id=identity.id, tenant_id=tenant_id, valid_from=stamp, party_id=person.party.id)
    permission = PermissionDefinition(security["permission_code"], "pc6", "platform_context", "read", "ordinary", (ScopeType.ORGANIZATION_UNIT,), 1)
    authority.register_permission(command_key=f"{prefix}:permission", definition=permission)
    authority.create_role(command_key=f"{prefix}:role", role_code=security["role_code"], tenant_id=tenant_id, permissions=tuple(security["permission_codes"]))
    authority.assign_role(command_key=f"{prefix}:assignment", assignment=RoleAssignment(identity.id, tenant_id, security["role_code"], StructuralScope(ScopeType.ORGANIZATION_UNIT, context.organization_unit.id), stamp))
    return {"profile_id": profile.profile_id, "profile_sha256": profile.sha256, "tenant_id": tenant_id, "tenant_code": context.tenant.code, "organization_unit_id": context.organization_unit.id, "legal_entity_id": context.legal_entity.id, "location_id": context.location.id, "legal_party_public_id": str(organization.party.public_id), "administrator_party_public_id": str(person.party.public_id), "identity_id": identity.id, "identity_public_id": str(identity.public_id), "calendar": calendar_value}


def deterministic_export(profile: TenantProfile, state: Mapping[str, Any]) -> bytes:
    required = {"structure", "party", "semantics", "operating_context", "identity"}
    if set(state) != required:
        raise NeutralProofError("export_authority_set_incomplete_or_private")
    payload = {
        "schema": EXPORT_SCHEMA,
        "profile_id": profile.profile_id,
        "profile_sha256": profile.sha256,
        "classification": {
            "tenant_profile": "PORTABLE", "structure": "REFERENCE_ONLY", "party": "REFERENCE_ONLY", "semantics": "REFERENCE_ONLY", "operating_context": "REFERENCE_ONLY",
            "identity_membership_and_assignments": "REFERENCE_ONLY", "audit_evidence": "HISTORICAL_EVIDENCE",
            "credentials_and_secrets": "SECRET", "sessions": "EXCLUDED", "financial_data": "EXCLUDED",
        },
        "tenant_profile": dict(profile.payload),
        "state_snapshot": dict(state),
        "excluded": ["audit_evidence", "credential_material", "financial_data", "password_hashes", "secret_material", "sessions", "signing_keys", "tokens"],
    }
    _secret_safe(payload)
    return _canonical(payload)


def validate_export(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (TypeError, json.JSONDecodeError) as exc:
        raise NeutralProofError("invalid_portable_export") from exc
    if payload.get("schema") != EXPORT_SCHEMA or set(payload.get("classification", {}).values()) - set(PORTABILITY_CLASSES):
        raise NeutralProofError("invalid_portability_classification")
    _secret_safe(payload)
    if not {"credentials_and_secrets", "sessions", "financial_data"} <= set(payload["classification"]):
        raise NeutralProofError("portability_exclusions_incomplete")
    return payload


def restore_export(data: bytes, profile: TenantProfile, bootstrap: Callable[[TenantProfile], Mapping[str, Any]]) -> dict[str, Any]:
    payload = validate_export(data)
    if payload["profile_id"] != profile.profile_id or payload["profile_sha256"] != profile.sha256:
        raise NeutralProofError("profile_export_identity_mismatch")
    restored = dict(bootstrap(profile))
    if restored.get("tenant_code") != profile.payload["tenant"]["code"] or restored.get("profile_sha256") != profile.sha256:
        raise NeutralProofError("restore_identity_mismatch")
    return restored
