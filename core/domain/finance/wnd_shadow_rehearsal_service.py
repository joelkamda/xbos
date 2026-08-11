"""M7.3 production-shaped shadow planning and deterministic comparison."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .wnd_financial_mapping_contract import CanonicalMappingPlan
from .wnd_inventory_document_contract import FinancialDocumentLinkagePlan, InventoryFinancialHandoffPlan
from .wnd_shadow_rehearsal_contract import (
    ControlTotalComparison, FinancialControlTotals, ProductionShapedRehearsal,
    ShadowCase, WndShadowRehearsalError,
)


def _currency_from_commands(plan: CanonicalMappingPlan) -> str:
    currencies = {
        str(command.payload["currency_code"]).upper()
        for command in plan.commands if command.payload.get("currency_code")
    }
    if len(currencies) != 1:
        raise WndShadowRehearsalError("single_currency_case_required", plan.source_identity)
    return currencies.pop()


class WndShadowRehearsalService:
    @classmethod
    def financial_case(cls, sequence: int, plan: CanonicalMappingPlan) -> ShadowCase:
        values: dict[str, Decimal] = {}
        for command in plan.commands:
            payload = command.payload
            amount = Decimal(str(payload.get("amount", payload.get("gross_sales_amount", 0))))
            if command.command_type == "CanonicalFinancialEventCommand":
                values["commercial_revenue"] = values.get("commercial_revenue", Decimal(0)) + amount
            elif command.command_type == "RecognizeCommercialTermsCommand":
                total = sum((Decimal(str(item["amount"])) for item in payload.get("components", ())), Decimal(0))
                values["customer_allowances"] = values.get("customer_allowances", Decimal(0)) + total
            elif command.command_type == "OpenReceivableCommand":
                opened = Decimal(str(payload["original_amount"]))
                values["receivables_opened"] = values.get("receivables_opened", Decimal(0)) + opened
            elif command.command_type == "CreatePaymentSettlementCommand":
                collected = Decimal(str(payload["gross_amount"]))
                values["cash_collections"] = values.get("cash_collections", Decimal(0)) + collected
            elif command.command_type == "ReceiveReceivablePaymentCommand":
                satisfied = Decimal(str(payload["amount"]))
                values["receivables_satisfied"] = values.get("receivables_satisfied", Decimal(0)) + satisfied
            elif command.command_type == "RecognizeRefundCommand":
                values["refunds"] = values.get("refunds", Decimal(0)) + amount
        return ShadowCase(
            sequence=sequence, tenant_id=plan.tenant_id,
            organization_unit_id=plan.organization_unit_id,
            source_identity=plan.source_identity, source_fingerprint=plan.source_fingerprint,
            mapping_package="m71", mapping_plan_fingerprint=plan.plan_fingerprint,
            expected=FinancialControlTotals(_currency_from_commands(plan), values),
        )

    @classmethod
    def inventory_case(cls, sequence: int, plan: InventoryFinancialHandoffPlan,
                       *, withheld_currency_code: str | None = None) -> ShadowCase:
        currency = plan.command.currency_code if plan.command else withheld_currency_code
        if not currency:
            raise WndShadowRehearsalError("withheld_case_currency_required", plan.source_identity)
        values = {"fulfillment_cost": plan.command.amount} if plan.command else {}
        return ShadowCase(
            sequence=sequence, tenant_id=plan.tenant_id,
            organization_unit_id=plan.organization_unit_id,
            source_identity=plan.source_identity, source_fingerprint=plan.source_fingerprint,
            mapping_package="m72.inventory", mapping_plan_fingerprint=plan.plan_fingerprint,
            expected=FinancialControlTotals(currency, values),
            disposition=plan.disposition, disposition_reason=plan.disposition_reason,
        )

    @classmethod
    def document_case(cls, sequence: int, plan: FinancialDocumentLinkagePlan,
                      *, currency_code: str) -> ShadowCase:
        return ShadowCase(
            sequence=sequence, tenant_id=plan.tenant_id,
            organization_unit_id=plan.organization_unit_id,
            source_identity=plan.source_identity, source_fingerprint=plan.source_fingerprint,
            mapping_package="m72.document", mapping_plan_fingerprint=plan.plan_fingerprint,
            expected=FinancialControlTotals(currency_code, {"financial_documents": Decimal(1)}),
        )

    @staticmethod
    def assemble(rehearsal_id: str, source_snapshot_fingerprint: str,
                 cases: Iterable[ShadowCase]) -> ProductionShapedRehearsal:
        selected = tuple(cases)
        normalized = tuple(ShadowCase(
            sequence=index, tenant_id=case.tenant_id,
            organization_unit_id=case.organization_unit_id,
            source_identity=case.source_identity, source_fingerprint=case.source_fingerprint,
            mapping_package=case.mapping_package,
            mapping_plan_fingerprint=case.mapping_plan_fingerprint,
            expected=case.expected, disposition=case.disposition,
            disposition_reason=case.disposition_reason,
        ) for index, case in enumerate(selected, 1))
        return ProductionShapedRehearsal(rehearsal_id, source_snapshot_fingerprint, normalized)

    @staticmethod
    def compare(case: ShadowCase, observed: FinancialControlTotals) -> ControlTotalComparison:
        if case.disposition != "ready":
            raise WndShadowRehearsalError("withheld_case_not_executable", case.source_identity)
        return ControlTotalComparison(case.case_fingerprint, case.expected, observed)
