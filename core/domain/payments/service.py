from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
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
    """
    Recursively convert values to JSON-safe primitives.

    This protects:
    - PaymentAttempt.meta JSON column
    - PaymentIntent.meta JSON column
    - treasury_logs.meta JSON column emitted through FinancialEventEmitter
    """
    if isinstance(value, Decimal):
      return float(value)

    if isinstance(value, datetime):
      return value.isoformat()

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
            created_at=datetime.utcnow(),
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
            created_at=datetime.utcnow(),
        )

        PaymentAttemptRepository.create(db, attempt=attempt)
        db.flush()

        return attempt

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
        # - Used by Complete Balance and Settle Another Way
        # - Must NOT create a new PaymentIntent
        # - Must add a new PaymentAttempt under the existing intent
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
                        "created_at": datetime.utcnow(),
                    }
                )
            )

            intent_meta["followup_payments"] = followups
            intent_meta["last_followup_payment"] = incoming_meta

            # Do not overwrite original description/items/gross_total.
            # Only preserve current tender/change trace.
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
        intent_meta["complimentary_total"] = float(complimentary_total)
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

        safe_given_d = min(change_given_now_d, change_amount_d)

        safe_tip_d = min(
            tip_amount_d,
            max(Decimal("0"), change_amount_d - safe_given_d),
        )

        store_credit = max(
            Decimal("0"),
            change_amount_d - (safe_given_d + safe_tip_d),
        )

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
        # CREATE PAYMENT ATTEMPTS
        # =====================================================

        for idx, line in enumerate(lines or []):
            method = str(line.get("method") or "").lower()
            amount = _d(line.get("amount"))
            meta = line.get("meta") or {}

            if amount <= 0:
                continue

            if method == "unpaid":
                if meta.get("tag") == "CHANGE_OWED":
                    store_credit += amount
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

            FinancialEventEmitter.payment_received(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                attempt_id=attempt.id,
                amount=attempt.amount,
                currency=currency,
                channel=attempt.method,
                meta=_json_safe(
                    {
                        "sale_id": sale_id,
                        "payment_intent_id": int(intent.id),
                        "manual_payment": payable_type == "manual",
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

        if sale and balance_due <= 0 and sale.status != SaleStatus.paid:
            SaleRepository.update_status(
                sale=sale,
                new_status=SaleStatus.paid,
            )
            SaleRepository.set_paid_at(
                sale=sale,
                paid_at=datetime.utcnow(),
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