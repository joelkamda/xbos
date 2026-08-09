"""Derived M3.3 value-source balances; immutable facts remain authoritative."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .value_application_contract import ValueApplicationError


@dataclass(frozen=True)
class ValueSourceBalance:
    value_source_id: int
    value_source_public_id: UUID
    tenant_id: int
    source_type: str
    source_amount: Decimal
    allocated_amount: Decimal
    reversed_amount: Decimal
    active_applied_amount: Decimal
    available_amount: Decimal
    currency_code: str
    disposition: str


class ValueSourceBalanceService:
    @staticmethod
    def get(session, *, tenant_id: int, value_source_public_id: UUID) -> ValueSourceBalance:
        if tenant_id <= 0:
            raise ValueApplicationError("invalid_tenant", "tenant_id must be positive")
        row = session.execute(text("""
          WITH reversals AS (
            SELECT tenant_id,payment_allocation_id,SUM(reversal_amount) reversed_amount
            FROM public.allocation_reversals WHERE tenant_id=:tenant
            GROUP BY tenant_id,payment_allocation_id
          ), applications AS (
            SELECT pa.tenant_id,pa.value_source_id,SUM(pa.allocation_amount) allocated_amount,
                   SUM(COALESCE(r.reversed_amount,0)) reversed_amount
            FROM public.payment_allocations pa LEFT JOIN reversals r
              ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
            WHERE pa.tenant_id=:tenant GROUP BY pa.tenant_id,pa.value_source_id
          )
          SELECT vs.id,vs.public_id,vs.tenant_id,vs.source_type,vs.source_amount,vs.currency_code,
                 COALESCE(a.allocated_amount,0) allocated_amount,COALESCE(a.reversed_amount,0) reversed_amount
          FROM public.value_sources vs LEFT JOIN applications a
            ON a.tenant_id=vs.tenant_id AND a.value_source_id=vs.id
          WHERE vs.tenant_id=:tenant AND vs.public_id=:public_id
        """), {"tenant": tenant_id, "public_id": str(UUID(str(value_source_public_id)))}).mappings().one_or_none()
        if row is None:
            raise ValueApplicationError("value_source_not_found", "value source does not exist for tenant")
        source=Decimal(row.source_amount); allocated=Decimal(row.allocated_amount); reversed_amount=Decimal(row.reversed_amount)
        active=allocated-reversed_amount; available=source-active
        if active < 0 or available < 0:
            raise ValueApplicationError("value_source_capacity_corrupt", "value-source facts exceed governed capacity")
        disposition = "unapplied" if active == 0 else ("fully_applied" if available == 0 else "partially_applied")
        return ValueSourceBalance(int(row.id),UUID(str(row.public_id)),row.tenant_id,row.source_type,source,
                                  allocated,reversed_amount,active,available,row.currency_code,disposition)
