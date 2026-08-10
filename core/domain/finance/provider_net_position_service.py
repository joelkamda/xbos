"""Deterministic provider net-position projection without rewriting settlement."""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID
from .provider_financial_contract import ProviderFinancialValidationError
from .provider_financial_repository import ProviderFinancialRepository

@dataclass(frozen=True)
class ProviderNetPosition:
    payment_settlement_public_id:UUID;gross_amount:Decimal;fee_amount:Decimal;reserve_held:Decimal;chargeback_loss:Decimal;expected_net:Decimal;currency_code:str

class ProviderNetPositionService:
    repository=ProviderFinancialRepository
    @classmethod
    def resolve(cls,session,*,tenant_id,payment_settlement_public_id):
        row=cls.repository.projection(session,tenant_id=tenant_id,settlement_public_id=payment_settlement_public_id)
        if row is None:raise ProviderFinancialValidationError("settlement_not_found","settlement does not exist in tenant scope")
        return ProviderNetPosition(UUID(str(row["public_id"])),Decimal(row["gross_amount"]),Decimal(row["fee_amount"]),Decimal(row["reserve_held"]),Decimal(row["chargeback_loss"]),Decimal(row["expected_net"]),row["currency_code"])
