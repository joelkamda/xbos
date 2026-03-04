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


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


# =========================================================
# Webhook Event DTO
# =========================================================

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


# =========================================================
# PAYMENT SERVICE (Financial Authority)
# =========================================================

class PaymentService:
    """
    Tier-1 settlement authority.

    GUARANTEES:
    - Intent init is idempotent (client_reference scoped).
    - Attempts are append-only + idempotent by attempt client_reference.
    - Intent totals are system-owned.
    - Sale becomes PAID only when balance_due <= 0.
    """

    # -------------------------------------------------
    # INTENT INIT (idempotent)
    # -------------------------------------------------

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

        existing = check_idempotency_key(db, key=client_reference, scope="payment_intent")
        if existing:
            intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing.reference_id,
            )
            if intent:
                return intent

        intent = PaymentIntent(
            tenant_id=tenant_id,
            branch_id=branch_id,
            payable_type=payable_type,
            payable_id=payable_id,
            currency=currency,
            amount=_d(amount),
            status=PaymentIntentStatus.pending,
            channel=channel,
            created_by_user_id=created_by_user_id,
            gateway_intent_id=gateway_intent_id,
            total_paid=Decimal("0"),
            balance_due=_d(amount),
            meta=meta or {},
            created_at=datetime.utcnow(),
        )

        PaymentIntentRepository.create(db, intent=intent)
        db.flush()  # ensure intent.id exists

        record_idempotency_key(
            db,
            key=client_reference,
            scope="payment_intent",
            reference_id=intent.id,
        )
        return intent

    # -------------------------------------------------
    # ATTEMPT CREATION (append-only + idempotent)
    # -------------------------------------------------

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
        status: PaymentAttemptStatus = PaymentAttemptStatus.pending,
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
            status=status,
            client_reference=str(client_reference),
            provider_reference=provider_reference,
            meta=meta or {},
            created_at=datetime.utcnow(),
        )

        PaymentAttemptRepository.create(db, attempt=attempt)
        return attempt

    # -------------------------------------------------
    # TOTALS RECOMPUTE (system-owned)
    # -------------------------------------------------

    @staticmethod
    def recompute_intent_totals(
        db: Session,
        *,
        intent: PaymentIntent,
    ) -> PaymentIntent:

        total_paid = PaymentAttemptRepository.sum_succeeded_for_intent(
            db,
            intent_id=intent.id,
        )
        total_paid = _d(total_paid or 0)
        balance_due = _d(intent.amount) - total_paid

        PaymentIntentRepository.set_totals(
            intent=intent,
            total_paid=total_paid,
            balance_due=balance_due,
        )
        return intent

    # -------------------------------------------------
    # POS MANUAL SETTLEMENT (fixes receipts)
    # -------------------------------------------------

    @staticmethod
    def apply_pos_settlement(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        created_by_user_id: int,
        client_reference: str,
        lines: List[Dict[str, Any]],
        tendered_total: Optional[Decimal] = None,
        change_amount: Optional[Decimal] = None,
        unpaid_amount: Optional[Decimal] = None,
        note: Optional[str] = None,
        receipt_meta: Optional[Dict[str, Any]] = None,
    ) -> PaymentIntent:
        """
        Manual/instant settlement entrypoint.

        lines example:
        [
          {"method":"cash","amount":5000},
          {"method":"mtn","amount":2000},
          {"method":"orange","amount":1000},
          {"method":"unpaid","amount":500,"meta":{"note":"John owes"}}
        ]

        receipt_meta: any extra receipt fields you want attached:
          - gross_total, discount_total, complimentary_total, discount_reason, complimentary_items, etc
        """

        if not client_reference:
            raise ValueError("client_reference is required")

        intent = PaymentIntentRepository.get_by_payable(
            db,
            tenant_id=tenant_id,
            payable_type="sale",
            payable_id=sale_id,
        )
        if not intent:
            raise ValueError("PaymentIntent missing for sale")

        existing = check_idempotency_key(db, key=client_reference, scope="pos_settlement")
        if existing:
            existing_intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing.reference_id,
            )
            if existing_intent:
                return existing_intent

        unpaid_total = Decimal("0")
        unpaid_notes: List[str] = []

        for idx, line in enumerate(lines or []):
            method = str(line.get("method") or "").strip().lower()
            amount = _d(line.get("amount") or 0)
            provider = line.get("provider")
            meta = line.get("meta") or {}

            if amount <= 0:
                continue

            if method == "unpaid":
                unpaid_total += amount
                if meta.get("note"):
                    unpaid_notes.append(str(meta["note"]))
                continue

            if method in ("cash", "mtn", "orange", "wallet", "card"):
                raw = f"{client_reference}|{idx}|{method}|{amount}"
                digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
                attempt_ref = f"ps:{sale_id}:{idx}:{method}:{digest}"  # <= 64 chars

                PaymentService.create_attempt(
                    db,
                    intent=intent,
                    amount=amount,
                    method=method,
                    provider=provider,
                    settlement_mode="manual",
                    client_reference=attempt_ref,
                    status=PaymentAttemptStatus.succeeded,
                    meta=meta,
                )

        # -------------------------
        # Attach receipt-critical meta
        # -------------------------
        intent_meta = dict(intent.meta or {})

        # Preserve existing fields from sale creation (gross/discount/complimentary/etc)
        if receipt_meta:
            for k, v in receipt_meta.items():
                intent_meta[k] = v

        # POS fields
        if unpaid_amount is not None:
            intent_meta["unpaid_total"] = float(_d(unpaid_amount))
        elif unpaid_total > 0:
            intent_meta["unpaid_total"] = float(unpaid_total)

        if unpaid_notes:
            intent_meta["unpaid_notes"] = unpaid_notes

        if tendered_total is not None:
            intent_meta["tendered_total"] = float(_d(tendered_total))

        if change_amount is not None:
            intent_meta["change_amount"] = float(_d(change_amount))

        if note:
            intent_meta["pos_note"] = str(note)

        intent.meta = intent_meta

        # recompute totals
        PaymentService.recompute_intent_totals(db, intent=intent)

        # update intent status
        if intent.balance_due <= 0:
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.succeeded)
        elif intent.total_paid > 0:
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.processing)
        else:
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.pending)

        # settle sale
        if intent.payable_type == "sale" and intent.balance_due <= 0:
            sale = SaleRepository.get_by_id(db, tenant_id=tenant_id, sale_id=intent.payable_id)
            if sale and sale.status != SaleStatus.paid:
                SaleRepository.update_status(sale=sale, new_status=SaleStatus.paid)
                SaleRepository.set_paid_at(sale=sale, paid_at=datetime.utcnow())

        record_idempotency_key(db, key=client_reference, scope="pos_settlement", reference_id=intent.id)
        return intent

    # -------------------------------------------------
    # GATEWAY WEBHOOK SETTLEMENT
    # -------------------------------------------------

    @staticmethod
    def apply_gateway_webhook(
        db: Session,
        *,
        tenant_id: int,
        event: WebhookEvent,
    ) -> PaymentIntent:

        if event.callback_reference:
            existing = check_idempotency_key(db, key=event.callback_reference, scope="gateway_callback")
            if existing:
                intent = PaymentIntentRepository.get_by_id(db, tenant_id=tenant_id, intent_id=existing.reference_id)
                if intent:
                    return intent

        intent = PaymentIntentRepository.get_by_gateway_id(
            db,
            tenant_id=tenant_id,
            gateway_intent_id=event.gateway_intent_id,
        )
        if not intent:
            raise ValueError(f"PaymentIntent not found for gateway_intent_id={event.gateway_intent_id}")

        attempt_status = (
            PaymentAttemptStatus.succeeded
            if str(event.status).upper() == "SUCCEEDED"
            else PaymentAttemptStatus.failed
        )

        PaymentService.create_attempt(
            db,
            intent=intent,
            amount=_d(event.amount),
            method="xafpay",
            provider=event.provider,
            settlement_mode="async",
            client_reference=event.callback_reference,
            provider_reference=event.provider_reference,
            status=attempt_status,
            meta={
                "event": event.event,
                "currency": event.currency,
                "merchant_reference": event.merchant_reference,
                "occurred_at": datetime.utcnow().isoformat(),
            },
        )

        PaymentService.recompute_intent_totals(db, intent=intent)

        if intent.balance_due <= 0:
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.succeeded)
        else:
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.processing)

        if intent.payable_type == "sale" and intent.balance_due <= 0:
            sale = SaleRepository.get_by_id(db, tenant_id=tenant_id, sale_id=intent.payable_id)
            if sale and sale.status != SaleStatus.paid:
                SaleRepository.update_status(sale=sale, new_status=SaleStatus.paid)
                SaleRepository.set_paid_at(sale=sale, paid_at=datetime.utcnow())

        if event.callback_reference:
            record_idempotency_key(db, key=event.callback_reference, scope="gateway_callback", reference_id=intent.id)

        return intent