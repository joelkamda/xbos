"""SQL authority used only by the XafPay orchestration boundary."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text


class XafPayRepository:
    @staticmethod
    def attempt_authority(session, *, tenant_id: int, public_id: UUID, lock: bool = False):
        # Lock only the canonical attempt row. PostgreSQL rejects an unqualified
        # FOR UPDATE when this authority query contains nullable LEFT JOINs.
        locking = "FOR UPDATE OF a" if lock else ""
        return session.execute(text(f"""
            SELECT a.id, a.public_id, a.tenant_id, a.organization_unit_id,
                   a.payment_intent_id, i.public_id AS payment_intent_public_id,
                   a.payment_tender_id, t.public_id AS payment_tender_public_id,
                   a.provider_account_id, p.public_id AS provider_account_public_id,
                   p.provider_code, p.active AS provider_account_active,
                   a.attempt_state, a.attempted_amount, a.currency_code,
                   a.payment_method_code, a.payment_rail_code, a.orchestrator_code,
                   a.underlying_provider_code, a.external_attempt_reference,
                   a.occurred_at, a.row_version
            FROM public.canonical_payment_attempts a
            JOIN public.canonical_payment_intents i ON i.id=a.payment_intent_id
            LEFT JOIN public.canonical_payment_tenders t ON t.id=a.payment_tender_id
            LEFT JOIN public.payment_provider_accounts p ON p.id=a.provider_account_id
            WHERE a.tenant_id=:tenant_id AND a.public_id=:public_id
            {locking}
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()

    @staticmethod
    def provider_account(session, *, tenant_id: int, public_id: UUID):
        return session.execute(text("""
            SELECT id, public_id, tenant_id, organization_unit_id, provider_code, environment, active
            FROM public.payment_provider_accounts
            WHERE tenant_id=:tenant_id AND public_id=:public_id FOR SHARE
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()

    @staticmethod
    def callback_by_reference(session, *, tenant_id: int, provider_account_id: int, reference: str):
        return session.execute(text("""
            SELECT id, public_id, payload_hash, processing_state, payment_attempt_id
            FROM public.provider_callback_events
            WHERE tenant_id=:tenant_id AND provider_account_id=:provider_account_id
              AND provider_event_reference=:reference
        """), {"tenant_id": tenant_id, "provider_account_id": provider_account_id, "reference": reference}).mappings().one_or_none()

    @staticmethod
    def insert_callback(
        session,
        *,
        public_id: UUID,
        tenant_id: int,
        organization_unit_id: int,
        provider_account_id: int,
        payment_attempt_id: int | None,
        provider_event_reference: str,
        event_type_code: str,
        payload_hash: str,
        signature_status: str,
        processing_state: str,
        evidence_payload: Mapping[str, Any],
        received_at,
        occurred_at,
        business_date,
        calendar_policy_version: int,
        correlation_id: UUID,
        source_record_id: str,
        metadata: Mapping[str, Any],
    ):
        return session.execute(text("""
            INSERT INTO public.provider_callback_events (
              public_id, tenant_id, organization_unit_id, provider_account_id,
              payment_attempt_id, provider_event_reference, event_type_code,
              payload_hash, signature_status, processing_state, evidence_payload,
              received_at, occurred_at, business_date, calendar_policy_version,
              correlation_id, source_component, source_record_id, metadata
            ) VALUES (
              :public_id, :tenant_id, :organization_unit_id, :provider_account_id,
              :payment_attempt_id, :provider_event_reference, :event_type_code,
              :payload_hash, :signature_status, :processing_state, CAST(:evidence AS JSONB),
              :received_at, :occurred_at, :business_date, :calendar_policy_version,
              :correlation_id, 'xbos.xafpay.callback', :source_record_id, CAST(:metadata AS JSONB)
            ) RETURNING id, public_id, payload_hash, processing_state, payment_attempt_id
        """), {
            "public_id": str(public_id), "tenant_id": tenant_id,
            "organization_unit_id": organization_unit_id,
            "provider_account_id": provider_account_id, "payment_attempt_id": payment_attempt_id,
            "provider_event_reference": provider_event_reference, "event_type_code": event_type_code,
            "payload_hash": payload_hash, "signature_status": signature_status,
            "processing_state": processing_state, "evidence": json.dumps(evidence_payload, sort_keys=True),
            "received_at": received_at, "occurred_at": occurred_at, "business_date": business_date,
            "calendar_policy_version": calendar_policy_version, "correlation_id": str(correlation_id),
            "source_record_id": source_record_id, "metadata": json.dumps(metadata, sort_keys=True),
        }).mappings().one()

    @staticmethod
    def settlement_for_callback(session, *, tenant_id: int, callback_id: int):
        return session.execute(text("""
            SELECT public_id, settlement_state FROM public.payment_settlements
            WHERE tenant_id=:tenant_id AND provider_callback_event_id=:callback_id
        """), {"tenant_id": tenant_id, "callback_id": callback_id}).mappings().one_or_none()
