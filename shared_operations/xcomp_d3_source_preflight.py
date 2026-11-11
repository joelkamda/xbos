"""XCOMP D1/D2 SOF: pure, nonoperative source-handoff preflight.

A consumer-candidate for the accepted SOF/W S01-S12 matrix. This module checks
the shape and consistency of supplied *source* observations. It does not verify
the caller's identity, a provider signature, PC5, PK/PC4 entitlement, source
authenticity, or a PG17 readback; it never posts, authorizes, marks PAID, pays
commissions, resets books, or writes a queue. Only independently admitted domain
services may perform those effects in a subsequent release.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Mapping


SOURCE_CONTRACT = "xcomp.sof.d3.source_preflight.v1"
PAYMENT_STATES = frozenset({"CREATED", "UNKNOWN", "FAILED", "PROVIDER_FINAL_OBSERVED"})
NONEFFECTIVE = "SOURCE_ONLY_NOT_OPERATIVE"


@dataclass(frozen=True)
class ServerPricedOrder:
    tenant_id: int
    organization_unit_id: int
    order_public_id: str
    item_public_id: str
    stock_identity: str
    price_public_id: str
    price_code: str
    selected_price_code: str
    server_quote_ref: str
    unit_price: Decimal
    quantity: Decimal
    currency: str
    source_kind: str = "SO1_SERVER_QUOTE_CLAIM"
    merchant_profile: str = "restaurant"


@dataclass(frozen=True)
class FinanceTrace:
    tenant_id: int
    organization_unit_id: int
    order_public_id: str
    currency: str
    obligation_amount: Decimal
    settlement_amount: Decimal
    receivable_balance: Decimal
    payment_state: str
    provider_event_ref: str | None = None
    settlement_ref: str | None = None
    journal_ref: str | None = None
    finance_readback_ref: str | None = None
    receivable_ref: str | None = None
    refund_amount: Decimal = Decimal("0")
    refund_original_settlement_ref: str | None = None
    commission_requested: bool = False
    payout_requested: bool = False
    monthly_reset_requested: bool = False
    repayment_as_new_revenue: bool = False
    idempotency_key: str = ""
    prior_payload_fingerprint: str | None = None
    period_event_at: datetime | None = None
    close_as_of: datetime | None = None
    close_requested: bool = False
    close_variance: Decimal | None = None
    independent_actual_ref: str | None = None
    calendar_policy_ref: str | None = None


@dataclass(frozen=True)
class SourceReview:
    contract: str
    source_grade: str
    fingerprint: str
    findings: tuple[str, ...]
    source_consistent: bool
    runtime_effect_authorized: bool = False
    paid_status_authorized: bool = False
    commission_or_payout_authorized: bool = False
    ledger_write_authorized: bool = False
    close_authorized: bool = False


def _money(value: object, label: str, *, strictly_positive: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("NONFINITE_OR_INVALID_" + label) from exc
    if not amount.is_finite() or amount.adjusted() > 17:
        raise ValueError("NONFINITE_OR_INVALID_" + label)
    if amount < 0 or (strictly_positive and amount == 0):
        raise ValueError("NEGATIVE_OR_ZERO_" + label)
    return amount


def _readable(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_aware(value: datetime | None) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _canonical_decimal(value: Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _fingerprint(order: ServerPricedOrder, trace: FinanceTrace) -> str:
    """Stable nonsecret request fingerprint; never substitutes for provider evidence."""
    payload = {
        "scope": [order.tenant_id, order.organization_unit_id, order.order_public_id],
        "price": [order.merchant_profile, order.item_public_id, order.stock_identity, order.price_public_id,
                  order.price_code, order.selected_price_code, order.server_quote_ref,
                  _canonical_decimal(order.unit_price), _canonical_decimal(order.quantity), order.currency],
        "trace": [_canonical_decimal(trace.obligation_amount), _canonical_decimal(trace.settlement_amount),
                  _canonical_decimal(trace.receivable_balance), trace.payment_state,
                  trace.provider_event_ref, trace.settlement_ref, trace.journal_ref,
                  trace.finance_readback_ref, trace.receivable_ref, _canonical_decimal(trace.refund_amount),
                  trace.refund_original_settlement_ref, trace.commission_requested,
                  trace.payout_requested, trace.monthly_reset_requested,
                  trace.repayment_as_new_revenue, trace.idempotency_key,
                  trace.period_event_at.isoformat() if trace.period_event_at else None,
                  trace.close_as_of.isoformat() if trace.close_as_of else None,
                  trace.close_requested, _canonical_decimal(trace.close_variance) if trace.close_variance is not None else None,
                  trace.independent_actual_ref, trace.calendar_policy_ref],
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def inspect_source_trace(order: ServerPricedOrder, trace: FinanceTrace) -> SourceReview:
    """Fail closed on contradictory evidence while NEVER approving financial effects.

    An empty findings tuple means only that caller-supplied source fields are
    mutually consistent. It does not prove that a source, signature or ledger
    exists, and it must never be interpreted as a payment decision.
    """
    findings: list[str] = []
    if min(order.tenant_id, order.organization_unit_id, trace.tenant_id,
           trace.organization_unit_id) <= 0:
        findings.append("INVALID_SCOPE")
    if (order.tenant_id, order.organization_unit_id, order.order_public_id) != (
            trace.tenant_id, trace.organization_unit_id, trace.order_public_id):
        findings.append("TENANT_OR_ORDER_CROSSOVER")
    if not all(_readable(x) for x in (
        order.order_public_id, order.item_public_id, order.stock_identity,
        order.price_public_id, order.price_code, order.server_quote_ref
    )):
        findings.append("MISSING_SERVER_PRICE_IDENTITY")
    if order.source_kind != "SO1_SERVER_QUOTE_CLAIM":
        findings.append("CLIENT_SUPPLIED_PRICE_FORBIDDEN")
    if order.merchant_profile != "restaurant":
        findings.append("PAYMENTS_ONLY_MUST_BYPASS_R1")
    if order.selected_price_code != order.price_code:
        findings.append("AREA_PRICE_CODE_MISMATCH")
    if (not _readable(order.currency) or order.currency.upper() != order.currency
            or len(order.currency) != 3 or order.currency != trace.currency):
        findings.append("CURRENCY_MISMATCH")
    price = _money(order.unit_price, "UNIT_PRICE")
    qty = _money(order.quantity, "QUANTITY", strictly_positive=True)
    due = _money(trace.obligation_amount, "OBLIGATION")
    received = _money(trace.settlement_amount, "SETTLEMENT")
    ar = _money(trace.receivable_balance, "RECEIVABLE")
    refund = _money(trace.refund_amount, "REFUND")
    if price * qty != due:
        findings.append("SOURCE_PRICE_OBLIGATION_MISMATCH")
    if received > due:
        findings.append("TENDER_OVER_CAPACITY")
    if ar != due - received:
        findings.append("AR_NOT_OUTSTANDING_REMAINDER")
    if ar > 0 and not _readable(trace.receivable_ref):
        findings.append("AR_RECEIVABLE_REFERENCE_MISSING")
    if trace.payment_state not in PAYMENT_STATES:
        findings.append("INVALID_PAYMENT_STATE")
    if trace.payment_state != "PROVIDER_FINAL_OBSERVED" and received > 0:
        findings.append("CHECKOUT_CREATED_OR_UNKNOWN_IS_NOT_SETTLEMENT")
    if trace.payment_state == "PROVIDER_FINAL_OBSERVED":
        if not all(_readable(x) for x in (
            trace.provider_event_ref, trace.settlement_ref,
            trace.journal_ref, trace.finance_readback_ref
        )):
            findings.append("INDEPENDENT_PROVIDER_AND_FINANCE_PROOF_NOT_SUPPLIED")
    if refund > 0:
        if not _readable(trace.refund_original_settlement_ref):
            findings.append("UNLINKED_REFUND_FORBIDDEN")
        if refund > received:
            findings.append("REFUND_EXCEEDS_SETTLED_VALUE")
    if trace.commission_requested and (trace.payment_state != "PROVIDER_FINAL_OBSERVED"
                                       or received != due or ar != 0):
        findings.append("COMMISSION_BEFORE_FULL_VERIFIED_PAYMENT_DENIED")
    if trace.commission_requested:
        findings.append("COMMISSION_EFFECT_NOT_ADMITTED_BY_SOURCE_PREFLIGHT")
    if trace.payout_requested:
        findings.append("PAYROLL_OR_PAYOUT_NOT_ADMITTED")
    if trace.monthly_reset_requested:
        findings.append("MONTHLY_BANK_OR_AR_RESET_FORBIDDEN")
    if trace.repayment_as_new_revenue:
        findings.append("AR_REPAYMENT_IS_NOT_NEW_REVENUE")
    if not _readable(trace.idempotency_key):
        findings.append("MISSING_IDEMPOTENCY_KEY")
    if trace.close_requested:
        if not _utc_aware(trace.period_event_at) or not _utc_aware(trace.close_as_of):
            findings.append("CLOSE_MISSING_AWARE_TIMES")
        elif trace.close_as_of < trace.period_event_at:
            findings.append("STALE_CLOSE_AS_OF")
        if not _readable(trace.calendar_policy_ref):
            findings.append("MISSING_TENANT_CALENDAR")
        if not _readable(trace.independent_actual_ref):
            findings.append("CLOSE_MISSING_INDEPENDENT_ACTUAL")
        if trace.close_variance is None or _money(trace.close_variance.copy_abs()
                if isinstance(trace.close_variance, Decimal) else trace.close_variance,
                "CLOSE_VARIANCE") != 0:
            findings.append("CLOSE_VARIANCE_UNEXPLAINED")
        findings.append("CLOSE_EFFECT_NOT_ADMITTED_BY_SOURCE_PREFLIGHT")
    fingerprint = _fingerprint(order, trace)
    if trace.prior_payload_fingerprint is not None and (
            trace.prior_payload_fingerprint != fingerprint):
        findings.append("IDEMPOTENCY_KEY_CHANGED_PAYLOAD_DENIED")
    findings = list(dict.fromkeys(findings))
    return SourceReview(SOURCE_CONTRACT, NONEFFECTIVE, fingerprint, tuple(findings),
                        source_consistent=not findings)


def inspect_vip_same_stock(
    standard: ServerPricedOrder,
    vip: ServerPricedOrder,
) -> tuple[str, ...]:
    """Compare synthetic price-tier evidence, not pricing or stock registry truth."""
    problems = []
    if standard.tenant_id != vip.tenant_id or standard.organization_unit_id != vip.organization_unit_id:
        problems.append("VIP_TENANT_CROSSOVER")
    if standard.item_public_id != vip.item_public_id:
        problems.append("VIP_DIFFERENT_ITEM_CANNOT_COMPARE")
    if standard.stock_identity != vip.stock_identity:
        problems.append("VIP_DUPLICATE_STOCK_IDENTITY_DENIED")
    if standard.price_code == vip.price_code:
        problems.append("VIP_PRICE_BAND_NOT_DISTINCT")
    if (standard.selected_price_code != standard.price_code
            or vip.selected_price_code != vip.price_code):
        problems.append("VIP_CALLER_PRICE_DOWNGRADE_DENIED")
    return tuple(problems)


def replay_disposition(
    prior_by_scoped_key: Mapping[str, str],
    scoped_key: str,
    incoming_fingerprint: str,
) -> str:
    """Pure classification, no durable idempotency ledger or storage."""
    if not _readable(scoped_key) or not _readable(incoming_fingerprint):
        return "DENY_EMPTY_IDEMPOTENCY"
    old = prior_by_scoped_key.get(scoped_key)
    if old is None:
        return "FIRST_SOURCE_OBSERVATION_ONLY"
    return "EXACT_REPLAY_NO_NEW_EFFECT" if old == incoming_fingerprint else "DENY_CONFLICTING_REPLAY"
