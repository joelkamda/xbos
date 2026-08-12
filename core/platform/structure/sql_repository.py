"""SQLAlchemy-backed PC1 repository; callers own transaction scope."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .contracts import LegalEntity, Location, LocationKind, OrganizationUnit, ProvisionTenant, StructuralContext, Tenant, TenantLifecycle
from .service import StructuralAuthorityError


class SQLStructuralRepository:
    def __init__(self, session: Session):
        self.session = session

    def _one(self, sql: str, values: dict[str, Any]) -> dict[str, Any] | None:
        row = self.session.execute(text(sql), values).mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _tenant(row: dict[str, Any]) -> Tenant:
        return Tenant(row["id"], row["code"], row["name"], TenantLifecycle(row["lifecycle_state"]), row["country_code"], row["currency"], row["locale"], row["timezone"], row["row_version"])

    @staticmethod
    def _organization(row: dict[str, Any]) -> OrganizationUnit:
        return OrganizationUnit(row["id"], UUID(str(row["public_id"])), row["tenant_id"], row["code"], row["name"], row["unit_type"], row["parent_id"], row["legal_entity_id"], row["active"], row["row_version"])

    @staticmethod
    def _legal(row: dict[str, Any]) -> LegalEntity:
        return LegalEntity(row["id"], UUID(str(row["public_id"])), row["tenant_id"], row["code"], row["legal_name"], row["jurisdiction_code"], row["registration_reference"], row["active"], row["row_version"])

    @staticmethod
    def _location(row: dict[str, Any]) -> Location:
        return Location(row["id"], UUID(str(row["public_id"])), row["tenant_id"], row["code"], row["name"], LocationKind(row["location_kind"]), row["legal_entity_id"], row["timezone_name"], row["address"], row["active"], row["row_version"])

    def tenant(self, tenant_id: int) -> Tenant | None:
        row = self._one("SELECT id,code,name,lifecycle_state,country_code,currency,locale,timezone,row_version FROM tenants WHERE id=:id", {"id": tenant_id})
        return self._tenant(row) if row else None

    def organization_unit(self, tenant_id: int, organization_unit_id: int) -> OrganizationUnit | None:
        row = self._one("SELECT id,public_id,tenant_id,code,name,unit_type,parent_id,legal_entity_id,active,row_version FROM organization_units WHERE tenant_id=:tenant AND id=:id", {"tenant": tenant_id, "id": organization_unit_id})
        return self._organization(row) if row else None

    def legal_entity(self, tenant_id: int, legal_entity_id: int) -> LegalEntity | None:
        row = self._one("SELECT id,public_id,tenant_id,code,legal_name,jurisdiction_code,registration_reference,active,row_version FROM legal_entities WHERE tenant_id=:tenant AND id=:id", {"tenant": tenant_id, "id": legal_entity_id})
        return self._legal(row) if row else None

    def location(self, tenant_id: int, location_id: int) -> Location | None:
        row = self._one("SELECT id,public_id,tenant_id,code,name,location_kind,legal_entity_id,timezone_name,address,active,row_version FROM locations WHERE tenant_id=:tenant AND id=:id", {"tenant": tenant_id, "id": location_id})
        return self._location(row) if row else None

    def _many(self, sql: str, tenant_id: int, mapper: Any) -> tuple[Any, ...]:
        rows = self.session.execute(text(sql), {"tenant": tenant_id}).mappings().all()
        return tuple(mapper(dict(row)) for row in rows)

    def organization_units(self, tenant_id: int) -> tuple[OrganizationUnit, ...]:
        return self._many("SELECT id,public_id,tenant_id,code,name,unit_type,parent_id,legal_entity_id,active,row_version FROM organization_units WHERE tenant_id=:tenant ORDER BY code,id", tenant_id, self._organization)

    def legal_entities(self, tenant_id: int) -> tuple[LegalEntity, ...]:
        return self._many("SELECT id,public_id,tenant_id,code,legal_name,jurisdiction_code,registration_reference,active,row_version FROM legal_entities WHERE tenant_id=:tenant ORDER BY code,id", tenant_id, self._legal)

    def locations(self, tenant_id: int) -> tuple[Location, ...]:
        return self._many("SELECT id,public_id,tenant_id,code,name,location_kind,legal_entity_id,timezone_name,address,active,row_version FROM locations WHERE tenant_id=:tenant ORDER BY code,id", tenant_id, self._location)

    def branch_mapping(self, tenant_id: int, branch_id: int) -> tuple[int, int] | None:
        row = self._one("SELECT organization_unit_id,location_id FROM legacy_branch_structural_mappings WHERE tenant_id=:tenant AND branch_id=:branch", {"tenant": tenant_id, "branch": branch_id})
        return (row["organization_unit_id"], row["location_id"]) if row else None

    def transition_tenant(self, tenant_id: int, expected_version: int, target: TenantLifecycle) -> Tenant:
        row = self._one("""UPDATE tenants SET lifecycle_state=:target,
            suspended_at=CASE WHEN :target='suspended' THEN now() ELSE suspended_at END,
            retired_at=CASE WHEN :target='retired' THEN now() ELSE retired_at END,
            row_version=row_version+1 WHERE id=:id AND row_version=:version
            RETURNING id,code,name,lifecycle_state,country_code,currency,locale,timezone,row_version""",
            {"target": target.value, "id": tenant_id, "version": expected_version})
        if row is None:
            raise StructuralAuthorityError("tenant_concurrent_change")
        return self._tenant(row)

    def provision(self, command: ProvisionTenant, request_fingerprint: str) -> StructuralContext:
        self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": command.command_key})
        existing = self._one("SELECT request_fingerprint,result_context FROM tenant_provisioning_commands WHERE command_key=:key", {"key": command.command_key})
        if existing:
            if existing["request_fingerprint"] != request_fingerprint or not existing["result_context"]:
                raise StructuralAuthorityError("conflicting_provisioning_replay")
            result = existing["result_context"]
            from .service import StructuralAuthority
            return StructuralAuthority(self).resolve(tenant_id=result["tenant_id"], organization_unit_id=result["organization_unit_id"], legal_entity_id=result["legal_entity_id"], location_id=result.get("location_id"))
        self.session.execute(text("INSERT INTO tenant_provisioning_commands(command_key,request_fingerprint) VALUES (:key,:fingerprint)"), {"key": command.command_key, "fingerprint": request_fingerprint})
        tenant = self._one("""INSERT INTO tenants(code,name,country_code,currency,locale,timezone,lifecycle_state)
            VALUES (:code,:name,:country,:currency,:locale,:timezone,'active')
            RETURNING id,code,name,lifecycle_state,country_code,currency,locale,timezone,row_version""", {"code": command.tenant_code, "name": command.tenant_name, "country": command.country_code, "currency": command.currency, "locale": command.locale, "timezone": command.timezone})
        legal = self._one("""INSERT INTO legal_entities(tenant_id,code,legal_name) VALUES (:tenant,:code,:name)
            RETURNING id,public_id,tenant_id,code,legal_name,jurisdiction_code,registration_reference,active,row_version""", {"tenant": tenant["id"], "code": command.legal_entity_code, "name": command.legal_entity_name})
        organization = self._one("""INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,legal_entity_id)
            VALUES (:tenant,'root',:code,:name,:timezone,:legal) RETURNING id,public_id,tenant_id,code,name,unit_type,parent_id,legal_entity_id,active,row_version""", {"tenant": tenant["id"], "code": command.root_organization_code, "name": command.root_organization_name, "timezone": command.timezone, "legal": legal["id"]})
        location = None
        if command.primary_location_code:
            location = self._one("""INSERT INTO locations(tenant_id,legal_entity_id,code,name,location_kind,timezone_name)
                VALUES (:tenant,:legal,:code,:name,:kind,:timezone) RETURNING id,public_id,tenant_id,code,name,location_kind,legal_entity_id,timezone_name,address,active,row_version""", {"tenant": tenant["id"], "legal": legal["id"], "code": command.primary_location_code, "name": command.primary_location_name or command.primary_location_code, "kind": command.primary_location_kind.value, "timezone": command.timezone})
        result = {"tenant_id": tenant["id"], "organization_unit_id": organization["id"], "legal_entity_id": legal["id"], "location_id": location["id"] if location else None}
        self.session.execute(text("UPDATE tenant_provisioning_commands SET tenant_id=:tenant,result_context=CAST(:result AS jsonb),completed_at=now() WHERE command_key=:key"), {"tenant": tenant["id"], "result": json.dumps(result), "key": command.command_key})
        return StructuralContext(self._tenant(tenant), self._organization(organization), self._legal(legal), self._location(location) if location else None, (organization["id"],))
