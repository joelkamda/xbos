"""Tenant-scoped payable, disbursement, and settlement authority reads."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .payable_contract import PAYABLE_TYPES, PayableLifecycleError


class PayableLifecycleRepository:
    @staticmethod
    def payable_authority(session, *, tenant_id: int, public_id: UUID, lock: bool = False):
        locking = "FOR UPDATE OF o" if lock else ""
        row = session.execute(text(f"""
            SELECT o.id,o.public_id,o.tenant_id,o.organization_unit_id,o.debtor_party_id,
                   o.creditor_party_id,o.obligation_type,o.obligation_state,o.original_amount,
                   o.currency_code,o.due_at,o.occurred_at,o.business_date,o.row_version
            FROM public.financial_obligations o
            WHERE o.tenant_id=:tenant_id AND o.public_id=:public_id
            {locking}
        """), {"tenant_id": tenant_id, "public_id": str(UUID(str(public_id)))}).mappings().one_or_none()
        if row is None:
            raise PayableLifecycleError("payable_not_found", "payable does not exist for tenant")
        if row["obligation_type"] not in PAYABLE_TYPES:
            raise PayableLifecycleError("not_a_payable", "obligation is not an approved payable type")
        return row

    @staticmethod
    def settlement_authority(session, *, tenant_id: int, public_id: UUID, lock: bool = False):
        locking = "FOR UPDATE OF ps" if lock else ""
        row = session.execute(text(f"""
            SELECT ps.id,ps.public_id,ps.tenant_id,ps.organization_unit_id,
                   ps.settlement_direction,ps.settlement_state,ps.gross_amount,
                   ps.net_amount,ps.currency_code,ps.reversed_amount
            FROM public.payment_settlements ps
            WHERE ps.tenant_id=:tenant_id AND ps.public_id=:public_id
            {locking}
        """), {"tenant_id": tenant_id, "public_id": str(UUID(str(public_id)))}).mappings().one_or_none()
        if row is None:
            raise PayableLifecycleError("settlement_not_found", "settlement does not exist for tenant")
        return row

    @staticmethod
    def disbursement_authority(session, *, tenant_id: int, public_id: UUID, lock: bool = False):
        locking = "FOR UPDATE OF vs" if lock else ""
        row = session.execute(text(f"""
            SELECT vs.id,vs.public_id,vs.tenant_id,vs.organization_unit_id,vs.owner_party_id,
                   vs.source_type,vs.source_amount,vs.currency_code,vs.payment_settlement_public_id,
                   vs.metadata->>'payee_party_id' AS payee_party_id
            FROM public.value_sources vs
            WHERE vs.tenant_id=:tenant_id AND vs.public_id=:public_id
            {locking}
        """), {
            "tenant_id": tenant_id, "public_id": str(UUID(str(public_id))),
        }).mappings().one_or_none()
        if row is None or row["source_type"] != "disbursement":
            raise PayableLifecycleError("disbursement_not_found", "governed disbursement does not exist for tenant")
        try:
            UUID(str(row["payee_party_id"]))
        except (TypeError, ValueError) as exc:
            raise PayableLifecycleError("payee_identity_missing", "persisted disbursement payee is invalid") from exc
        return row

    @staticmethod
    def supplier_position(session, *, tenant_id: int, supplier_party_id: UUID, currency_code: str):
        row = session.execute(text("""
          WITH reversals AS (
            SELECT tenant_id,payment_allocation_id,SUM(reversal_amount) reversed
            FROM public.allocation_reversals WHERE tenant_id=:tenant_id
            GROUP BY tenant_id,payment_allocation_id
          ), applications AS (
            SELECT pa.tenant_id,pa.obligation_id,
                   SUM(pa.allocation_amount-COALESCE(r.reversed,0)) active_amount
            FROM public.payment_allocations pa LEFT JOIN reversals r
              ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
            WHERE pa.tenant_id=:tenant_id GROUP BY pa.tenant_id,pa.obligation_id
          )
          SELECT COALESCE(SUM(o.original_amount-COALESCE(a.active_amount,0)),0) outstanding
          FROM public.financial_obligations o
          LEFT JOIN applications a ON a.tenant_id=o.tenant_id AND a.obligation_id=o.id
          WHERE o.tenant_id=:tenant_id AND o.creditor_party_id=:supplier
            AND o.currency_code=:currency
            AND o.obligation_type IN ('trade_payable','supplier_payable','expense_payable')
            AND o.obligation_state NOT IN ('cancelled','written_off')
        """), {
            "tenant_id": tenant_id, "supplier": str(UUID(str(supplier_party_id))), "currency": currency_code,
        }).scalar_one()
        return Decimal(row)
