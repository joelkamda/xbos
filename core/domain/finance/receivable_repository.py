"""Tenant-scoped authority reads for M5.0 receivable orchestration."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .receivable_contract import CUSTOMER_VALUE_TYPES, RECEIVABLE_TYPES, ReceivableLifecycleError


class ReceivableLifecycleRepository:
    @staticmethod
    def is_receivable(session, *, tenant_id: int, public_id: UUID) -> bool:
        return bool(session.execute(
            text("""
                SELECT 1 FROM public.financial_obligations
                WHERE tenant_id=:tenant_id AND public_id=:public_id
                  AND obligation_type IN ('trade_receivable','customer_receivable')
            """),
            {"tenant_id": tenant_id, "public_id": str(UUID(str(public_id)))},
        ).scalar_one_or_none())

    @staticmethod
    def receivable_authority(session, *, tenant_id: int, public_id: UUID, lock: bool = False):
        locking = "FOR UPDATE OF o" if lock else ""
        row = session.execute(
            text(
                f"""
                SELECT o.id, o.public_id, o.tenant_id, o.organization_unit_id,
                       o.debtor_party_id, o.creditor_party_id, o.obligation_type,
                       o.obligation_state, o.original_amount, o.currency_code,
                       o.due_at, o.occurred_at, o.business_date, o.row_version
                FROM public.financial_obligations o
                WHERE o.tenant_id=:tenant_id AND o.public_id=:public_id
                {locking}
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(UUID(str(public_id)))},
        ).mappings().one_or_none()
        if row is None:
            raise ReceivableLifecycleError("receivable_not_found", "receivable does not exist for tenant")
        if row["obligation_type"] not in RECEIVABLE_TYPES:
            raise ReceivableLifecycleError("not_a_receivable", "obligation is not an approved receivable type")
        return row

    @staticmethod
    def customer_value_authority(
        session, *, tenant_id: int, public_id: UUID, lock: bool = False, allow_payment_residual: bool = False
    ):
        locking = "FOR UPDATE OF vs" if lock else ""
        row = session.execute(
            text(
                f"""
                SELECT vs.id, vs.public_id, vs.tenant_id, vs.organization_unit_id,
                       vs.owner_party_id, vs.source_type, vs.source_amount, vs.currency_code
                FROM public.value_sources vs
                WHERE vs.tenant_id=:tenant_id AND vs.public_id=:public_id
                {locking}
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(UUID(str(public_id)))},
        ).mappings().one_or_none()
        if row is None:
            raise ReceivableLifecycleError("customer_value_not_found", "customer value does not exist for tenant")
        allowed = CUSTOMER_VALUE_TYPES | ({"payment"} if allow_payment_residual else set())
        if row["source_type"] not in allowed:
            raise ReceivableLifecycleError(
                "not_customer_value", "value source is not governed customer-held value"
            )
        return row

    @staticmethod
    def customer_position(session, *, tenant_id: int, customer_party_id: UUID, currency_code: str):
        row = session.execute(
            text(
                """
                WITH reversals AS (
                  SELECT tenant_id,payment_allocation_id,SUM(reversal_amount) reversed
                  FROM public.allocation_reversals WHERE tenant_id=:tenant_id
                  GROUP BY tenant_id,payment_allocation_id
                ), obligation_applications AS (
                  SELECT pa.tenant_id,pa.obligation_id,
                         SUM(pa.allocation_amount-COALESCE(r.reversed,0)) active_amount
                  FROM public.payment_allocations pa LEFT JOIN reversals r
                    ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
                  WHERE pa.tenant_id=:tenant_id GROUP BY pa.tenant_id,pa.obligation_id
                ), source_applications AS (
                  SELECT pa.tenant_id,pa.value_source_id,
                         SUM(pa.allocation_amount-COALESCE(r.reversed,0)) active_amount
                  FROM public.payment_allocations pa LEFT JOIN reversals r
                    ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
                  WHERE pa.tenant_id=:tenant_id GROUP BY pa.tenant_id,pa.value_source_id
                ), receivables AS (
                  SELECT COALESCE(SUM(o.original_amount-COALESCE(a.active_amount,0)),0) outstanding
                  FROM public.financial_obligations o
                  LEFT JOIN obligation_applications a ON a.tenant_id=o.tenant_id AND a.obligation_id=o.id
                  WHERE o.tenant_id=:tenant_id AND o.debtor_party_id=:customer
                    AND o.currency_code=:currency AND o.obligation_type IN ('trade_receivable','customer_receivable')
                    AND o.obligation_state NOT IN ('cancelled','written_off')
                ), customer_value AS (
                  SELECT COALESCE(SUM(vs.source_amount-COALESCE(a.active_amount,0)),0) available
                  FROM public.value_sources vs
                  LEFT JOIN source_applications a ON a.tenant_id=vs.tenant_id AND a.value_source_id=vs.id
                  WHERE vs.tenant_id=:tenant_id AND vs.owner_party_id=:customer
                    AND vs.currency_code=:currency
                    AND vs.source_type IN ('payment','customer_credit','customer_deposit','customer_advance')
                )
                SELECT receivables.outstanding,customer_value.available
                FROM receivables CROSS JOIN customer_value
                """
            ),
            {"tenant_id": tenant_id, "customer": str(UUID(str(customer_party_id))), "currency": currency_code},
        ).mappings().one()
        return Decimal(row["outstanding"]), Decimal(row["available"])
