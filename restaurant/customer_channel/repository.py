from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .contracts import (
    CHECKOUT_PERMISSION,
    H1BError,
    SERVICE_CREDENTIAL_REFERENCE,
    SERVICE_PRINCIPAL,
    BoundContact,
    ServiceAuthorization,
)
from .delivery_policy import DeliveryPolicyRecord
from .contracts import CatalogReadBinding


class CustomerChannelRepository:
    """XBOS persistence composition for the private Customer Channel seam.

    This repository owns no transaction boundary. The HTTP adapter opens one
    transaction per effecting operation so the confirmation claim and the full
    R1 order submission remain atomic.
    """

    def __init__(self, session: Session):
        self.session = session

    def service_authorization(self, tenant_id: int, *, at: datetime, rotation_slot: str) -> ServiceAuthorization:
        rows = self.session.execute(
            text(
                """
                SELECT DISTINCT
                    s.id service_identity_id,
                    s.public_id service_identity_public_id,
                    s.tenant_id,
                    a.scope_id location_id
                FROM service_identities s
                JOIN scoped_role_assignments a
                  ON a.principal_id=s.id
                 AND a.actor_type='service'
                 AND a.tenant_id=s.tenant_id
                JOIN authorization_roles r
                  ON r.id=a.role_id
                 AND r.status='active'
                JOIN authorization_role_permissions rp
                  ON rp.role_id=r.id
                 AND rp.effective_from<=:at
                 AND (rp.effective_to IS NULL OR :at<rp.effective_to)
                JOIN permission_definitions p
                  ON p.id=rp.permission_id
                WHERE s.tenant_id=:tenant
                  AND s.service_code=:service
                  AND s.owner_module='restaurant'
                  AND s.status='active'
                  AND s.revoked_at IS NULL
                  AND s.credential_reference=:credential
                  AND a.status='active'
                  AND a.scope_type='location'
                  AND a.scope_id IS NOT NULL
                  AND a.valid_from<=:at
                  AND (a.valid_to IS NULL OR :at<a.valid_to)
                  AND p.permission_code=:permission
                  AND p.owner_module='restaurant'
                  AND p.resource_code='customer_channel'
                  AND p.action_code='checkout'
                  AND p.status='active'
                  AND p.required_assurance=1
                  AND 'location'=ANY(p.allowed_scopes)
                ORDER BY a.scope_id
                """
            ),
            {
                "tenant": tenant_id,
                "service": SERVICE_PRINCIPAL,
                "credential": SERVICE_CREDENTIAL_REFERENCE,
                "permission": CHECKOUT_PERMISSION,
                "at": at,
            },
        ).mappings().all()
        identities = {(int(r["service_identity_id"]), UUID(str(r["service_identity_public_id"]))) for r in rows}
        locations = {int(r["location_id"]) for r in rows}
        if len(identities) != 1 or len(locations) != 1:
            raise H1BError("SERVICE_AUTH_FORBIDDEN")
        identity_id, identity_public = next(iter(identities))
        return ServiceAuthorization(
            identity_id,
            identity_public,
            tenant_id,
            next(iter(locations)),
            rotation_slot,
        )

    def branch_for_location(self, tenant_id: int, location_id: int) -> int:
        rows = self.session.execute(
            text(
                """
                SELECT branch_id
                FROM legacy_branch_structural_mappings
                WHERE tenant_id=:tenant AND location_id=:location
                ORDER BY branch_id
                """
            ),
            {"tenant": tenant_id, "location": location_id},
        ).scalars().all()
        values = tuple(dict.fromkeys(int(x) for x in rows))
        if len(values) != 1:
            raise H1BError("CONTEXT_MISMATCH")
        return values[0]

    def operational_merchant(self, tenant_id: int) -> UUID:
        rows = self.session.execute(
            text(
                """
                SELECT public_id
                FROM pa_merchants
                WHERE tenant_id=:tenant AND administration_state='operational'
                """
            ),
            {"tenant": tenant_id},
        ).scalars().all()
        if len(rows) != 1:
            raise H1BError("CONTEXT_MISMATCH")
        return UUID(str(rows[0]))

    def party_contact(self, tenant_id: int, contact_id: int, *, at: datetime) -> BoundContact:
        row = self.session.execute(
            text(
                """
                SELECT c.id,c.contact_type,c.contact_value,c.metadata,p.public_id party_public_id
                FROM party_contacts c
                JOIN parties p ON (p.tenant_id,p.id)=(c.tenant_id,c.party_id)
                WHERE c.tenant_id=:tenant AND c.id=:id
                  AND c.valid_from<=:today
                  AND (c.valid_to IS NULL OR :today<=c.valid_to)
                """
            ),
            {"tenant": tenant_id, "id": contact_id, "today": at.date()},
        ).mappings().first()
        if row is None:
            raise H1BError("CONTEXT_MISMATCH")
        return BoundContact(
            UUID(int=0),
            int(row["id"]),
            UUID(str(row["party_public_id"])),
            str(row["contact_type"]),
            str(row["contact_value"]),
            dict(row["metadata"] or {}),
        )

    def resource(self, tenant_id: int, public_id: UUID) -> Any | None:
        row = self.session.execute(
            text(
                """
                SELECT public_id,tenant_id,organization_unit_id,location_id,lifecycle_status,
                       classification_code,row_version
                FROM so5_resources
                WHERE tenant_id=:tenant AND public_id=:public_id
                """
            ),
            {"tenant": tenant_id, "public_id": str(public_id)},
        ).mappings().first()
        return SimpleNamespace(**dict(row)) if row else None

    def party(self, tenant_id: int, public_id: UUID) -> Any | None:
        row = self.session.execute(
            text("SELECT id,public_id,tenant_id FROM parties WHERE tenant_id=:tenant AND public_id=:p"),
            {"tenant": tenant_id, "p": str(public_id)},
        ).mappings().first()
        return SimpleNamespace(**dict(row)) if row else None

    def identity(self, tenant_id: int, public_id: UUID) -> Any | None:
        row = self.session.execute(
            text(
                """
                SELECT i.id,i.public_id,m.tenant_id,p.public_id party_public_id
                FROM identities i
                JOIN identity_memberships m ON m.identity_id=i.id
                LEFT JOIN parties p ON (p.tenant_id,p.id)=(m.tenant_id,m.party_id)
                WHERE m.tenant_id=:tenant AND i.public_id=:p AND m.status='active'
                """
            ),
            {"tenant": tenant_id, "p": str(public_id)},
        ).mappings().first()
        return SimpleNamespace(**dict(row)) if row else None

    def order_line(self, tenant_id: int, public_id: UUID) -> Any | None:
        row = self.session.execute(
            text(
                """
                SELECT l.public_id,l.tenant_id,o.public_id order_public_id,l.row_version,l.lifecycle_status
                FROM r1_restaurant_order_lines l
                JOIN r1_restaurant_orders o ON (o.tenant_id,o.id)=(l.tenant_id,l.order_id)
                WHERE l.tenant_id=:tenant AND l.public_id=:p
                """
            ),
            {"tenant": tenant_id, "p": str(public_id)},
        ).mappings().first()
        return SimpleNamespace(**dict(row)) if row else None

    def menu_entry_is_current(self, tenant_id: int, catalog_entry_public_id: UUID, *, at: datetime) -> bool:
        value = self.session.execute(
            text(
                """
                SELECT EXISTS(
                  SELECT 1
                  FROM r2_restaurant_menu_section_entries x
                  JOIN r2_restaurant_menu_sections s
                    ON (s.tenant_id,s.id)=(x.tenant_id,x.section_id)
                  JOIN so1_catalog_entries e
                    ON e.tenant_id=x.tenant_id AND e.public_id=x.catalog_entry_public_id
                  JOIN so1_catalogs c
                    ON (c.tenant_id,c.id)=(e.tenant_id,e.catalog_id)
                  WHERE x.tenant_id=:tenant
                    AND x.catalog_entry_public_id=:entry
                    AND s.active
                    AND s.effective_from<=:at
                    AND (s.effective_to IS NULL OR :at<s.effective_to)
                    AND x.effective_from<=:at
                    AND (x.effective_to IS NULL OR :at<x.effective_to)
                    AND e.enabled
                    AND e.effective_from<=:at
                    AND (e.effective_to IS NULL OR :at<e.effective_to)
                    AND c.active
                    AND c.effective_from<=:at
                    AND (c.effective_to IS NULL OR :at<c.effective_to)
                )
                """
            ),
            {"tenant": tenant_id, "entry": str(catalog_entry_public_id), "at": at},
        ).scalar_one()
        return bool(value)

    def delivery_policies(
        self,
        tenant_id: int,
        organization_unit_id: int,
        location_id: int,
    ) -> tuple[DeliveryPolicyRecord, ...]:
        rows = self.session.execute(
            text(
                """
                SELECT public_id,tenant_id,organization_unit_id,location_id,policy_code,
                       policy_version,address_match_rule,fee_catalog_entry_public_id,
                       fee_price_public_id,effective_from,effective_to,active
                FROM restaurant_customer_delivery_policies
                WHERE tenant_id=:tenant
                  AND organization_unit_id=:organization
                  AND location_id=:location
                ORDER BY policy_code,policy_version,public_id
                """
            ),
            {
                "tenant": tenant_id,
                "organization": organization_unit_id,
                "location": location_id,
            },
        ).mappings().all()
        return tuple(
            DeliveryPolicyRecord(
                UUID(str(r["public_id"])),
                int(r["tenant_id"]),
                int(r["organization_unit_id"]),
                int(r["location_id"]),
                str(r["policy_code"]),
                int(r["policy_version"]),
                dict(r["address_match_rule"] or {}),
                UUID(str(r["fee_catalog_entry_public_id"])),
                UUID(str(r["fee_price_public_id"])),
                r["effective_from"],
                r["effective_to"],
                bool(r["active"]),
            )
            for r in rows
        )

    def create_confirmation(
        self,
        *,
        public_id: UUID,
        tenant_id: int,
        organization_unit_id: int,
        location_id: int,
        merchant_public_id: UUID,
        context_binding_public_id: UUID,
        service_mode: str,
        table_resource_public_id: UUID | None,
        contact_binding_public_id: UUID | None,
        delivery_address_binding_public_id: UUID | None,
        authoritative_snapshot: dict[str, Any],
        commercial_fingerprint: str,
        observed_quote_ref: str | None,
        observed_quote_version: str | None,
        expires_at: datetime,
    ) -> dict[str, Any]:
        row = self.session.execute(
            text(
                """
                INSERT INTO restaurant_customer_order_confirmations(
                    public_id,tenant_id,organization_unit_id,location_id,merchant_public_id,
                    context_binding_public_id,service_mode,table_resource_public_id,
                    contact_binding_public_id,delivery_address_binding_public_id,
                    authoritative_snapshot,commercial_fingerprint,observed_quote_ref,
                    observed_quote_version,expires_at
                ) VALUES(
                    :public_id,:tenant,:organization,:location,:merchant,:context,
                    :mode,:table_ref,:contact_ref,:address_ref,CAST(:snapshot AS jsonb),
                    :fingerprint,:quote_ref,:quote_version,:expires
                )
                RETURNING *
                """
            ),
            {
                "public_id": str(public_id),
                "tenant": tenant_id,
                "organization": organization_unit_id,
                "location": location_id,
                "merchant": str(merchant_public_id),
                "context": str(context_binding_public_id),
                "mode": service_mode,
                "table_ref": str(table_resource_public_id) if table_resource_public_id else None,
                "contact_ref": str(contact_binding_public_id) if contact_binding_public_id else None,
                "address_ref": str(delivery_address_binding_public_id) if delivery_address_binding_public_id else None,
                "snapshot": json.dumps(authoritative_snapshot, sort_keys=True, separators=(",", ":")),
                "fingerprint": commercial_fingerprint,
                "quote_ref": observed_quote_ref,
                "quote_version": observed_quote_version,
                "expires": expires_at,
            },
        ).mappings().one()
        return dict(row)

    def confirmation(self, tenant_id: int, public_id: UUID, *, lock: bool = False) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if lock else ""
        row = self.session.execute(
            text(
                """
                SELECT * FROM restaurant_customer_order_confirmations
                WHERE tenant_id=:tenant AND public_id=:public_id
                """ + suffix
            ),
            {"tenant": tenant_id, "public_id": str(public_id)},
        ).mappings().first()
        return dict(row) if row else None

    def claim_confirmation(
        self,
        *,
        tenant_id: int,
        confirmation_public_id: UUID,
        client_submit_ref_hash: str,
    ) -> dict[str, Any]:
        row = self.confirmation(tenant_id, confirmation_public_id, lock=True)
        if row is None:
            raise H1BError("ORDER_CONFIRMATION_EXPIRED_OR_CHANGED")
        existing = row.get("claimed_client_submit_ref_hash")
        if existing and existing != client_submit_ref_hash:
            raise H1BError("IDEMPOTENCY_CONFLICT")
        other = self.session.execute(
            text(
                """
                SELECT public_id FROM restaurant_customer_order_confirmations
                WHERE tenant_id=:tenant
                  AND claimed_client_submit_ref_hash=:hash
                  AND public_id<>:public_id
                LIMIT 1
                """
            ),
            {
                "tenant": tenant_id,
                "hash": client_submit_ref_hash,
                "public_id": str(confirmation_public_id),
            },
        ).scalar()
        if other is not None:
            raise H1BError("IDEMPOTENCY_CONFLICT")
        if not existing:
            self.session.execute(
                text(
                    """
                    UPDATE restaurant_customer_order_confirmations
                    SET claimed_client_submit_ref_hash=:hash,updated_at=now()
                    WHERE tenant_id=:tenant AND public_id=:public_id
                    """
                ),
                {
                    "tenant": tenant_id,
                    "public_id": str(confirmation_public_id),
                    "hash": client_submit_ref_hash,
                },
            )
            row["claimed_client_submit_ref_hash"] = client_submit_ref_hash
        return row

    def bind_confirmation_order(
        self,
        *,
        tenant_id: int,
        confirmation_public_id: UUID,
        order_public_id: UUID,
    ) -> None:
        self.session.execute(
            text(
                """
                UPDATE restaurant_customer_order_confirmations
                SET order_public_id=:order_ref,updated_at=now()
                WHERE tenant_id=:tenant AND public_id=:confirmation
                """
            ),
            {
                "tenant": tenant_id,
                "confirmation": str(confirmation_public_id),
                "order_ref": str(order_public_id),
            },
        )

    def command_order_result(self, tenant_id: int, submit_command_key: str) -> UUID | None:
        row = self.session.execute(
            text(
                """
                SELECT result_public_id
                FROM r1_restaurant_commands
                WHERE tenant_id=:tenant
                  AND command_key=:key
                  AND command_type='submit_order'
                  AND completed_at IS NOT NULL
                  AND result_type='restaurant_order'
                  AND result_public_id IS NOT NULL
                """
            ),
            {"tenant": tenant_id, "key": submit_command_key},
        ).scalar()
        return UUID(str(row)) if row else None

class CatalogReadBindingRepository(Protocol):
    def resolve(
        self,
        merchant_public_id: UUID,
        location_public_id: UUID,
        effective_at: datetime,
    ) -> tuple[CatalogReadBinding, ...]: ...

class AbsentCatalogReadBindingRepository:
    """Fail-closed placeholder until R2-R3 installs real binding persistence."""
    def resolve(
        self,
        merchant_public_id: UUID,
        location_public_id: UUID,
        effective_at: datetime,
    ) -> tuple[CatalogReadBinding, ...]:
        return ()
