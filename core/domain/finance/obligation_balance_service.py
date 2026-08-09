"""Tenant-scoped derived obligation balances; no mutable balance authority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .obligation_contract import ObligationValidationError


@dataclass(frozen=True)
class ObligationBalance:
    obligation_id: int
    obligation_public_id: UUID
    tenant_id: int
    original_amount: Decimal
    allocated_amount: Decimal
    reversed_amount: Decimal
    active_satisfaction: Decimal
    outstanding_amount: Decimal
    currency_code: str
    stored_state: str
    projected_state: str
    row_version: int


_BALANCE = text(
    """
    WITH reversal_totals AS (
        SELECT tenant_id, payment_allocation_id, SUM(reversal_amount) AS reversed_amount
        FROM public.allocation_reversals
        WHERE tenant_id = :tenant_id
        GROUP BY tenant_id, payment_allocation_id
    ), allocation_totals AS (
        SELECT pa.tenant_id, pa.obligation_id,
               SUM(pa.allocation_amount) AS allocated_amount,
               SUM(COALESCE(rt.reversed_amount, 0)) AS reversed_amount
        FROM public.payment_allocations pa
        LEFT JOIN reversal_totals rt
          ON rt.tenant_id = pa.tenant_id
         AND rt.payment_allocation_id = pa.id
        WHERE pa.tenant_id = :tenant_id
        GROUP BY pa.tenant_id, pa.obligation_id
    )
    SELECT o.id, o.public_id, o.tenant_id, o.original_amount, o.currency_code,
           o.obligation_state, o.row_version,
           COALESCE(a.allocated_amount, 0) AS allocated_amount,
           COALESCE(a.reversed_amount, 0) AS reversed_amount
    FROM public.financial_obligations o
    LEFT JOIN allocation_totals a
      ON a.tenant_id = o.tenant_id AND a.obligation_id = o.id
    WHERE o.tenant_id = :tenant_id AND o.public_id = :public_id
    """
)


class ObligationBalanceService:
    @staticmethod
    def get(session, *, tenant_id: int, obligation_public_id: UUID) -> ObligationBalance:
        if tenant_id <= 0:
            raise ObligationValidationError("invalid_tenant", "tenant_id must be positive")
        row = session.execute(
            _BALANCE, {"tenant_id": tenant_id, "public_id": str(UUID(str(obligation_public_id)))}
        ).mappings().one_or_none()
        if row is None:
            raise ObligationValidationError("obligation_not_found", "obligation does not exist for tenant")
        original = Decimal(row["original_amount"])
        allocated = Decimal(row["allocated_amount"])
        reversed_amount = Decimal(row["reversed_amount"])
        active = allocated - reversed_amount
        outstanding = original - active
        if active < 0 or outstanding < 0:
            raise ObligationValidationError(
                "obligation_capacity_corrupt", "allocation facts exceed governed obligation capacity"
            )
        if outstanding == 0:
            projected = "satisfied"
        elif outstanding < original:
            projected = "partially_satisfied"
        else:
            projected = "open"
        return ObligationBalance(
            obligation_id=int(row["id"]),
            obligation_public_id=UUID(str(row["public_id"])),
            tenant_id=int(row["tenant_id"]),
            original_amount=original,
            allocated_amount=allocated,
            reversed_amount=reversed_amount,
            active_satisfaction=active,
            outstanding_amount=outstanding,
            currency_code=row["currency_code"],
            stored_state=row["obligation_state"],
            projected_state=projected,
            row_version=int(row["row_version"]),
        )
