"""PC1 structural authority and fail-closed resolver."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Protocol

from .contracts import LegalEntity, Location, OrganizationUnit, ProvisionTenant, StructuralContext, Tenant, TenantLifecycle


class StructuralAuthorityError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class StructuralRepository(Protocol):
    def tenant(self, tenant_id: int) -> Tenant | None: ...
    def organization_unit(self, tenant_id: int, organization_unit_id: int) -> OrganizationUnit | None: ...
    def legal_entity(self, tenant_id: int, legal_entity_id: int) -> LegalEntity | None: ...
    def location(self, tenant_id: int, location_id: int) -> Location | None: ...
    def organization_units(self, tenant_id: int) -> tuple[OrganizationUnit, ...]: ...
    def legal_entities(self, tenant_id: int) -> tuple[LegalEntity, ...]: ...
    def locations(self, tenant_id: int) -> tuple[Location, ...]: ...
    def branch_mapping(self, tenant_id: int, branch_id: int) -> tuple[int, int] | None: ...
    def provision(self, command: ProvisionTenant, request_fingerprint: str) -> StructuralContext: ...
    def transition_tenant(self, tenant_id: int, expected_version: int, target: TenantLifecycle) -> Tenant: ...


class StructuralAuthority:
    def __init__(self, repository: StructuralRepository):
        self.repository = repository

    @staticmethod
    def request_fingerprint(command: ProvisionTenant) -> str:
        payload = json.dumps(command.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def provision(self, command: ProvisionTenant) -> StructuralContext:
        if not command.command_key.strip() or not command.tenant_code.strip():
            raise StructuralAuthorityError("invalid_provisioning_identity")
        return self.repository.provision(command, self.request_fingerprint(command))

    def transition_tenant(self, tenant_id: int, expected_version: int, target: TenantLifecycle) -> Tenant:
        tenant = self.repository.tenant(tenant_id)
        if tenant is None:
            raise StructuralAuthorityError("tenant_not_found")
        allowed = {
            TenantLifecycle.PROVISIONED: {TenantLifecycle.ACTIVE, TenantLifecycle.RETIRED},
            TenantLifecycle.ACTIVE: {TenantLifecycle.SUSPENDED, TenantLifecycle.RETIRED},
            TenantLifecycle.SUSPENDED: {TenantLifecycle.ACTIVE, TenantLifecycle.RETIRED},
            TenantLifecycle.RETIRED: set(),
        }
        if target not in allowed[tenant.lifecycle]:
            raise StructuralAuthorityError("invalid_tenant_lifecycle_transition")
        return self.repository.transition_tenant(tenant_id, expected_version, target)

    def ancestry(self, tenant_id: int, organization_unit_id: int) -> tuple[int, ...]:
        current = self._organization(tenant_id, organization_unit_id)
        result: list[int] = []
        seen: set[int] = set()
        while current:
            if current.id in seen:
                raise StructuralAuthorityError("organization_cycle")
            seen.add(current.id)
            result.append(current.id)
            if current.parent_id is None:
                break
            current = self._organization(tenant_id, current.parent_id)
        return tuple(reversed(result))

    def resolve(
        self, *, tenant_id: int, organization_unit_id: int | None = None,
        legal_entity_id: int | None = None, location_id: int | None = None,
        legacy_branch_id: int | None = None,
    ) -> StructuralContext:
        tenant = self._tenant(tenant_id)
        if legacy_branch_id is not None:
            mapped = self.repository.branch_mapping(tenant_id, legacy_branch_id)
            if mapped is None:
                raise StructuralAuthorityError("unmapped_legacy_branch")
            if organization_unit_id not in (None, mapped[0]) or location_id not in (None, mapped[1]):
                raise StructuralAuthorityError("conflicting_structural_context")
            organization_unit_id, location_id = mapped
        organization = self._organization(tenant_id, organization_unit_id) if organization_unit_id else None
        location = self._location(tenant_id, location_id) if location_id else None
        inferred = {value for value in (
            legal_entity_id,
            organization.legal_entity_id if organization else None,
            location.legal_entity_id if location else None,
        ) if value is not None}
        if len(inferred) > 1:
            raise StructuralAuthorityError("ambiguous_legal_entity_context")
        legal_entity = self._legal_entity(tenant_id, inferred.pop()) if inferred else None
        ancestry = self.ancestry(tenant_id, organization.id) if organization else ()
        return StructuralContext(tenant, organization, legal_entity, location, ancestry)

    def export(self, tenant_id: int) -> bytes:
        tenant = self._tenant(tenant_id)
        payload = {
            "schema": "xbos.pc1.structural-export.v1",
            "tenant": self._json(tenant),
            "organization_units": [self._json(item) for item in sorted(self.repository.organization_units(tenant_id), key=lambda x: (x.code, x.id))],
            "legal_entities": [self._json(item) for item in sorted(self.repository.legal_entities(tenant_id), key=lambda x: (x.code, x.id))],
            "locations": [self._json(item) for item in sorted(self.repository.locations(tenant_id), key=lambda x: (x.code, x.id))],
        }
        return (json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")

    @staticmethod
    def _json(value: object) -> dict[str, object]:
        result = asdict(value)
        for key, item in tuple(result.items()):
            if hasattr(item, "value"):
                result[key] = item.value
        return result

    def _tenant(self, tenant_id: int) -> Tenant:
        item = self.repository.tenant(tenant_id)
        if item is None:
            raise StructuralAuthorityError("tenant_not_found")
        if item.lifecycle in {TenantLifecycle.SUSPENDED, TenantLifecycle.RETIRED}:
            raise StructuralAuthorityError("tenant_unavailable")
        return item

    def _organization(self, tenant_id: int, item_id: int) -> OrganizationUnit:
        item = self.repository.organization_unit(tenant_id, item_id)
        if item is None:
            raise StructuralAuthorityError("organization_not_found_or_cross_tenant")
        return item

    def _legal_entity(self, tenant_id: int, item_id: int) -> LegalEntity:
        item = self.repository.legal_entity(tenant_id, item_id)
        if item is None:
            raise StructuralAuthorityError("legal_entity_not_found_or_cross_tenant")
        return item

    def _location(self, tenant_id: int, item_id: int) -> Location:
        item = self.repository.location(tenant_id, item_id)
        if item is None:
            raise StructuralAuthorityError("location_not_found_or_cross_tenant")
        return item
