from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session

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

        if existing:
            intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing.reference_id,
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
            meta=meta or {},
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
            meta=meta or {},
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
        if existing:
            existing_intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing.reference_id,
            )
            if existing_intent:
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

        normalized_meta = {
            **receipt_meta,
            "description": description,
            "customer": customer,
            "reference": reference,
        }

        sale = None
        intent = None

        if sale_id:
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
                    **normalized_meta,
                    "manual_payment": True,
                    "source": "payments_screen",
                },
            )

        intent_meta = dict(intent.meta or {})
        intent_meta.update(normalized_meta)

        # =========================
        # 🔥 PRESERVE POS FINANCIAL TRUTH
        # =========================

        if tendered_total is not None:
            intent_meta["tendered_total"] = _to_float(tendered_total)

        if change_amount is not None:
            intent_meta["change_amount"] = _to_float(change_amount)

        if change_given_now is not None:
            intent_meta["change_given_now"] = _to_float(change_given_now)

        if change_remaining is not None:
            intent_meta["change_remaining"] = _to_float(change_remaining)

        if tip_amount is not None:
            intent_meta["tip_amount"] = _to_float(tip_amount)

        if unpaid_amount is not None:
            intent_meta["unpaid_amount"] = _to_float(unpaid_amount)

        # =========================
        # 🔥 FORCE FINANCIAL FIELDS (CRITICAL FIX)
        # =========================

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

        # 🔒 WRITE BACK — SINGLE SOURCE OF TRUTH
        intent_meta["discount_total"] = float(discount_total)
        intent_meta["complimentary_total"] = float(complimentary_total)
        intent_meta["gross_total"] = float(gross_total)

        # =========================
        # ITEMS FALLBACK
        # =========================

        if "items" not in intent_meta:
            intent_meta["items"] = [
                {
                    "name": description or "Payment",
                    "quantity": 1,
                    "unit_price": float(_d(intent.amount)),
                    "line_total": float(_d(intent.amount)),
                }
            ]

        net_total = gross_total - discount_total - complimentary_total
        if net_total < 0:
            net_total = Decimal("0")

        intent.amount = net_total
        currency = (intent.currency or currency or "XAF").upper()

        unpaid_notes: List[str] = []
        # 🔥 EXTRACT RAW DECIMALS
        change_amount_d = _d(intent_meta.get("change_amount"))
        change_given_now_d = _d(intent_meta.get("change_given_now"))
        tip_amount_d = _d(intent_meta.get("tip_amount"))

        # 🔥 ENFORCE HARD CONSTRAINTS (BACKEND FINAL AUTHORITY)
        safe_given_d = min(change_given_now_d, change_amount_d)

        safe_tip_d = min(
            tip_amount_d,
            max(Decimal("0"), change_amount_d - safe_given_d)
        )

        # 🔥 FINAL STORE CREDIT (CHANGE OWED)
        store_credit = max(
            Decimal("0"),
            change_amount_d - (safe_given_d + safe_tip_d)
        )

        # 🔥 WRITE BACK NORMALIZED VALUES (FINAL SOURCE OF TRUTH)

        # Ensure Decimal → float conversion is safe and consistent
        final_given = float(safe_given_d)
        final_tip = float(safe_tip_d)
        final_change_remaining = float(store_credit)

        # 🔥 HARD SYNC — NO DRIFT ALLOWED
        intent_meta.update({
            "change_amount": float(change_amount_d),   # keep full trace
            "change_given_now": final_given,
            "tip_amount": final_tip,
            "change_remaining": final_change_remaining,
            "store_credit_amount": final_change_remaining,
        })

        # 🔥 OPTIONAL DEBUG (REMOVE AFTER VERIFYING)
        print("FINAL META (SERVICE):", intent_meta)

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
                meta=meta,
            )

            FinancialEventEmitter.payment_received(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                attempt_id=attempt.id,
                amount=attempt.amount,
                currency=currency,
                channel=attempt.method,
                meta={
                    "sale_id": sale_id,
                    "payment_intent_id": intent.id,
                    "manual_payment": payable_type == "manual",
                    "tendered_total": intent_meta.get("tendered_total"),
                    "change_amount": intent_meta.get("change_amount"),
                    "change_given_now": intent_meta.get("change_given_now"),
                    "change_remaining": intent_meta.get("change_remaining"),
                    "tip_amount": intent_meta.get("tip_amount"),
                },
            )

        total_paid = _d(
            PaymentAttemptRepository.sum_succeeded_for_intent(
                db,
                intent_id=intent.id,
            ) or 0
        )

        balance_due = net_total - total_paid
        if balance_due < 0:
            balance_due = Decimal("0")

        
        intent.meta = {
            **intent_meta,
            "net_total": float(net_total),
            "total_paid": float(total_paid),
            "balance_due": float(balance_due),
            "unpaid_notes": unpaid_notes,
            "store_credit_amount": float(store_credit),
            "manual_payment": payable_type == "manual",
        }

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

        record_idempotency_key(
            db,
            key=client_reference,
            scope="pos_settlement",
            reference_id=intent.id,
        )

        return intent