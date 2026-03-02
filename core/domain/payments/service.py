from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)

from core.domain.sales.models import SaleStatus
from core.domain.sales.repository import SaleRepository

# ✅ NEW MODEL imports (adjust names if yours differ)
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


@dataclass(frozen=True)
class WebhookEvent:
    event: str
    status: str
    amount: Decimal
    currency: str
    provider: str                # e.g. "tranzak"
    gateway_intent_id: str       # UUID string
    callback_reference: str      # event id
    merchant_reference: Optional[str] = None  # e.g. sale_id string
    provider_reference: Optional[str] = None  # e.g. Tranzak rid


class PaymentService:
    """
    Domain service for PaymentIntents + PaymentAttempts (Tier-1 settlement authority)

    GUARANTEES:
    - Webhook idempotency via callback_reference
    - PaymentAttempt is append-only (no edits; new attempts represent retries)
    - PaymentIntent totals are system-owned (recomputed by service only)
    - Sale becomes PAID only when intent.balance_due <= 0 (split-safe)
    """

    # -------------------------------------------------
    # Intent initialization (called from /xafpay/init)
    # -------------------------------------------------
    @staticmethod
    def init_intent(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        payable_type: str,     # "sale" for now
        payable_id: int,       # sale_id
        currency: str,
        amount: Decimal,
        channel: str,          # "xafpay" or "pos" etc.
        created_by_user_id: int,
        client_reference: str, # idempotency key from UI
        gateway_intent_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PaymentIntent:
        """
        Creates a PaymentIntent (idempotent by client_reference).
        """

        # Idempotency guard: if client_reference already created an intent, return it.
        existing = check_idempotency_key(db, key=client_reference, scope="payment_intent")
        if existing:
            intent = PaymentIntentRepository.get_by_id(
                db, tenant_id=tenant_id, intent_id=existing.reference_id
            )
            if intent:
                return intent

        intent = PaymentIntent(
            tenant_id=tenant_id,
            branch_id=branch_id,
            payable_type=payable_type,
            payable_id=payable_id,
            currency=currency,
            amount=amount,
            status=PaymentIntentStatus.pending,
            channel=channel,
            created_by_user_id=created_by_user_id,
            gateway_intent_id=gateway_intent_id,
            total_paid=Decimal("0"),
            balance_due=amount,
            meta=meta or {},
        )

        PaymentIntentRepository.create(db, intent=intent)

        record_idempotency_key(
            db,
            key=client_reference,
            scope="payment_intent",
            reference_id=intent.id,
        )

        return intent

    # -------------------------------------------------
    # Attempt initialization (optional; if you create an attempt at init-time)
    # -------------------------------------------------
    @staticmethod
    def create_attempt(
        db: Session,
        *,
        intent: PaymentIntent,
        amount: Decimal,
        method: str,
        provider: str,
        settlement_mode: str,
        client_reference: str,
        provider_reference: Optional[str] = None,
        status: PaymentAttemptStatus = PaymentAttemptStatus.pending,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PaymentAttempt:

        attempt = PaymentAttempt(
            payment_intent_id=intent.id,
            sale_id=intent.payable_id if intent.payable_type == "sale" else None,
            method=method,
            provider=provider,
            settlement_mode=settlement_mode,
            amount=amount,
            status=status,
            client_reference=client_reference,
            provider_reference=provider_reference,
            meta=meta or {},
            created_at=datetime.utcnow(),
        )

        PaymentAttemptRepository.create(db, attempt=attempt)
        return attempt

    # -------------------------------------------------
    # Totals recompute (system-owned)
    # -------------------------------------------------
    @staticmethod
    def recompute_intent_totals(
        db: Session,
        *,
        intent: PaymentIntent,
    ) -> PaymentIntent:
        """
        Recompute total_paid and balance_due from successful attempts only.
        """
        total_paid = PaymentAttemptRepository.sum_succeeded_for_intent(
            db,
            intent_id=intent.id,
        )

        total_paid = Decimal(total_paid or 0)
        balance_due = (Decimal(intent.amount) - total_paid)

        PaymentIntentRepository.set_totals(
            intent=intent,
            total_paid=total_paid,
            balance_due=balance_due,
        )

        return intent

    # -------------------------------------------------
    # Webhook settlement entrypoint
    # -------------------------------------------------
    @staticmethod
    def apply_gateway_webhook(
        db: Session,
        *,
        tenant_id: int,
        event: WebhookEvent,
    ) -> PaymentIntent:
        """
        Main webhook handler: resolves intent by gateway_intent_id, appends attempt, recomputes totals,
        settles sale if paid, idempotent by callback_reference.
        """

        # -------------------------
        # Idempotency: callback_reference must be unique
        # -------------------------
        if event.callback_reference:
            existing = check_idempotency_key(
                db,
                key=event.callback_reference,
                scope="gateway_callback",
            )
            if existing:
                intent = PaymentIntentRepository.get_by_id(
                    db, tenant_id=tenant_id, intent_id=existing.reference_id
                )
                if intent:
                    return intent

        # -------------------------
        # Find intent by gateway_intent_id
        # -------------------------
        intent = PaymentIntentRepository.get_by_gateway_id(
            db,
            tenant_id=tenant_id,
            gateway_intent_id=event.gateway_intent_id,
        )
        if not intent:
            raise ValueError(f"PaymentIntent not found for gateway_intent_id={event.gateway_intent_id}")

        # -------------------------
        # Append attempt from webhook
        # -------------------------
        attempt_status = (
            PaymentAttemptStatus.succeeded if event.status == "SUCCEEDED" else PaymentAttemptStatus.failed
        )

        existing_attempt = db.query(PaymentAttempt).filter(
            PaymentAttempt.client_reference == event.callback_reference
        ).first()

        if existing_attempt:
            # Already processed this webhook
            return intent
            
        PaymentService.create_attempt(
            db,
            intent=intent,
            amount=event.amount,
            method=intent.channel,               # usually "xafpay"
            provider=event.provider,             # tranzak
            settlement_mode="async",             # gateway flow
            client_reference=event.callback_reference,
            provider_reference=event.provider_reference,
            status=attempt_status,
            meta={
                "event": event.event,
                "currency": event.currency,
                "occurred_at": datetime.utcnow().isoformat(),
                "merchant_reference": event.merchant_reference,
            },
        )

        # -------------------------
        # Update intent status + totals
        # -------------------------
        PaymentService.recompute_intent_totals(db, intent=intent)

        if intent.balance_due <= 0:
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.succeeded)
        else:
            # Still due -> keep pending/processing
            PaymentIntentRepository.set_status(intent=intent, status=PaymentIntentStatus.processing)

        # -------------------------
        # Settle Sale if fully paid
        # -------------------------
        if intent.payable_type == "sale" and intent.balance_due <= 0:
            sale = SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=intent.payable_id,
            )
            if sale and sale.status != SaleStatus.paid:
                SaleRepository.update_status(sale=sale, new_status=SaleStatus.paid)
                SaleRepository.set_paid_at(sale=sale, paid_at=datetime.utcnow())

        # -------------------------
        # Record callback idempotency
        # -------------------------
        if event.callback_reference:
            record_idempotency_key(
                db,
                key=event.callback_reference,
                scope="gateway_callback",
                reference_id=intent.id,
            )

        return intent