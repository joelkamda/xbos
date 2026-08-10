"""Deterministic commercial-term totals without persistence side effects."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .commercial_terms_contract import RecognizeCommercialTermsCommand


@dataclass(frozen=True)
class CommercialTermsSummary:
    gross_sales: Decimal
    discounts: Decimal
    complimentary: Decimal
    customer_service_fees: Decimal
    output_tax: Decimal
    customer_collectible: Decimal
    currency_code: str


class CommercialTermsService:
    @staticmethod
    def summarize(command: RecognizeCommercialTermsCommand) -> CommercialTermsSummary:
        total = lambda kind: sum((item.amount for item in command.components if item.component_type == kind), Decimal("0"))
        return CommercialTermsSummary(command.gross_sales_amount, total("discount"), total("complimentary"), total("customer_service_fee"), total("output_tax"), command.customer_collectible_amount, command.currency_code)
