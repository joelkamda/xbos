"""SQL-backed PC1 explicit stable tenant identity import; caller owns transaction."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .contracts import StructuralContext
from .identity_import_contract import ImportTenantIdentity
from .service import StructuralAuthority, StructuralAuthorityError
from .sql_repository import SQLStructuralRepository


class SQLTenantIdentityImportRepository:
    def __init__(self, session: Session):
        self.session = session
        self.structural = SQLStructuralRepository(session)

    def _one(self, sql: str, values: dict[str, Any]) -> dict[str, Any] | None:
        row = self.session.execute(text(sql), values).mappings().first()
        return dict(row) if row else None

    def _resolve(self, result: dict[str, Any]) -> StructuralContext:
        return StructuralAuthority(self.structural).resolve(
            tenant_id=result["tenant_id"],
            organization_unit_id=result["organization_unit_id"],
            legal_entity_id=result["legal_entity_id"],
            location_id=result["location_id"],
        )

    def import_tenant(
        self, command: ImportTenantIdentity, request_fingerprint: str
    ) -> StructuralContext:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": command.command_key},
        )
        self.session.execute(text("LOCK TABLE public.tenants IN SHARE ROW EXCLUSIVE MODE"))

        prior = self._one(
            """SELECT request_fingerprint,tenant_id,result_context
               FROM public.tenant_provisioning_commands WHERE command_key=:key""",
            {"key": command.command_key},
        )
        if prior:
            if prior["request_fingerprint"] != request_fingerprint:
                raise StructuralAuthorityError(
                    "conflicting_tenant_identity_import_replay"
                )
            if not prior["result_context"]:
                raise StructuralAuthorityError("incomplete_tenant_identity_import")
            return self._resolve(prior["result_context"])

        by_id = self._one(
            "SELECT id,code,name FROM public.tenants WHERE id=:id",
            {"id": command.tenant_id},
        )
        if by_id:
            if by_id["code"] == command.tenant_code and by_id["name"] == command.tenant_name:
                raise StructuralAuthorityError("unowned_existing_tenant_identity")
            raise StructuralAuthorityError("tenant_id_collision")

        by_code = self._one(
            "SELECT id FROM public.tenants WHERE code=:code",
            {"code": command.tenant_code},
        )
        if by_code:
            raise StructuralAuthorityError("tenant_code_collision")

        self.session.execute(
            text(
                """INSERT INTO public.tenant_provisioning_commands
                   (command_key,request_fingerprint)
                   VALUES (:key,:fingerprint)"""
            ),
            {"key": command.command_key, "fingerprint": request_fingerprint},
        )
        tenant = self._one(
            """INSERT INTO public.tenants
               (id,code,name,country_code,currency,locale,timezone,lifecycle_state)
               VALUES (:id,:code,:name,:country,:currency,:locale,:timezone,'active')
               RETURNING id""",
            {
                "id": command.tenant_id,
                "code": command.tenant_code,
                "name": command.tenant_name,
                "country": command.country_code,
                "currency": command.currency,
                "locale": command.locale,
                "timezone": command.timezone,
            },
        )
        legal = self._one(
            """INSERT INTO public.legal_entities
               (tenant_id,code,legal_name,jurisdiction_code)
               VALUES (:tenant,:code,:name,:jurisdiction)
               RETURNING id""",
            {
                "tenant": command.tenant_id,
                "code": command.legal_entity_code,
                "name": command.legal_entity_name,
                "jurisdiction": command.country_code,
            },
        )
        organization = self._one(
            """INSERT INTO public.organization_units
               (tenant_id,unit_type,code,name,timezone_name,legal_entity_id)
               VALUES (:tenant,'root',:code,:name,:timezone,:legal)
               RETURNING id""",
            {
                "tenant": command.tenant_id,
                "code": command.root_organization_code,
                "name": command.root_organization_name,
                "timezone": command.timezone,
                "legal": legal["id"],
            },
        )
        location = self._one(
            """INSERT INTO public.locations
               (tenant_id,legal_entity_id,code,name,location_kind,timezone_name)
               VALUES (:tenant,:legal,:code,:name,:kind,:timezone)
               RETURNING id""",
            {
                "tenant": command.tenant_id,
                "legal": legal["id"],
                "code": command.primary_location_code,
                "name": command.primary_location_name,
                "kind": command.primary_location_kind.value,
                "timezone": command.timezone,
            },
        )

        seq = self.session.execute(
            text("SELECT pg_get_serial_sequence('public.tenants','id')")
        ).scalar_one_or_none()
        max_id = int(
            self.session.execute(text("SELECT max(id) FROM public.tenants")).scalar_one()
        )
        if seq:
            last_value = self.session.execute(
                text("SELECT pg_sequence_last_value(CAST(:seq AS regclass))"),
                {"seq": seq},
            ).scalar_one_or_none()
            if last_value is None or int(last_value) < max_id:
                self.session.execute(
                    text("SELECT setval(CAST(:seq AS regclass),:target,true)"),
                    {"seq": seq, "target": max_id},
                )

        result = {
            "tenant_id": tenant["id"],
            "organization_unit_id": organization["id"],
            "legal_entity_id": legal["id"],
            "location_id": location["id"],
            "identity_mode": command.identity_mode,
            "authority_reference": command.authority_reference,
        }
        self.session.execute(
            text(
                """UPDATE public.tenant_provisioning_commands
                   SET tenant_id=:tenant,result_context=CAST(:result AS jsonb),completed_at=now()
                   WHERE command_key=:key"""
            ),
            {
                "tenant": command.tenant_id,
                "result": json.dumps(result, sort_keys=True),
                "key": command.command_key,
            },
        )
        return self._resolve(result)
