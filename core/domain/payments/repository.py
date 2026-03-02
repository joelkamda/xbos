from typing import Optional, List
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from core.domain.payments.models import (
    Payment,
    PaymentStatus,
    PaymentMethod,
    PaymentIntent,
    PaymentIntentStatus,
    PaymentAttempt,
    PaymentAttemptStatus,
)

from core.domain.sales.models import Sale


# =========================================================
# LEGACY PAYMENT REPOSITORY (kept for compatibility only)
# =========================================================

class PaymentRepository:

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        payment_id: int,
    ) -> Optional[Payment]:

        stmt = (
            select(Payment)
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.id == payment_id)
            .where(Sale.tenant_id == tenant_id)
        )

        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create(
        db: Session,
        *,
        payment: Payment,
    ) -> Payment:
        db.add(payment)
        return payment

    @staticmethod
    def set_status(
        *,
        payment: Payment,
        status: PaymentStatus,
    ) -> None:
        payment.status = status

    @staticmethod
    def sum_paid_for_sale(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
    ) -> float:

        stmt = (
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.sale_id == sale_id)
            .where(Payment.status == PaymentStatus.paid)
            .where(Sale.tenant_id == tenant_id)
        )

        return float(db.execute(stmt).scalar_one())


# =========================================================
# PAYMENT INTENT REPOSITORY (PRIMARY ARCHITECTURE)
# =========================================================

class PaymentIntentRepository:

    @staticmethod
    def create(
        db: Session,
        *,
        intent: PaymentIntent,
    ) -> PaymentIntent:
        db.add(intent)
        return intent

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        intent_id: int,
    ) -> Optional[PaymentIntent]:

        stmt = (
            select(PaymentIntent)
            .where(PaymentIntent.id == intent_id)
            .where(PaymentIntent.tenant_id == tenant_id)
        )

        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_by_gateway_id(
        db: Session,
        *,
        tenant_id: int,
        gateway_intent_id: str,
    ) -> Optional[PaymentIntent]:

        stmt = (
            select(PaymentIntent)
            .where(PaymentIntent.gateway_intent_id == gateway_intent_id)
            .where(PaymentIntent.tenant_id == tenant_id)
        )

        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def set_gateway_id(
        *,
        intent: PaymentIntent,
        gateway_intent_id: str,
    ) -> None:
        intent.gateway_intent_id = gateway_intent_id

    @staticmethod
    def set_status(
        *,
        intent: PaymentIntent,
        status: PaymentIntentStatus,
    ) -> None:
        intent.status = status

    @staticmethod
    def set_totals(
        *,
        intent: PaymentIntent,
        total_paid: Decimal,
        balance_due: Decimal,
    ) -> None:
        intent.total_paid = Decimal(total_paid)
        intent.balance_due = Decimal(balance_due)

    @staticmethod
    def list_by_status(
        db: Session,
        *,
        tenant_id: int,
        status: PaymentIntentStatus,
        limit: int = 50,
    ) -> List[PaymentIntent]:

        stmt = (
            select(PaymentIntent)
            .where(PaymentIntent.tenant_id == tenant_id)
            .where(PaymentIntent.status == status)
            .order_by(PaymentIntent.created_at.desc())
            .limit(limit)
        )

        return list(db.execute(stmt).scalars().all())


# =========================================================
# PAYMENT ATTEMPT REPOSITORY
# =========================================================

class PaymentAttemptRepository:

    @staticmethod
    def create(
        db: Session,
        *,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:
        db.add(attempt)
        return attempt

    @staticmethod
    def sum_succeeded_for_intent(
        db: Session,
        *,
        intent_id: int,
    ) -> Decimal:

        stmt = (
            select(func.coalesce(func.sum(PaymentAttempt.amount), 0))
            .where(PaymentAttempt.payment_intent_id == intent_id)
            .where(PaymentAttempt.status == PaymentAttemptStatus.succeeded)
        )

        result = db.execute(stmt).scalar_one()
        return Decimal(result or 0)

    @staticmethod
    def list_for_intent(
        db: Session,
        *,
        intent_id: int,
    ) -> List[PaymentAttempt]:

        stmt = (
            select(PaymentAttempt)
            .where(PaymentAttempt.payment_intent_id == intent_id)
            .order_by(PaymentAttempt.created_at.asc())
        )

        return list(db.execute(stmt).scalars().all())