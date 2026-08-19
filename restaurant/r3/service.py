from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from core.domain.finance.commercial_terms_contract import CONTRACT_CODE as COMMERCIAL_TERMS_CONTRACT
from core.domain.finance.correction_contract import CONTRACT_CODE as CORRECTION_CONTRACT
from core.domain.finance.event_contract import ENGINE_CONTRACT as EVENT_CONTRACT
from core.domain.finance.obligation_contract import CONTRACT_CODE as OBLIGATION_CONTRACT
from core.domain.finance.participant_earning_contract import CONTRACT_CODE as EARNING_CONTRACT
from restaurant.r1.contracts import ObligationHandoff
from restaurant.r2.contracts import ModifierSelectionSet

from .contracts import (
    ChargeLine,
    ChargeSourceKind,
    CommercialTerm,
    CommercialTermKind,
    CorrectionKind,
    CorrectionPlan,
    CorrectionRequest,
    EarningInstruction,
    EarningKind,
    FinanceCommandDescriptor,
    R3Error,
    RestaurantFinanceContext,
    RestaurantFinancePlan,
    RestaurantReportPlan,
    RestaurantReportRequest,
    fingerprint,
)

_NAMESPACE = uuid5(NAMESPACE_URL, "xbos:restaurant:r3:financial-semantics:v1")


def _id(context: RestaurantFinanceContext | CorrectionRequest, suffix: str) -> UUID:
    return uuid5(_NAMESPACE, f"{context.tenant_id}:{context.source_public_id}:{suffix}")


def _descriptor(context: RestaurantFinanceContext | CorrectionRequest, sequence: int, contract: str, command_type: str, payload: dict, effects: tuple[str, ...], suffix: str) -> FinanceCommandDescriptor:
    key = f"{context.tenant_id}:{context.source_public_id}:{suffix}"
    return FinanceCommandDescriptor(sequence, contract, command_type, _id(context, suffix), "restaurant.r3", key, payload, effects)


class RestaurantFinancialSemantics:
    """Side-effect-free Restaurant-to-Neutral-Finance composition.

    R3 emits deterministic command plans only. It never invokes a Finance engine,
    repository, payment writer, posting writer, inventory writer, or report ledger.
    """

    @staticmethod
    def compile_order_charge(
        context: RestaurantFinanceContext,
        handoff: ObligationHandoff,
        *,
        modifier_sets: Mapping[UUID, ModifierSelectionSet] | None = None,
        terms: Sequence[CommercialTerm] = (),
        earnings: Sequence[EarningInstruction] = (),
    ) -> RestaurantFinancePlan:
        if handoff.tenant_id != context.tenant_id or handoff.source_public_id != context.source_public_id:
            raise R3Error("R3_R1_SCOPE_MISMATCH", str(context.source_public_id))
        if handoff.creates_financial_truth or handoff.finance_authority != "Neutral Finance":
            raise R3Error("R3_R1_HANDOFF_AUTHORITY_INVALID", str(context.source_public_id))
        if handoff.currency != context.currency_code:
            raise R3Error("R3_R1_CURRENCY_MISMATCH", handoff.currency)
        modifier_sets = modifier_sets or {}
        known_lines = {x.order_line_public_id: x for x in handoff.lines}
        if set(modifier_sets) - set(known_lines):
            raise R3Error("R3_MODIFIER_LINE_NOT_IN_SOURCE", str(context.source_public_id))

        lines: list[ChargeLine] = []
        for source in handoff.lines:
            if source.currency != context.currency_code:
                raise R3Error("R3_LINE_CURRENCY_MISMATCH", str(source.order_line_public_id))
            lines.append(ChargeLine(
                source.order_line_public_id,
                ChargeSourceKind.BASE_LINE,
                source.target_public_id,
                f"restaurant_{source.target_type.value}",
                source.quantity,
                source.unit_price_snapshot,
                source.commercial_amount,
                source.currency,
                {"target_type": source.target_type.value},
            ))
            selected = modifier_sets.get(source.order_line_public_id)
            if selected is None:
                continue
            if selected.tenant_id != context.tenant_id or selected.order_line_public_id != source.order_line_public_id:
                raise R3Error("R3_MODIFIER_SCOPE_MISMATCH", str(source.order_line_public_id))
            for choice in selected.selections:
                if choice.currency not in (None, context.currency_code):
                    raise R3Error("R3_MODIFIER_CURRENCY_MISMATCH", str(choice.option_public_id))
                amount = source.quantity * choice.quantity * choice.price_amount_snapshot
                if amount < 0:
                    raise R3Error("R3_MODIFIER_NEGATIVE_PRICE_FORBIDDEN", str(choice.option_public_id))
                if amount == 0:
                    continue
                lines.append(ChargeLine(
                    source.order_line_public_id,
                    ChargeSourceKind.MODIFIER,
                    choice.option_public_id,
                    "restaurant_modifier",
                    source.quantity * choice.quantity,
                    choice.price_amount_snapshot,
                    amount,
                    context.currency_code,
                    {"modifier_group_public_id": str(choice.group_public_id), "selection_version": selected.selection_version},
                ))

        if not lines:
            raise R3Error("R3_EMPTY_CHARGE", str(context.source_public_id))
        terms = tuple(terms)
        earnings = tuple(earnings)
        if len({x.component_public_id for x in terms}) != len(terms):
            raise R3Error("R3_DUPLICATE_TERM", str(context.source_public_id))
        if len({x.public_id for x in earnings}) != len(earnings):
            raise R3Error("R3_DUPLICATE_EARNING", str(context.source_public_id))

        gross = sum((x.line_amount for x in lines), Decimal("0"))
        reductions = sum((x.amount for x in terms if x.kind in {CommercialTermKind.DISCOUNT, CommercialTermKind.COMPLIMENTARY}), Decimal("0"))
        additions = sum((x.amount for x in terms if x.kind in {CommercialTermKind.CUSTOMER_SERVICE_FEE, CommercialTermKind.OUTPUT_TAX}), Decimal("0"))
        if reductions > gross:
            raise R3Error("R3_ALLOWANCE_CAPACITY_EXCEEDED", str(context.source_public_id))
        collectible = gross - reductions + additions
        tip_total = sum((x.amount for x in earnings if x.kind is EarningKind.TIP), Decimal("0"))
        customer_due = collectible + tip_total

        source_payload = {
            "context": asdict(context),
            "handoff": asdict(handoff),
            "modifier_sets": {str(k): asdict(v) for k, v in sorted(modifier_sets.items(), key=lambda pair: str(pair[0]))},
            "terms": [asdict(x) for x in terms],
            "earnings": [asdict(x) for x in earnings],
        }
        source_fp = fingerprint(source_payload)
        commands: list[FinanceCommandDescriptor] = []

        commands.append(_descriptor(context, len(commands)+1, EVENT_CONTRACT, "CanonicalFinancialEventCommand", {
            "event_type_code": "COMMERCIAL_REVENUE_RECOGNIZED",
            "event_version": 1,
            "amount": gross,
            "currency_code": context.currency_code,
            "economic_role": "recognition",
            "occurred_at": context.occurred_at,
            "business_date": context.business_date,
            "calendar_policy_version": context.calendar_policy_version,
            "correlation_id": context.correlation_id,
            "classification_snapshot": {"revenue_nature": {"code": "restaurant_sale"}},
            "posting_profile_code": "commercial_recognition",
            "source_reference": f"restaurant:{context.source_type}:{context.source_public_id}",
            "line_evidence": [asdict(x) for x in lines],
        }, ("revenue_recognition", "receivable_control_increase"), "gross-revenue"))

        if terms:
            components = []
            profiles = {
                CommercialTermKind.DISCOUNT: "discount_contra_revenue",
                CommercialTermKind.CUSTOMER_SERVICE_FEE: "commercial_recognition",
                CommercialTermKind.OUTPUT_TAX: "output_tax_recognition",
            }
            for term in terms:
                profile = profiles.get(term.kind)
                if term.kind is CommercialTermKind.COMPLIMENTARY:
                    policy = str(term.classification_snapshot["complimentary_policy"]["code"]).lower()
                    profile = {
                        "contra_revenue": "complimentary_contra_revenue",
                        "promotion": "complimentary_promotion",
                        "service_recovery": "complimentary_service_recovery",
                    }[policy]
                components.append({
                    "public_id": term.component_public_id,
                    "component_type": term.kind.value,
                    "amount": term.amount,
                    "classification_snapshot": term.classification_snapshot,
                    "posting_profile_code": profile,
                    "source_reference": term.source_reference,
                    "metadata": term.metadata,
                })
            commands.append(_descriptor(context, len(commands)+1, COMMERCIAL_TERMS_CONTRACT, "RecognizeCommercialTermsCommand", {
                "gross_sales_amount": gross,
                "customer_collectible_amount": collectible,
                "currency_code": context.currency_code,
                "occurred_at": context.occurred_at,
                "business_date": context.business_date,
                "calendar_policy_version": context.calendar_policy_version,
                "correlation_id": context.correlation_id,
                "components": components,
            }, tuple(f"{x.kind.value}_recognition" for x in terms), "commercial-terms"))

        for earning in earnings:
            if earning.kind is EarningKind.TIP:
                payload = {
                    "amount": earning.amount,
                    "currency_code": context.currency_code,
                    "tip_policy": earning.policy_code,
                    "beneficiary_party_public_id": earning.beneficiary_party_public_id,
                    "occurred_at": context.occurred_at,
                    "business_date": context.business_date,
                    "calendar_policy_version": context.calendar_policy_version,
                    "correlation_id": context.correlation_id,
                    "source_reference": earning.source_reference,
                    "metadata": earning.metadata,
                }
                effects = ("tip_recognition", "participant_payable" if earning.policy_code == "staff_beneficiary" else "tenant_tip_income", "no_payment_settlement")
                ctype = "RecognizeTipCommand"
            else:
                payload = {
                    "amount": earning.amount,
                    "currency_code": context.currency_code,
                    "beneficiary_party_public_id": earning.beneficiary_party_public_id,
                    "basis": {"basis_type": earning.basis_type, "basis_amount": earning.basis_amount, "rate_percent": earning.rate_percent},
                    "occurred_at": context.occurred_at,
                    "business_date": context.business_date,
                    "calendar_policy_version": context.calendar_policy_version,
                    "correlation_id": context.correlation_id,
                    "source_reference": earning.source_reference,
                    "metadata": earning.metadata,
                }
                effects = ("commission_expense_recognition", "participant_payable", "no_payment_settlement")
                ctype = "RecognizeCommissionCommand"
            commands.append(_descriptor(context, len(commands)+1, EARNING_CONTRACT, ctype, payload, effects, f"earning:{earning.public_id}"))

        if customer_due > 0:
            if context.debtor_party_public_id is None:
                raise R3Error("R3_DEBTOR_PARTY_REQUIRED", "Finance obligation handoff requires a resolved customer/anonymous-customer Party identity")
            commands.append(_descriptor(context, len(commands)+1, OBLIGATION_CONTRACT, "CreateObligationCommand", {
                "debtor_party_id": context.debtor_party_public_id,
                "creditor_party_id": context.merchant_party_public_id,
                "obligation_type": "restaurant_customer_charge",
                "original_amount": customer_due,
                "currency_code": context.currency_code,
                "occurred_at": context.occurred_at,
                "due_at": context.occurred_at,
                "business_date": context.business_date,
                "calendar_policy_version": context.calendar_policy_version,
                "correlation_id": context.correlation_id,
                "source_component": "restaurant.r3",
                "source_record_id": str(context.source_public_id),
                "commercial_transaction_public_id": context.source_public_id,
                "bill_summary": {
                    "gross_sales_amount": gross,
                    "customer_collectible_before_tip": collectible,
                    "tip_amount": tip_total,
                    "customer_due_amount": customer_due,
                },
            }, ("financial_obligation_requested", "finance_owns_obligation_truth"), "obligation"))

        return RestaurantFinancePlan(
            context.tenant_id,
            context.organization_unit_id,
            context.source_type,
            context.source_public_id,
            source_fp,
            tuple(lines),
            terms,
            earnings,
            gross,
            collectible,
            customer_due,
            tuple(commands),
        )

    @staticmethod
    def correction_plan(request: CorrectionRequest) -> CorrectionPlan:
        if request.kind is CorrectionKind.CANCEL:
            if request.financial_event_exists or request.finalized_payment_exists:
                raise R3Error("R3_CANCELLATION_TOO_LATE", "posted or settled truth requires correction/refund semantics")
            return CorrectionPlan(request.kind, "restaurant_cancel_without_finance_command", ())
        if request.kind is CorrectionKind.VOID:
            if request.financial_event_exists or request.finalized_payment_exists or request.irreversible_external_effect_exists:
                raise R3Error("R3_VOID_TOO_LATE", "final financial/external truth cannot be voided")
            return CorrectionPlan(request.kind, "restaurant_void_without_finance_command", ())
        if request.kind is CorrectionKind.REVERSE:
            if not request.financial_event_exists or request.original_event_public_id is None:
                raise R3Error("R3_REVERSAL_ORIGINAL_REQUIRED", str(request.source_public_id))
            command = _descriptor(request, 1, CORRECTION_CONTRACT, "ReverseFinancialFactCommand", {
                "amount": request.amount,
                "currency_code": request.currency_code,
                "original_event_public_id": request.original_event_public_id,
                "reversal_reason": request.reason_code,
                "document": {"document_type": "reversal_notice", "document_number": request.document_number, "evidence_hash": request.evidence_hash},
                "occurred_at": request.occurred_at,
                "business_date": request.business_date,
                "calendar_policy_version": request.calendar_policy_version,
                "correlation_id": request.correlation_id,
            }, ("append_reversal", "original_financial_truth_immutable"), "reverse")
            return CorrectionPlan(request.kind, "finance_reversal_required", (command,))
        if request.original_settlement_public_id is None or request.refund_settlement_public_id is None:
            raise R3Error("R3_REFUND_SETTLEMENTS_REQUIRED", str(request.source_public_id))
        command = _descriptor(request, 1, CORRECTION_CONTRACT, "RecognizeRefundCommand", {
            "amount": request.amount,
            "currency_code": request.currency_code,
            "original_settlement_public_id": request.original_settlement_public_id,
            "refund_settlement_public_id": request.refund_settlement_public_id,
            "refund_reason": request.reason_code,
            "document": {"document_type": "refund_notice", "document_number": request.document_number, "evidence_hash": request.evidence_hash},
            "occurred_at": request.occurred_at,
            "business_date": request.business_date,
            "calendar_policy_version": request.calendar_policy_version,
            "correlation_id": request.correlation_id,
        }, ("settlement_out", "correction_append", "original_revenue_immutable"), "refund")
        return CorrectionPlan(request.kind, "finance_refund_required", (command,))

    @staticmethod
    def report_plan(request: RestaurantReportRequest) -> RestaurantReportPlan:
        sources = {
            "sales_summary": ("NeutralFinance.StatementService", "NeutralFinance.TraceService", "SO9"),
            "commercial_adjustments": ("NeutralFinance.CommercialTerms", "NeutralFinance.CorrectionTrace", "SO9"),
            "participant_earnings": ("NeutralFinance.ParticipantEarnings", "NeutralFinance.Payables", "SO9"),
            "receivables": ("NeutralFinance.ObligationBalances", "NeutralFinance.ReceivableBalances", "SO9"),
        }
        if request.lens not in sources:
            raise R3Error("R3_REPORT_LENS_INVALID", request.lens)
        allowed = {"mode_code", "source_channel_code", "waiter_party_public_id", "cashier_party_public_id", "service_date", "order_code"}
        if any(x not in allowed for x in request.dimensions):
            raise R3Error("R3_REPORT_DIMENSION_INVALID", ",".join(request.dimensions))
        return RestaurantReportPlan(request.lens, sources[request.lens], request.dimensions)


def assert_plan_replay(existing: RestaurantFinancePlan, candidate: RestaurantFinancePlan) -> RestaurantFinancePlan:
    if (existing.tenant_id, existing.source_type, existing.source_public_id) != (candidate.tenant_id, candidate.source_type, candidate.source_public_id):
        raise R3Error("R3_REPLAY_IDENTITY_MISMATCH", str(candidate.source_public_id))
    if existing.plan_fingerprint != candidate.plan_fingerprint:
        raise R3Error("R3_MAPPING_IDEMPOTENCY_CONFLICT", str(candidate.source_public_id))
    return existing
