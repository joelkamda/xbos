"""Derived supplier payable position from immutable obligation and allocation facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .payable_contract import PayableLifecycleError
from .payable_repository import PayableLifecycleRepository


@dataclass(frozen=True)
class SupplierPayablePosition:
    tenant_id: int
    supplier_party_id: UUID
    currency_code: str
    outstanding_amount: Decimal


class SupplierPayableBalanceService:
    repository = PayableLifecycleRepository

    @classmethod
    def get(cls, session, *, tenant_id: int, supplier_party_id: UUID, currency_code: str):
        if tenant_id <= 0:
            raise PayableLifecycleError("invalid_tenant", "tenant_id must be positive")
        supplier = UUID(str(supplier_party_id))
        currency = str(currency_code).strip().upper()
        if len(currency) != 3:
            raise PayableLifecycleError("invalid_currency", "currency_code must use three uppercase letters")
        outstanding = cls.repository.supplier_position(
            session, tenant_id=tenant_id, supplier_party_id=supplier, currency_code=currency
        )
        return SupplierPayablePosition(tenant_id, supplier, currency, outstanding)
