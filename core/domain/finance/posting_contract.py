"""Executable M2.4 posting profiles and account-role policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .event_contract import FinancialEventValidationError


POSTING_CONTRACT = "XBOS_M24_CANONICAL_BALANCED_POSTING"
POSTING_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class PostingProfile:
    event_type_code: str
    profile_code: str
    mode: str
    debit_roles: tuple[str, ...] = ()
    credit_roles: tuple[str, ...] = ()


def _template(event: str, code: str, debit: str, credit: str) -> PostingProfile:
    return PostingProfile(event, code, "template", (debit,), (credit,))


POSTING_PROFILES = {
    profile.profile_code: profile
    for profile in (
        _template("COMMERCIAL_REVENUE_RECOGNIZED", "commercial_recognition", "trade_or_contract_receivable", "classified_revenue"),
        _template("TAX_LIABILITY_RECOGNIZED", "output_tax_recognition", "trade_or_contract_receivable", "tax_payable"),
        _template("DISCOUNT_GRANTED", "discount_contra_revenue", "sales_discount_contra_revenue", "trade_or_contract_receivable"),
        _template("COMPLIMENTARY_GRANTED", "complimentary_contra_revenue", "complimentary_contra_revenue", "trade_or_contract_receivable"),
        _template("COMPLIMENTARY_GRANTED", "complimentary_promotion", "marketing_or_promotional_expense", "trade_or_contract_receivable"),
        _template("COMPLIMENTARY_GRANTED", "complimentary_service_recovery", "service_recovery_expense", "trade_or_contract_receivable"),
        _template("TIP_RECOGNIZED", "tip_staff_liability", "trade_or_contract_receivable", "tip_payable"),
        _template("TIP_RECOGNIZED", "tip_tenant_income", "trade_or_contract_receivable", "tip_or_service_charge_income"),
        _template("COMMERCIAL_RETURN_RECOGNIZED", "commercial_return", "sales_returns_and_allowances", "trade_or_contract_receivable"),
        _template("COST_OF_FULFILLMENT_RECOGNIZED", "fulfillment_cost", "cost_of_goods_or_fulfillment", "inventory_or_deferred_cost_asset"),
        _template("EXPENSE_RECOGNIZED", "expense_accrual", "classified_expense", "trade_or_accrued_payable"),
        _template("OBLIGATION_WRITTEN_OFF", "receivable_writeoff", "writeoff_expense_or_allowance_reserve", "trade_receivable"),
        _template("OBLIGATION_WRITTEN_OFF", "payable_forgiveness", "trade_payable", "payable_forgiveness_gain_or_adjustment"),
        _template("PAYMENT_SETTLED", "inbound_settlement", "cash_bank_or_provider_asset", "unapplied_receipts_clearing"),
        _template("PAYMENT_SETTLED", "outbound_settlement", "disbursement_clearing", "cash_bank_or_provider_asset"),
        PostingProfile("PAYMENT_SETTLEMENT_REVERSED", "inverse_original_settlement", "inverse_original"),
        _template("PAYMENT_ALLOCATED", "receivable_allocation", "unapplied_receipts_clearing", "trade_receivable"),
        _template("PAYMENT_ALLOCATED", "payable_allocation", "trade_payable", "disbursement_clearing"),
        PostingProfile("PAYMENT_ALLOCATION_REVERSED", "inverse_original_allocation", "inverse_original"),
        _template("CUSTOMER_CREDIT_RECOGNIZED", "customer_credit_liability", "unapplied_receipts_clearing", "customer_credit_liability"),
        _template("REFUND_SETTLED", "customer_refund", "refund_payable_or_unapplied_receipts", "cash_bank_or_provider_asset"),
        _template("VALUE_TRANSFERRED", "operational_value_transfer", "target_operational_asset", "source_operational_asset"),
        _template("PROVIDER_FEE_RECOGNIZED", "provider_fee", "provider_fee_expense", "provider_settlement_receivable_or_payable"),
        _template("PROVIDER_SETTLEMENT_ADJUSTED", "provider_reserve_hold", "provider_reserve_asset", "provider_settlement_receivable"),
        _template("PROVIDER_SETTLEMENT_ADJUSTED", "provider_reserve_release", "provider_settlement_receivable", "provider_reserve_asset"),
        _template("PROVIDER_SETTLEMENT_ADJUSTED", "provider_chargeback_loss", "chargeback_loss_or_receivable", "provider_settlement_receivable"),
        PostingProfile("FINANCIAL_FACT_REVERSED", "inverse_original_fact", "inverse_original"),
    )
}

EVENT_PROFILES: dict[str, tuple[str, ...]] = {}
for _profile in POSTING_PROFILES.values():
    EVENT_PROFILES[_profile.event_type_code] = (
        *EVENT_PROFILES.get(_profile.event_type_code, ()),
        _profile.profile_code,
    )

NON_POSTING_EVENTS = frozenset({"OBLIGATION_OPENED"})

ACCOUNT_ROLE_POLICIES: dict[str, tuple[frozenset[str], frozenset[str], str]] = {
    "trade_or_contract_receivable": (frozenset({"asset"}), frozenset({"debit"}), "forbidden"),
    "trade_receivable": (frozenset({"asset"}), frozenset({"debit"}), "forbidden"),
    "classified_revenue": (frozenset({"income"}), frozenset({"credit"}), "forbidden"),
    "tax_payable": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "sales_discount_contra_revenue": (frozenset({"contra"}), frozenset({"debit"}), "forbidden"),
    "complimentary_contra_revenue": (frozenset({"contra"}), frozenset({"debit"}), "forbidden"),
    "marketing_or_promotional_expense": (frozenset({"expense"}), frozenset({"debit"}), "forbidden"),
    "service_recovery_expense": (frozenset({"expense"}), frozenset({"debit"}), "forbidden"),
    "tip_payable": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "tip_or_service_charge_income": (frozenset({"income"}), frozenset({"credit"}), "forbidden"),
    "sales_returns_and_allowances": (frozenset({"contra"}), frozenset({"debit"}), "forbidden"),
    "cost_of_goods_or_fulfillment": (frozenset({"expense"}), frozenset({"debit"}), "forbidden"),
    "inventory_or_deferred_cost_asset": (frozenset({"asset"}), frozenset({"debit"}), "forbidden"),
    "classified_expense": (frozenset({"expense"}), frozenset({"debit"}), "forbidden"),
    "trade_or_accrued_payable": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "trade_payable": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "writeoff_expense_or_allowance_reserve": (frozenset({"expense", "contra"}), frozenset({"debit", "credit"}), "forbidden"),
    "payable_forgiveness_gain_or_adjustment": (frozenset({"income", "equity"}), frozenset({"credit"}), "forbidden"),
    "cash_bank_or_provider_asset": (frozenset({"asset"}), frozenset({"debit"}), "required"),
    "unapplied_receipts_clearing": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "disbursement_clearing": (frozenset({"asset"}), frozenset({"debit"}), "forbidden"),
    "customer_credit_liability": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "refund_payable_or_unapplied_receipts": (frozenset({"liability"}), frozenset({"credit"}), "forbidden"),
    "target_operational_asset": (frozenset({"asset"}), frozenset({"debit"}), "required"),
    "source_operational_asset": (frozenset({"asset"}), frozenset({"debit"}), "required"),
    "provider_fee_expense": (frozenset({"expense"}), frozenset({"debit"}), "forbidden"),
    "provider_settlement_receivable_or_payable": (frozenset({"asset", "liability"}), frozenset({"debit", "credit"}), "optional"),
    "provider_reserve_asset": (frozenset({"asset"}), frozenset({"debit"}), "optional"),
    "provider_settlement_receivable": (frozenset({"asset"}), frozenset({"debit"}), "optional"),
    "chargeback_loss_or_receivable": (frozenset({"asset", "expense"}), frozenset({"debit"}), "forbidden"),
}


def select_posting_profile(
    event_type_code: str, posting_context: Mapping[str, Any]
) -> PostingProfile | None:
    if event_type_code in NON_POSTING_EVENTS:
        return None
    candidates = EVENT_PROFILES.get(event_type_code, ())
    if not candidates:
        raise FinancialEventValidationError(
            "posting_profile_missing",
            "posting-eligible event has no executable posting profile",
        )
    requested = posting_context.get("posting_profile_code")
    if requested is None:
        if len(candidates) != 1:
            raise FinancialEventValidationError(
                "posting_profile_required",
                "event has multiple posting profiles; posting_profile_code is required",
            )
        requested = candidates[0]
    requested = str(requested).strip().lower()
    if requested not in candidates:
        raise FinancialEventValidationError(
            "posting_profile_not_allowed",
            "posting profile is not approved for this event type",
        )
    return POSTING_PROFILES[requested]


def binding_key_for(posting_context: Mapping[str, Any], account_role: str) -> str:
    keys = posting_context.get("account_role_binding_keys", {})
    if not isinstance(keys, Mapping):
        raise FinancialEventValidationError(
            "invalid_binding_keys",
            "account_role_binding_keys must be a JSON object",
        )
    selected = str(keys.get(account_role, "default")).strip()
    if not selected:
        raise FinancialEventValidationError(
            "invalid_binding_key", "account-role binding key cannot be empty"
        )
    return selected
