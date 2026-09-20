"""PC1 additive authority for governed explicit stable tenant identity import."""
from __future__ import annotations

import hashlib
import json
from typing import Protocol

from .contracts import StructuralContext
from .identity_import_contract import ImportTenantIdentity
from .service import StructuralAuthorityError


class TenantIdentityImportRepository(Protocol):
    def import_tenant(
        self, command: ImportTenantIdentity, request_fingerprint: str
    ) -> StructuralContext: ...


class TenantIdentityImportAuthority:
    def __init__(self, repository: TenantIdentityImportRepository):
        self.repository = repository

    @staticmethod
    def request_fingerprint(command: ImportTenantIdentity) -> str:
        payload = json.dumps(
            command.canonical_payload(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def import_tenant(self, command: ImportTenantIdentity) -> StructuralContext:
        provision = command.as_provision_tenant()
        required = (
            command.command_key,
            command.tenant_code,
            command.tenant_name,
            command.country_code,
            command.currency,
            command.locale,
            command.timezone,
            command.legal_entity_code,
            command.legal_entity_name,
            command.root_organization_code,
            command.root_organization_name,
            command.primary_location_code,
            command.primary_location_name,
        )
        if command.tenant_id <= 0 or any(not str(value).strip() for value in required):
            raise StructuralAuthorityError("invalid_tenant_identity_import")
        if command.identity_mode != "explicit_stable_id_import":
            raise StructuralAuthorityError("invalid_tenant_identity_mode")
        if provision.primary_location_kind.value not in {"physical", "virtual"}:
            raise StructuralAuthorityError("invalid_location_kind")
        return self.repository.import_tenant(
            command, self.request_fingerprint(command)
        )
