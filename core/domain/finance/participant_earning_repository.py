"""Tenant-scoped source authority and participant earning balances."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .participant_earning_contract import ParticipantEarningError


class ParticipantEarningRepository:
    @staticmethod
    def source_authority(session, *, tenant_id: int, organization_unit_id: int, source_record_id: int, allowed_kinds: tuple[str, ...]):
        row = session.execute(text("""SELECT id,organization_unit_id,aggregate_type,retired_at
            FROM kernel_source_records WHERE tenant_id=:tenant AND id=:source"""), {"tenant": tenant_id, "source": source_record_id}).mappings().one_or_none()
        if row is None:
            raise ParticipantEarningError("source_not_found", "earning source is missing or belongs to another tenant")
        if row["organization_unit_id"] not in (None, organization_unit_id):
            raise ParticipantEarningError("source_scope_mismatch", "earning source belongs to another organization")
        if row["retired_at"] is not None:
            raise ParticipantEarningError("source_retired", "retired earning source cannot create financial truth")
        if row["aggregate_type"] not in allowed_kinds:
            raise ParticipantEarningError("source_kind_mismatch", "source kind is not authoritative for this earning")
        return row

    @staticmethod
    def beneficiary_balance(session, *, tenant_id: int, beneficiary_party_id: UUID, currency_code: str):
        row = session.execute(text("""WITH reversals AS (
              SELECT tenant_id,payment_allocation_id,sum(reversal_amount) reversed
              FROM allocation_reversals WHERE tenant_id=:tenant GROUP BY tenant_id,payment_allocation_id
            ), applied AS (
              SELECT pa.tenant_id,pa.obligation_id,sum(pa.allocation_amount-coalesce(r.reversed,0)) amount
              FROM payment_allocations pa LEFT JOIN reversals r ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
              WHERE pa.tenant_id=:tenant GROUP BY pa.tenant_id,pa.obligation_id
            ) SELECT coalesce(sum(o.original_amount-coalesce(a.amount,0)),0) outstanding
            FROM financial_obligations o LEFT JOIN applied a ON a.tenant_id=o.tenant_id AND a.obligation_id=o.id
            WHERE o.tenant_id=:tenant AND o.creditor_party_id=:beneficiary AND o.currency_code=:currency
              AND o.obligation_type='expense_payable' AND o.metadata->>'earning_type' IN ('tip','commission')
              AND o.obligation_state NOT IN ('cancelled','written_off')"""), {
            "tenant": tenant_id, "beneficiary": str(UUID(str(beneficiary_party_id))), "currency": currency_code,
        }).mappings().one()
        return Decimal(row["outstanding"])
