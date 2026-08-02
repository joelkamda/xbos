from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)

from core.domain.sales.models import SaleStatus
from core.domain.sales.repository import SaleRepository
from core.domain.inventory.service import InventoryService

from core.domain.payments.models import (
    PaymentIntent,
    PaymentAttempt,
    PaymentIntentStatus,
    PaymentAttemptStatus,
)

from core.domain.payments.repository import (
    PaymentIntentRepository,
    PaymentAttemptRepository,
)

from core.domain.accounting.emitter import FinancialEventEmitter


# =====================================================
# HELPERS
# =====================================================

def _utc_now() -> datetime:
    """
    Canonical payment timestamp.

    payment_intents.created_at, payment_attempts.created_at, and sales.paid_at
    are timestamptz columns, so payment-service timestamps must be
    timezone-aware UTC instants.

    Display conversion to Africa/Douala belongs in API/UI serializers.
    """

    return datetime.now(timezone.utc)


def _d(v: Any) -> Decimal:
    try:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _enum_value(v: Any) -> Any:
    return getattr(v, "value", v)


def _to_float(v: Any) -> float:
    return float(_d(v))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_json_safe(v) for v in value]

    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]

    return value


def _idempotency_reference_id(existing: Any) -> Optional[Any]:
    if not existing:
        return None

    if hasattr(existing, "reference_id"):
        return existing.reference_id

    if isinstance(existing, dict):
        return existing.get("reference_id")

    try:
        return existing["reference_id"]
    except Exception:
        return None


def _status_succeeded(status_value: Any) -> bool:
    raw = str(getattr(status_value, "value", status_value) or "").lower()
    return raw in {"succeeded", "success", "completed", "complete", "paid"}


def _clean_label(value: Any) -> str:
    return str(value or "").strip()


def _discount_classification(discount_type: Any) -> Dict[str, Any]:
    """
    Classify POS discounts for expense reporting.

    These labels are stored in TreasuryLog.meta and consumed by daily,
    reconciliation-commercial, monthly, and yearly reports. They remain useful
    even before every tenant has dedicated finance taxonomy nodes.
    """
    raw = _clean_label(discount_type)
    key = raw.lower().replace("_", " ").replace("-", " ")
    key = " ".join(key.split())

    if key in {
        "staff subsidy",
        "staff discount",
        "employee discount",
        "personnel discount",
    }:
        return {
            "allowance_class": "staff_subsidy",
            "category_name": "Staff Welfare",
            "subcategory_name": "Staff Discount / Subsidy",
            "expense_family": "staff_expense",
            "display_label": "Staff Discount",
            "non_cash": True,
        }

    if key in {
        "loyalty discount",
        "customer discount",
        "customer loyalty",
        "regular customer",
    }:
        return {
            "allowance_class": "customer_discount",
            "category_name": "Marketing & Promotions",
            "subcategory_name": "Customer / Loyalty Discount",
            "expense_family": "customer_retention",
            "display_label": "Customer Discount",
            "non_cash": True,
        }

    if key in {
        "marketing promo",
        "marketing promotion",
        "promotion",
        "promotional discount",
        "offer",
        "special offer",
    }:
        return {
            "allowance_class": "marketing_promo",
            "category_name": "Marketing & Promotions",
            "subcategory_name": "Promotional Discount / Offer",
            "expense_family": "marketing_expense",
            "display_label": "Marketing Promotion",
            "non_cash": True,
        }

    if key in {
        "manager override",
        "manager discount",
        "management discount",
    }:
        return {
            "allowance_class": "manager_override",
            "category_name": "Sales Allowances",
            "subcategory_name": "Manager Override",
            "expense_family": "sales_allowance",
            "display_label": "Manager Override",
            "non_cash": True,
        }

    return {
        "allowance_class": "other_discount",
        "category_name": "Sales Allowances",
        "subcategory_name": raw or "Other Discount",
        "expense_family": "sales_allowance",
        "display_label": raw or "Other Discount",
        "non_cash": True,
    }


def _complimentary_classification(reason: Any = None) -> Dict[str, Any]:
    raw = _clean_label(reason)

    return {
        "allowance_class": "complimentary",
        "category_name": "Marketing & Promotions",
        "subcategory_name": raw or "Complimentary Items / Offer",
        "expense_family": "marketing_expense",
        "display_label": raw or "Complimentary",
        "non_cash": True,
    }


# =====================================================
# WEBHOOK EVENT MODEL
# =====================================================

@dataclass(frozen=True)
class WebhookEvent:
    event: str
    status: str
    amount: Decimal
    currency: str
    provider: str
    gateway_intent_id: str
    callback_reference: str
    merchant_reference: Optional[str] = None
    provider_reference: Optional[str] = None


# =====================================================
# PAYMENT SERVICE
# =====================================================

class PaymentService:

    # =====================================================
    # INIT INTENT
    # =====================================================

    @staticmethod
    def init_intent(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        payable_type: str,
        payable_id: int,
        currency: str,
        amount: Decimal,
        channel: str,
        created_by_user_id: int,
        client_reference: str,
        gateway_intent_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PaymentIntent:

        existing = check_idempotency_key(
            db,
            key=client_reference,
            scope="payment_intent",
        )

        existing_ref = _idempotency_reference_id(existing)

        if existing_ref:
            intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing_ref,
            )
            if intent:
                return intent

        amt = _d(amount)
        now = _utc_now()

        intent = PaymentIntent(
            tenant_id=tenant_id,
            branch_id=branch_id,
            payable_type=payable_type,
            payable_id=payable_id,
            currency=currency,
            amount=amt,
            status=_enum_value(PaymentIntentStatus.pending),
            channel=channel,
            created_by_user_id=created_by_user_id,
            gateway_intent_id=gateway_intent_id,
            total_paid=Decimal("0"),
            balance_due=amt,
            meta=_json_safe(meta or {}),
            created_at=now,
        )

        PaymentIntentRepository.create(db, intent=intent)
        db.flush()

        record_idempotency_key(
            db,
            key=client_reference,
            scope="payment_intent",
            reference_id=intent.id,
        )

        return intent

    # =====================================================
    # CREATE ATTEMPT
    # =====================================================

    @staticmethod
    def create_attempt(
        db: Session,
        *,
        intent: PaymentIntent,
        amount: Decimal,
        method: str,
        provider: Optional[str],
        settlement_mode: str,
        client_reference: str,
        provider_reference: Optional[str] = None,
        status: Any = PaymentAttemptStatus.pending,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PaymentAttempt:

        existing = PaymentAttemptRepository.get_by_client_reference(
            db,
            client_reference=client_reference,
        )
        if existing:
            return existing

        now = _utc_now()

        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            sale_id=intent.payable_id if intent.payable_type == "sale" else None,
            method=str(method),
            provider=str(provider) if provider else None,
            settlement_mode=str(settlement_mode),
            amount=_d(amount),
            status=_enum_value(status),
            client_reference=str(client_reference),
            provider_reference=provider_reference,
            meta=_json_safe(meta or {}),
            created_at=now,
        )

        PaymentAttemptRepository.create(db, attempt=attempt)
        db.flush()

        return attempt

    # =====================================================
    # ACCOUNTING EMISSION AFTER SETTLEMENT
    # =====================================================

    @staticmethod
    def _emit_settlement_accounting_events(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        intent: PaymentIntent,
        sale_id: Optional[int],
        payable_type: str,
        currency: str,
        gross_total: Decimal,
        net_total: Decimal,
        discount_total: Decimal,
        discount_type: Optional[str],
        complimentary_total: Decimal,
        complimentary_reason: Optional[str],
        complimentary_items: Any,
        total_paid: Decimal,
        balance_due: Decimal,
        store_credit: Decimal,
        tip_amount: Decimal,
        change_given_now: Decimal,
        current_tendered_total: Decimal,
        complete_balance: bool,
        settle_failed_intent: bool,
        occurred_at: datetime,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Emits settlement-side accounting events.

        Important rule:
        - change_given_now is NOT emitted as expense or separate ledger cash-out.
        - same-moment change is local cashier settlement.
        - payment_received is already reduced to the retained cash amount.
        - occurred_at is a UTC-aware settlement instant shared by related
          settlement accounting events.
        """

        base_meta = _json_safe(
            {
                **(meta or {}),
                "sale_id": sale_id,
                "payment_intent_id": int(intent.id),
                "payable_type": payable_type,
                "payable_id": intent.payable_id,
                "gross_total": gross_total,
                "net_total": net_total,
                "discount_total": discount_total,
                "discount_type": discount_type,
                "complimentary_total": complimentary_total,
                "complimentary_reason": complimentary_reason,
                "complimentary_items": complimentary_items,
                "total_paid": total_paid,
                "balance_due": balance_due,
                "store_credit_amount": store_credit,
                "tip_amount": tip_amount,
                "change_given_now": change_given_now,
                "tendered_total": current_tendered_total,
                "complete_balance": bool(complete_balance),
                "settle_failed_intent": bool(settle_failed_intent),
                "source": "pos_settlement",
            }
        )

        # -------------------------------------------------
        # Discount / Allowance
        # -------------------------------------------------
        if payable_type == "sale" and sale_id and discount_total > 0:
            classification = _discount_classification(discount_type)

            FinancialEventEmitter.sale_discount(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale_id,
                amount=discount_total,
                currency=currency,
                occurred_at=occurred_at,
                meta={
                    **base_meta,
                    **classification,
                    "event_reason": "discount_applied_at_settlement",
                    "discount_reason": discount_type,
                    "allowance_type": "discount",
                },
            )

        # -------------------------------------------------
        # Complimentary / Comp Allowance
        # -------------------------------------------------
        if payable_type == "sale" and sale_id and complimentary_total > 0:
            classification = _complimentary_classification(complimentary_reason)

            FinancialEventEmitter.sale_complimentary(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale_id,
                amount=complimentary_total,
                currency=currency,
                occurred_at=occurred_at,
                meta={
                    **base_meta,
                    **classification,
                    "event_reason": "complimentary_applied_at_settlement",
                    "complimentary_reason": complimentary_reason,
                    "allowance_type": "complimentary",
                },
            )

        # -------------------------------------------------
        # Debt / A-R
        # -------------------------------------------------
        if payable_type == "sale" and sale_id and balance_due > 0:
            FinancialEventEmitter.debt_created(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale_id,
                amount=balance_due,
                currency=currency,
                occurred_at=occurred_at,
                meta={
                    **base_meta,
                    "event_reason": "sale_partially_unpaid",
                },
            )

        # -------------------------------------------------
        # Store credit / A-P / change owed
        # -------------------------------------------------
        if payable_type == "sale" and sale_id and store_credit > 0:
            FinancialEventEmitter.store_credit_created(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale_id,
                amount=store_credit,
                currency=currency,
                occurred_at=occurred_at,
                meta={
                    **base_meta,
                    "event_reason": "change_remaining_as_store_credit",
                },
            )

        # -------------------------------------------------
        # Tip revenue
        # -------------------------------------------------
        if tip_amount > 0:
            FinancialEventEmitter.emit(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                idempotency_key=f"tip_revenue:intent:{intent.id}",
                direction="credit",
                event_type="TIP_REVENUE",
                amount=tip_amount,
                currency=currency,
                channel=None,
                reference_type="payment_intent",
                reference_id=int(intent.id),
                occurred_at=occurred_at,
                meta={
                    **base_meta,
                    "event_reason": "tip_recorded",
                },
            )

    # =====================================================
    # POS SETTLEMENT
    # =====================================================

    @staticmethod
    def apply_pos_settlement(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        created_by_user_id: int,
        client_reference: str,
        lines: List[Dict[str, Any]],
        sale_id: Optional[int] = None,
        existing_intent_id: Optional[Any] = None,
        complete_balance: bool = False,
        settle_failed_intent: bool = False,
        payable_type: str = "sale",
        payable_id: Optional[int] = None,
        currency: str = "XAF",
        tendered_total: Optional[Decimal] = None,
        change_amount: Optional[Decimal] = None,
        change_given_now: Optional[Decimal] = None,
        change_remaining: Optional[Decimal] = None,
        tip_amount: Optional[Decimal] = None,
        unpaid_amount: Optional[Decimal] = None,
        note: Optional[str] = None,
        receipt_meta: Optional[Dict[str, Any]] = None,
    ) -> PaymentIntent:

        if not client_reference:
            raise ValueError("client_reference is required")

        if not lines or not isinstance(lines, list):
            raise ValueError("lines are required")

        settlement_now = _utc_now()

        existing = check_idempotency_key(
            db,
            key=client_reference,
            scope="pos_settlement",
        )

        existing_ref = _idempotency_reference_id(existing)

        if existing_ref:
            existing_intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing_ref,
            )
            if existing_intent:
                print(f"[IDEMPOTENCY HIT] Returning existing intent {existing_intent.id}")
                return existing_intent

        receipt_meta = receipt_meta or {}

        description = receipt_meta.get("description")
        customer = receipt_meta.get("customer") or {}
        reference = receipt_meta.get("reference")

        if not description and lines:
            description = lines[0].get("name") or "Payment"

        if not customer and lines:
            meta_customer = lines[0].get("meta", {}).get("customer_name")
            if meta_customer:
                customer = {"name": meta_customer}

        incoming_meta = _json_safe(
            {
                **receipt_meta,
                "description": description,
                "customer": customer,
                "reference": reference,
            }
        )

        sale = None
        intent = None

        is_existing_intent_flow = bool(existing_intent_id)

        # =====================================================
        # EXISTING INTENT FLOW
        # =====================================================

        if is_existing_intent_flow:
            intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing_intent_id,
            )

            if not intent:
                raise ValueError(f"Existing PaymentIntent not found: {existing_intent_id}")

            if intent.tenant_id != tenant_id:
                raise ValueError("PaymentIntent tenant mismatch")

            if getattr(intent, "branch_id", branch_id) != branch_id:
                raise ValueError("PaymentIntent branch mismatch")

            payable_type = intent.payable_type
            payable_id = intent.payable_id
            currency = (intent.currency or currency or "XAF").upper()

            if intent.payable_type == "sale" and intent.payable_id:
                sale_id = intent.payable_id
                sale = SaleRepository.get_by_id(
                    db,
                    tenant_id=tenant_id,
                    sale_id=sale_id,
                )

        # =====================================================
        # SALE FLOW
        # =====================================================

        elif sale_id:
            payable_type = "sale"
            payable_id = sale_id

            sale = SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=sale_id,
            )
            if not sale:
                raise ValueError(f"Sale not found: {sale_id}")

            intent = PaymentIntentRepository.get_by_payable(
                db,
                tenant_id=tenant_id,
                payable_type="sale",
                payable_id=sale_id,
            )
            if not intent:
                raise ValueError("PaymentIntent missing for sale")

        # =====================================================
        # NEW MANUAL / DIRECT PAY FLOW
        # =====================================================

        else:
            payable_type = "manual"
            payable_id = payable_id or 0

            gross_total = sum(
                _d(line.get("amount"))
                for line in lines
                if _d(line.get("amount")) > 0
            )

            currency = (currency or "XAF").upper()

            intent = PaymentService.init_intent(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                payable_type="manual",
                payable_id=payable_id,
                currency=currency,
                amount=gross_total,
                channel="pos",
                created_by_user_id=created_by_user_id,
                client_reference=f"{client_reference}:intent",
                meta={
                    **incoming_meta,
                    "manual_payment": True,
                    "source": "payments_screen",
                },
            )

        # =====================================================
        # META MERGE
        # =====================================================

        intent_meta = dict(intent.meta or {})

        if is_existing_intent_flow:
            followups = list(intent_meta.get("followup_payments") or [])

            followups.append(
                _json_safe(
                    {
                        "client_reference": client_reference,
                        "receipt_meta": incoming_meta,
                        "complete_balance": bool(complete_balance),
                        "settle_failed_intent": bool(settle_failed_intent),
                        "created_at": settlement_now,
                    }
                )
            )

            intent_meta["followup_payments"] = followups
            intent_meta["last_followup_payment"] = incoming_meta
            intent_meta["last_followup_description"] = incoming_meta.get("description")
            intent_meta["last_followup_reference"] = incoming_meta.get("reference")
        else:
            intent_meta.update(incoming_meta)

        # =====================================================
        # PRESERVE POS FINANCIAL TRUTH
        # =====================================================

        current_tendered_total = _d(
            tendered_total
            if tendered_total is not None
            else incoming_meta.get("tendered_total")
        )

        if tendered_total is not None:
            intent_meta["current_tendered_total"] = _to_float(tendered_total)

        if change_amount is not None:
            intent_meta["change_amount"] = _to_float(change_amount)

        if change_given_now is not None:
            intent_meta["change_given_now"] = _to_float(change_given_now)

        if change_remaining is not None:
            intent_meta["change_remaining"] = _to_float(change_remaining)

        if tip_amount is not None:
            intent_meta["tip_amount"] = _to_float(tip_amount)

        if unpaid_amount is not None:
            intent_meta["current_unpaid_amount"] = _to_float(unpaid_amount)

        # =====================================================
        # ORIGINAL FINANCIAL BASIS
        # =====================================================

        discount_type = (
            intent_meta.get("discount_type")
            or intent_meta.get("discount_reason")
            or receipt_meta.get("discount_type")
            or receipt_meta.get("discount_reason")
        )

        complimentary_reason = (
            intent_meta.get("complimentary_reason")
            or receipt_meta.get("complimentary_reason")
            or receipt_meta.get("comp_reason")
        )

        complimentary_items = (
            intent_meta.get("complimentary_items")
            or receipt_meta.get("complimentary_items")
            or []
        )

        if is_existing_intent_flow:
            discount_total = _d(intent_meta.get("discount_total") or 0)
            complimentary_total = _d(intent_meta.get("complimentary_total") or 0)

            net_total = _d(
                intent_meta.get("net_total")
                or intent.amount
                or intent_meta.get("gross_total")
                or 0
            )

            gross_total = _d(
                intent_meta.get("gross_total")
                or intent_meta.get("original_total")
                or net_total
            )

        else:
            discount_total = _d(
                intent_meta.get("discount_total")
                or receipt_meta.get("discount_total")
                or 0
            )

            complimentary_total = _d(
                intent_meta.get("complimentary_total")
                or receipt_meta.get("complimentary_total")
                or 0
            )

            gross_total = _d(
                intent_meta.get("gross_total")
                or receipt_meta.get("gross_total")
                or intent.amount
            )

            net_total = gross_total - discount_total - complimentary_total
            if net_total < 0:
                net_total = Decimal("0")

            intent.amount = net_total

        currency = (intent.currency or currency or "XAF").upper()

        intent_meta["discount_total"] = float(discount_total)
        intent_meta["discount_type"] = discount_type
        intent_meta["discount_reason"] = discount_type
        intent_meta["complimentary_total"] = float(complimentary_total)
        intent_meta["complimentary_reason"] = complimentary_reason
        intent_meta["complimentary_items"] = complimentary_items
        intent_meta["gross_total"] = float(gross_total)
        intent_meta["original_total"] = float(gross_total)
        intent_meta["net_total"] = float(net_total)
        intent_meta["client_pays"] = float(net_total)

        # =====================================================
        # ITEMS FALLBACK
        # =====================================================

        if "items" not in intent_meta or not intent_meta.get("items"):
            intent_meta["items"] = [
                {
                    "name": description or "Payment",
                    "quantity": 1,
                    "unit_price": float(_d(intent.amount)),
                    "line_total": float(_d(intent.amount)),
                }
            ]

        unpaid_notes: List[str] = []

        # =====================================================
        # CHANGE / STORE CREDIT MODEL
        # =====================================================

        change_amount_d = _d(intent_meta.get("change_amount"))
        change_given_now_d = _d(intent_meta.get("change_given_now"))
        tip_amount_d = _d(intent_meta.get("tip_amount"))
        explicit_change_remaining_d = _d(
            change_remaining
            if change_remaining is not None
            else intent_meta.get("change_remaining")
        )

        safe_given_d = min(change_given_now_d, change_amount_d)

        safe_tip_d = min(
            tip_amount_d,
            max(Decimal("0"), change_amount_d - safe_given_d),
        )

        computed_store_credit = max(
            Decimal("0"),
            change_amount_d - (safe_given_d + safe_tip_d),
        )

        change_owed_line_total = Decimal("0")
        store_credit = computed_store_credit

        intent_meta.update(
            {
                "change_amount": float(change_amount_d),
                "change_given_now": float(safe_given_d),
                "tip_amount": float(safe_tip_d),
                "change_remaining": float(store_credit),
                "store_credit_amount": float(store_credit),
            }
        )

        # =====================================================
        # CREATE PAYMENT ATTEMPTS + RETAINED COLLECTION LEDGER
        # =====================================================

        change_given_remaining = safe_given_d

        for idx, line in enumerate(lines or []):
            method = str(line.get("method") or "").lower()
            amount = _d(line.get("amount"))
            meta = line.get("meta") or {}

            if amount <= 0:
                continue

            if method == "unpaid":
                if meta.get("tag") == "CHANGE_OWED":
                    change_owed_line_total += amount
                else:
                    if meta.get("note"):
                        unpaid_notes.append(meta["note"])
                continue

            raw = f"{client_reference}|{idx}|{method}|{amount}"
            digest = hashlib.sha1(raw.encode()).hexdigest()[:16]

            attempt = PaymentService.create_attempt(
                db,
                intent=intent,
                amount=amount,
                method=method,
                provider=line.get("provider"),
                settlement_mode="manual",
                client_reference=f"ps:{intent.id}:{idx}:{digest}",
                status=PaymentAttemptStatus.succeeded,
                meta=_json_safe(
                    {
                        **meta,
                        "complete_balance": bool(complete_balance),
                        "settle_failed_intent": bool(settle_failed_intent),
                        "parent_intent_id": int(intent.id),
                        "current_receipt_meta": incoming_meta
                        if is_existing_intent_flow
                        else None,
                    }
                ),
            )

            ledger_amount = attempt.amount
            retained_adjustment = Decimal("0")

            # Same-moment cash change is local cashier settlement.
            # It should not create expense, A/P, or a separate CHANGE_RETURNED row.
            # Instead, only the retained cash amount is posted as PAYMENT_RECEIVED.
            if method == "cash" and change_given_remaining > 0:
                retained_adjustment = min(ledger_amount, change_given_remaining)
                ledger_amount = ledger_amount - retained_adjustment
                change_given_remaining = change_given_remaining - retained_adjustment

            if ledger_amount > 0:
                FinancialEventEmitter.payment_received(
                    db,
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    attempt_id=attempt.id,
                    amount=ledger_amount,
                    currency=currency,
                    channel=attempt.method,
                    occurred_at=attempt.created_at or settlement_now,
                    meta=_json_safe(
                        {
                            "sale_id": sale_id,
                            "payment_intent_id": int(intent.id),
                            "manual_payment": payable_type == "manual",
                            "tendered_attempt_amount": amount,
                            "retained_collection_amount": ledger_amount,
                            "change_given_applied_to_cash": retained_adjustment,
                            "tendered_total": current_tendered_total
                            if current_tendered_total > 0
                            else intent_meta.get("tendered_total"),
                            "change_amount": intent_meta.get("change_amount"),
                            "change_given_now": intent_meta.get("change_given_now"),
                            "change_remaining": intent_meta.get("change_remaining"),
                            "tip_amount": intent_meta.get("tip_amount"),
                            "complete_balance": bool(complete_balance),
                            "settle_failed_intent": bool(settle_failed_intent),
                        }
                    ),
                )

        # =====================================================
        # FINALIZE CHANGE / STORE CREDIT AFTER LINE INSPECTION
        # =====================================================

        store_credit = max(
            computed_store_credit,
            explicit_change_remaining_d,
            change_owed_line_total,
        )

        intent_meta.update(
            {
                "change_amount": float(change_amount_d),
                "change_given_now": float(safe_given_d),
                "tip_amount": float(safe_tip_d),
                "change_remaining": float(store_credit),
                "store_credit_amount": float(store_credit),
                "change_owed_line_total": float(change_owed_line_total),
                "computed_store_credit": float(computed_store_credit),
                "explicit_change_remaining": float(explicit_change_remaining_d),
                "cash_change_given_not_posted_to_ledger": float(safe_given_d),
            }
        )

        # =====================================================
        # CUMULATIVE TOTALS
        # =====================================================

        cumulative_tendered_total = _d(
            PaymentAttemptRepository.sum_succeeded_for_intent(
                db,
                intent_id=intent.id,
            )
            or 0
        )

        if cumulative_tendered_total <= 0 and current_tendered_total > 0:
            cumulative_tendered_total = current_tendered_total

        total_paid = min(net_total, cumulative_tendered_total)

        balance_due = net_total - total_paid
        if balance_due < 0:
            balance_due = Decimal("0")

        intent_meta["tendered_total"] = float(cumulative_tendered_total)
        intent_meta["total_tendered"] = float(cumulative_tendered_total)

        intent.meta = _json_safe(
            {
                **intent_meta,
                "net_total": float(net_total),
                "total_paid": float(total_paid),
                "paid_total": float(total_paid),
                "balance_due": float(balance_due),
                "unpaid_total": float(balance_due),
                "unpaid_notes": unpaid_notes,
                "store_credit_amount": float(store_credit),
                "manual_payment": payable_type == "manual",
            }
        )

        PaymentIntentRepository.set_totals(
            intent=intent,
            total_paid=total_paid,
            balance_due=balance_due,
        )

        if balance_due <= 0:
            PaymentIntentRepository.set_status(
                intent=intent,
                status=PaymentIntentStatus.succeeded,
            )
        elif total_paid > 0:
            PaymentIntentRepository.set_status(
                intent=intent,
                status=PaymentIntentStatus.processing,
            )
        else:
            PaymentIntentRepository.set_status(
                intent=intent,
                status=PaymentIntentStatus.pending,
            )

        # =====================================================
        # ADDITIONAL ACCOUNTING EVENTS
        # =====================================================

        PaymentService._emit_settlement_accounting_events(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            intent=intent,
            sale_id=sale_id,
            payable_type=payable_type,
            currency=currency,
            gross_total=gross_total,
            net_total=net_total,
            discount_total=discount_total,
            discount_type=discount_type,
            complimentary_total=complimentary_total,
            complimentary_reason=complimentary_reason,
            complimentary_items=complimentary_items,
            total_paid=total_paid,
            balance_due=balance_due,
            store_credit=store_credit,
            tip_amount=safe_tip_d,
            change_given_now=safe_given_d,
            current_tendered_total=cumulative_tendered_total,
            complete_balance=complete_balance,
            settle_failed_intent=settle_failed_intent,
            occurred_at=settlement_now,
            meta={
                "description": description,
                "reference": reference,
                "customer": customer,
                "receipt_no": intent_meta.get("receipt_no"),
                "unpaid_notes": unpaid_notes,
                "change_owed_line_total": change_owed_line_total,
                "computed_store_credit": computed_store_credit,
                "explicit_change_remaining": explicit_change_remaining_d,
            },
        )

        # =====================================================
        # FINALIZE SALE + INVENTORY
        # =====================================================
        if sale and balance_due <= 0 and sale.status != SaleStatus.paid:
            SaleRepository.update_status(
                sale=sale,
                new_status=SaleStatus.paid,
            )
            SaleRepository.set_paid_at(
                sale=sale,
                paid_at=settlement_now,
            )

            # Inventory finalization rule:
            # - If sale came from an order, order stock was already withheld.
            #   This creates zero-delta sale_commit markers only.
            # - If sale has no reservation, this deducts as direct sale.
            # - It is idempotent and prevents double deduction.
            InventoryService.finalize_sale_inventory(
                db,
                sale=sale,
            )

        try:
            record_idempotency_key(
                db,
                key=client_reference,
                scope="pos_settlement",
                reference_id=intent.id,
            )
        except IntegrityError:
            existing = check_idempotency_key(
                db,
                key=client_reference,
                scope="pos_settlement",
            )
            existing_ref = _idempotency_reference_id(existing)

            if existing_ref:
                existing_intent = PaymentIntentRepository.get_by_id(
                    db,
                    tenant_id=tenant_id,
                    intent_id=existing_ref,
                )
                if existing_intent:
                    print(f"[RACE RECOVERY] Returning existing intent {existing_intent.id}")
                    return existing_intent
            raise

        return intent