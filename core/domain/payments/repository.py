from typing import Optional, List
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from core.domain.payments.models import (
    PaymentIntent,
    PaymentIntentStatus,
    PaymentAttempt,
    PaymentAttemptStatus,
)


# =========================================================
# PAYMENT INTENT REPOSITORY (PRIMARY AUTHORITY)
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
    def get_by_payable(
        db: Session,
        *,
        tenant_id: int,
        payable_type: str,
        payable_id: int,
    ) -> Optional[PaymentIntent]:

        stmt = (
            select(PaymentIntent)
            .where(PaymentIntent.tenant_id == tenant_id)
            .where(PaymentIntent.payable_type == payable_type)
            .where(PaymentIntent.payable_id == payable_id)
            .order_by(PaymentIntent.id.desc())
            .limit(1)
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
    @staticmethod
    def list_recent(db: Session, tenant_id: int, branch_id: int, limit: int = 50):
        """
        Return recent payment intents for dashboard.
        """

        return (
            db.query(PaymentIntent)
            .filter(
                PaymentIntent.tenant_id == tenant_id,
                PaymentIntent.branch_id == branch_id,
            )
            .order_by(PaymentIntent.created_at.desc())
            .limit(limit)
            .all()
        )
    
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
    def get_by_client_reference(
        db: Session,
        *,
        client_reference: str,
    ) -> Optional[PaymentAttempt]:

        stmt = (
            select(PaymentAttempt)
            .where(PaymentAttempt.client_reference == client_reference)
            .order_by(PaymentAttempt.id.desc())
            .limit(1)
        )
        return db.execute(stmt).scalar_one_or_none()

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