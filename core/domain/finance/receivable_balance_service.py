"""Derived customer receivable and stored-value position for M5.0."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .receivable_contract import ReceivableLifecycleError
from .receivable_repository import ReceivableLifecycleRepository


@dataclass(frozen=True)
class CustomerFinancialPosition:
    tenant_id: int
    customer_party_id: UUID
    currency_code: str
    receivable_outstanding: Decimal
    customer_value_available: Decimal
    net_customer_due: Decimal


class CustomerReceivableBalanceService:
    repository = ReceivableLifecycleRepository

    @classmethod
    def get(cls, session, *, tenant_id: int, customer_party_id: UUID, currency_code: str):
        if tenant_id <= 0:
            raise ReceivableLifecycleError("invalid_tenant", "tenant_id must be positive")
        customer = UUID(str(customer_party_id))
        currency = str(currency_code).strip().upper()
        if len(currency) != 3:
            raise ReceivableLifecycleError("invalid_currency", "currency_code must use three uppercase letters")
        outstanding, available = cls.repository.customer_position(
            session, tenant_id=tenant_id, customer_party_id=customer, currency_code=currency
        )
        return CustomerFinancialPosition(
            tenant_id, customer, currency, outstanding, available, outstanding - available
        )
