"""Industry-neutral PC1 structural contracts (standard-library only)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class TenantLifecycle(StrEnum):
    PROVISIONED = "provisioned"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class LocationKind(StrEnum):
    PHYSICAL = "physical"
    VIRTUAL = "virtual"


@dataclass(frozen=True)
class Tenant:
    id: int
    code: str
    name: str
    lifecycle: TenantLifecycle
    country_code: str
    currency: str
    locale: str
    timezone: str
    row_version: int = 1


@dataclass(frozen=True)
class OrganizationUnit:
    id: int
    public_id: UUID
    tenant_id: int
    code: str
    name: str
    unit_type: str
    parent_id: int | None = None
    legal_entity_id: int | None = None
    active: bool = True
    row_version: int = 1


@dataclass(frozen=True)
class LegalEntity:
    id: int
    public_id: UUID
    tenant_id: int
    code: str
    legal_name: str
    jurisdiction_code: str | None = None
    registration_reference: str | None = None
    active: bool = True
    row_version: int = 1


@dataclass(frozen=True)
class Location:
    id: int
    public_id: UUID
    tenant_id: int
    code: str
    name: str
    kind: LocationKind
    legal_entity_id: int | None = None
    timezone_name: str | None = None
    address: dict[str, Any] | None = None
    active: bool = True
    row_version: int = 1


@dataclass(frozen=True)
class StructuralContext:
    tenant: Tenant
    organization_unit: OrganizationUnit | None
    legal_entity: LegalEntity | None
    location: Location | None
    ancestry: tuple[int, ...]


@dataclass(frozen=True)
class ProvisionTenant:
    command_key: str
    tenant_code: str
    tenant_name: str
    country_code: str
    currency: str
    locale: str
    timezone: str
    legal_entity_code: str
    legal_entity_name: str
    root_organization_code: str
    root_organization_name: str
    primary_location_code: str | None = None
    primary_location_name: str | None = None
    primary_location_kind: LocationKind = LocationKind.PHYSICAL

    def canonical_payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["primary_location_kind"] = self.primary_location_kind.value
        return value
