"""Locked tenant-scoped authorities for M5.4 correction workflows."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .correction_contract import CorrectionDocumentReference, CorrectionLifecycleError


class CorrectionLifecycleRepository:
    @staticmethod
    def source_authority(session, *, tenant_id: int, organization_unit_id: int, source_record_id: int, expected_kind: str, document: CorrectionDocumentReference):
        row = session.execute(text("""SELECT id,organization_unit_id,aggregate_type,retired_at,metadata
            FROM kernel_source_records WHERE tenant_id=:tenant AND id=:source"""), {"tenant": tenant_id, "source": source_record_id}).mappings().one_or_none()
        if row is None: raise CorrectionLifecycleError("source_not_found", "correction source is missing or belongs to another tenant")
        if row["organization_unit_id"] not in (None, organization_unit_id): raise CorrectionLifecycleError("source_scope_mismatch", "correction source belongs to another organization")
        if row["retired_at"] is not None: raise CorrectionLifecycleError("source_retired", "retired correction source cannot create financial truth")
        if row["aggregate_type"] != expected_kind: raise CorrectionLifecycleError("source_kind_mismatch", "source kind is not authoritative for this correction")
        metadata = row["metadata"] or {}
        if metadata.get("document_type") != document.document_type or metadata.get("document_number") != document.document_number or metadata.get("evidence_hash") != document.evidence_hash: raise CorrectionLifecycleError("document_source_mismatch", "source authority does not preserve the supplied correction document")
        return row
    @staticmethod
    def event_authority(session, *, tenant_id: int, public_id: UUID):
        row = session.execute(text("""SELECT id,public_id,organization_unit_id,event_type_code,amount,currency_code,
            source_operational_account_id,target_operational_account_id,occurred_at
            FROM financial_events WHERE tenant_id=:tenant AND public_id=:public FOR UPDATE"""), {"tenant": tenant_id, "public": str(UUID(str(public_id)))}).mappings().one_or_none()
        if row is None: raise CorrectionLifecycleError("original_event_not_found", "original event is missing or belongs to another tenant")
        return row

    @staticmethod
    def refund_authority(session, *, tenant_id: int, original_public_id: UUID, refund_public_id: UUID):
        rows = session.execute(text("""SELECT s.id,s.public_id,s.organization_unit_id,s.settlement_state,s.settlement_direction,
            s.gross_amount,s.reversed_amount,s.currency_code,s.operational_account_id,oa.public_id operational_account_public_id
            FROM payment_settlements s JOIN operational_financial_accounts oa ON oa.id=s.operational_account_id
            WHERE s.tenant_id=:tenant AND s.public_id IN (:original,:refund) FOR UPDATE OF s"""), {"tenant": tenant_id, "original": str(original_public_id), "refund": str(refund_public_id)}).mappings().all()
        selected = {UUID(str(row["public_id"])): row for row in rows}
        original, refund = selected.get(original_public_id), selected.get(refund_public_id)
        if original is None or refund is None: raise CorrectionLifecycleError("settlement_not_found", "original or refund settlement is missing")
        return original, refund

    @staticmethod
    def previous_refunds(session, *, tenant_id: int, original_public_id: UUID):
        return Decimal(session.execute(text("""SELECT coalesce(sum(amount),0) FROM financial_events
            WHERE tenant_id=:tenant AND event_type_code='REFUND_SETTLED'
              AND metadata->>'original_settlement_public_id'=:original"""), {"tenant": tenant_id, "original": str(original_public_id)}).scalar_one())

    @staticmethod
    def obligation_authority(session, *, tenant_id: int, public_id: UUID):
        row = session.execute(text("""SELECT id,public_id,organization_unit_id,obligation_type,obligation_state,
            currency_code,row_version FROM financial_obligations WHERE tenant_id=:tenant AND public_id=:public FOR UPDATE"""), {"tenant": tenant_id, "public": str(UUID(str(public_id)))}).mappings().one_or_none()
        if row is None: raise CorrectionLifecycleError("obligation_not_found", "obligation is missing or belongs to another tenant")
        return row
