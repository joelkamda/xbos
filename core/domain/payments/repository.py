from typing import Optional, List
from decimal import Decimal
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from core.domain.payments.models import (
    PaymentIntent,
    PaymentAttempt,
    PaymentIntentStatus,
    PaymentAttemptStatus,
    PaymentMethod,
)
from core.domain.sales.models import Sale


# =====================================================
# PAYMENT INTENT REPOSITORY
# =====================================================

class PaymentIntentRepository:
    """
    Data-access layer for PaymentIntent.

    NO business logic.
    """

    # -------------------------------------------------
    # Core fetches
    # -------------------------------------------------

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
    def get_for_sale(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
    ) -> Optional[PaymentIntent]:

        stmt = (
            select(PaymentIntent)
            .where(PaymentIntent.payable_type == "sale")
            .where(PaymentIntent.payable_id == sale_id)
            .where(PaymentIntent.tenant_id == tenant_id)
        )

        return db.execute(stmt).scalar_one_or_none()

    # -------------------------------------------------
    # Persistence
    # -------------------------------------------------

    @staticmethod
    def create(
        db: Session,
        *,
        intent: PaymentIntent,
    ) -> PaymentIntent:

        db.add(intent)
        return intent

    # -------------------------------------------------
    # Field mutations (no semantics)
    # -------------------------------------------------

    @staticmethod
    def set_status(
        *,
        intent: PaymentIntent,
        status: PaymentIntentStatus,
    ) -> None:
        intent.status = status

    @staticmethod
    def update_aggregates(
        *,
        intent: PaymentIntent,
        total_paid: Decimal,
        balance_due: Decimal,
    ) -> None:
        intent.total_paid = total_paid
        intent.balance_due = balance_due


# =====================================================
# PAYMENT ATTEMPT REPOSITORY
# =====================================================

class PaymentAttemptRepository:
    """
    Data-access layer for PaymentAttempt.

    NO business logic.
    """

    # -------------------------------------------------
    # Fetches
    # -------------------------------------------------

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        attempt_id: int,
    ) -> Optional[PaymentAttempt]:

        stmt = (
            select(PaymentAttempt)
            .join(PaymentIntent, PaymentIntent.id == PaymentAttempt.payment_intent_id)
            .where(PaymentAttempt.id == attempt_id)
            .where(PaymentIntent.tenant_id == tenant_id)
        )

        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_for_intent(
        db: Session,
        *,
        tenant_id: int,
        intent_id: int,
    ) -> List[PaymentAttempt]:

        stmt = (
            select(PaymentAttempt)
            .join(PaymentIntent, PaymentIntent.id == PaymentAttempt.payment_intent_id)
            .where(PaymentAttempt.payment_intent_id == intent_id)
            .where(PaymentIntent.tenant_id == tenant_id)
            .order_by(PaymentAttempt.created_at.asc())
        )

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_latest_for_intent(
        db: Session,
        *,
        tenant_id: int,
        intent_id: int,
    ) -> Optional[PaymentAttempt]:

        stmt = (
            select(PaymentAttempt)
            .join(PaymentIntent, PaymentIntent.id == PaymentAttempt.payment_intent_id)
            .where(PaymentAttempt.payment_intent_id == intent_id)
            .where(PaymentIntent.tenant_id == tenant_id)
            .order_by(PaymentAttempt.created_at.desc())
            .limit(1)
        )

        return db.execute(stmt).scalar_one_or_none()

    # -------------------------------------------------
    # Creation
    # -------------------------------------------------

    @staticmethod
    def create(
        db: Session,
        *,
        attempt: PaymentAttempt,
    ) -> PaymentAttempt:

        db.add(attempt)
        return attempt

    # -------------------------------------------------
    # Mutations (no semantics)
    # -------------------------------------------------

    @staticmethod
    def set_status(
        *,
        attempt: PaymentAttempt,
        status: PaymentAttemptStatus,
    ) -> None:
        attempt.status = status

    @staticmethod
    def set_completed_at(
        *,
        attempt: PaymentAttempt,
        completed_at: Optional[datetime],
    ) -> None:
        attempt.completed_at = completed_at

    @staticmethod
    def set_gateway_reference(
        *,
        attempt: PaymentAttempt,
        reference: Optional[str],
    ) -> None:
        attempt.gateway_reference = reference

    @staticmethod
    def set_provider_reference(
        *,
        attempt: PaymentAttempt,
        reference: Optional[str],
    ) -> None:
        attempt.provider_reference = reference

    # -------------------------------------------------
    # Aggregates
    # -------------------------------------------------

    @staticmethod
    def sum_paid_for_intent(
        db: Session,
        *,
        tenant_id: int,
        intent_id: int,
    ) -> Decimal:

        stmt = (
            select(func.coalesce(func.sum(PaymentAttempt.amount), 0))
            .join(PaymentIntent, PaymentIntent.id == PaymentAttempt.payment_intent_id)
            .where(PaymentAttempt.payment_intent_id == intent_id)
            .where(PaymentAttempt.status == PaymentAttemptStatus.paid)
            .where(PaymentIntent.tenant_id == tenant_id)
        )

        result = db.execute(stmt).scalar_one()
        return Decimal(result)