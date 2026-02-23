from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from core.domain.payments.models import (
    Payment,
    PaymentStatus,
    PaymentMethod,
    PaymentProvider,
)
from core.domain.payments.repository import PaymentRepository
from core.domain.sales.models import SaleStatus
from core.domain.sales.repository import SaleRepository

from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)


class PaymentService:
    """
    Domain service for Payments — Tier-1 settlement authority.

    GUARANTEES:
    - Payments are immutable once PAID / FAILED
    - Sale settlement is derived from payments (never assumed)
    - Fully split-payment safe
    """

    # -------------------------------------------------
    # Payment initialization
    # -------------------------------------------------

    @staticmethod
    def init_payment(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
        method: PaymentMethod,
        provider: Optional[PaymentProvider],
        amount: float,
        client_reference: str,
    ) -> Payment:
        """
        Initialize a new payment attempt.
        """

        # Idempotency guard
        existing = check_idempotency_key(
            db,
            key=client_reference,
            scope="payment",
        )
        if existing:
            payment = PaymentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                payment_id=existing.reference_id,
            )
            if payment:
                return payment

        payment = Payment(
            sale_id=sale_id,
            method=method,
            provider=provider,
            amount=amount,
            status=PaymentStatus.pending,
        )

        PaymentRepository.create(db, payment=payment)

        record_idempotency_key(
            db,
            key=client_reference,
            scope="payment",
            reference_id=payment.id,
        )

        return payment

    # -------------------------------------------------
    # Payment finalization — SUCCESS
    # -------------------------------------------------

    @staticmethod
    def mark_payment_success(
        db: Session,
        *,
        tenant_id: int,
        payment_id: int,
        gateway_reference: Optional[str] = None,
        callback_reference: Optional[str] = None,
    ) -> Payment:
        """
        Mark a payment as successful.

        RULES (LOCKED):
        - A payment is PAID exactly once
        - A sale is PAID ONLY when total_paid >= sale.total
        - Supports split payments natively
        """

        # -------------------------
        # Idempotency (gateway callback)
        # -------------------------
        if callback_reference:
            existing = check_idempotency_key(
                db,
                key=callback_reference,
                scope="payment_callback",
            )
            if existing:
                payment = PaymentRepository.get_by_id(
                    db,
                    tenant_id=tenant_id,
                    payment_id=existing.reference_id,
                )
                if payment:
                    return payment

        payment = PaymentRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            payment_id=payment_id,
        )
        if not payment:
            raise ValueError("Payment not found")

        if payment.status == PaymentStatus.paid:
            return payment

        if payment.status in (PaymentStatus.failed, PaymentStatus.cancelled):
            raise ValueError("Cannot mark failed/cancelled payment as paid")

        # -------------------------
        # Mark payment PAID
        # -------------------------
        PaymentRepository.set_status(
            payment=payment,
            status=PaymentStatus.paid,
        )
        PaymentRepository.set_completed_at(
            payment=payment,
            completed_at=datetime.utcnow(),
        )

        if gateway_reference:
            PaymentRepository.set_reference(
                payment=payment,
                reference=gateway_reference,
            )

        # -------------------------
        # Re-evaluate Sale settlement (split-safe)
        # -------------------------
        sale = payment.sale

        if sale.status != SaleStatus.paid:
            total_paid = PaymentRepository.sum_paid_for_sale(
                db,
                tenant_id=tenant_id,
                sale_id=sale.id,
            )

            if total_paid >= sale.total:
                SaleRepository.update_status(
                    sale=sale,
                    new_status=SaleStatus.paid,
                )
                SaleRepository.set_paid_at(
                    sale=sale,
                    paid_at=datetime.utcnow(),
                )

        if callback_reference:
            record_idempotency_key(
                db,
                key=callback_reference,
                scope="payment_callback",
                reference_id=payment.id,
            )

        return payment

    # -------------------------------------------------
    # Payment finalization — FAILURE
    # -------------------------------------------------

    @staticmethod
    def mark_payment_failed(
        db: Session,
        *,
        tenant_id: int,
        payment_id: int,
        gateway_reference: Optional[str] = None,
        callback_reference: Optional[str] = None,
    ) -> Payment:

        if callback_reference:
            existing = check_idempotency_key(
                db,
                key=callback_reference,
                scope="payment_callback",
            )
            if existing:
                payment = PaymentRepository.get_by_id(
                    db,
                    tenant_id=tenant_id,
                    payment_id=existing.reference_id,
                )
                if payment:
                    return payment

        payment = PaymentRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            payment_id=payment_id,
        )
        if not payment:
            raise ValueError("Payment not found")

        if payment.status == PaymentStatus.failed:
            return payment

        PaymentRepository.set_status(
            payment=payment,
            status=PaymentStatus.failed,
        )
        PaymentRepository.set_completed_at(
            payment=payment,
            completed_at=datetime.utcnow(),
        )

        if gateway_reference:
            PaymentRepository.set_reference(
                payment=payment,
                reference=gateway_reference,
            )

        if callback_reference:
            record_idempotency_key(
                db,
                key=callback_reference,
                scope="payment_callback",
                reference_id=payment.id,
            )

        return payment
