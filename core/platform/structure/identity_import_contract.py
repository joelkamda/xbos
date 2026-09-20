"""Additive PC1 stable tenant-identity import contract for XGI2."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .contracts import LocationKind, ProvisionTenant


@dataclass(frozen=True)
class ImportTenantIdentity:
    command_key: str
    tenant_id: int
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
    primary_location_code: str
    primary_location_name: str
    primary_location_kind: LocationKind = LocationKind.PHYSICAL
    identity_mode: str = "explicit_stable_id_import"
    authority_reference: str = "XBOS-XGI2-R4D-FOUNDATION-SOURCE-MATERIALIZATION"

    def as_provision_tenant(self) -> ProvisionTenant:
        return ProvisionTenant(
            command_key=self.command_key,
            tenant_code=self.tenant_code,
            tenant_name=self.tenant_name,
            country_code=self.country_code,
            currency=self.currency,
            locale=self.locale,
            timezone=self.timezone,
            legal_entity_code=self.legal_entity_code,
            legal_entity_name=self.legal_entity_name,
            root_organization_code=self.root_organization_code,
            root_organization_name=self.root_organization_name,
            primary_location_code=self.primary_location_code,
            primary_location_name=self.primary_location_name,
            primary_location_kind=self.primary_location_kind,
        )

    def canonical_payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["primary_location_kind"] = self.primary_location_kind.value
        return value
