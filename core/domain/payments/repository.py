from typing import Optional, List
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from core.domain.payments.models import Payment, PaymentStatus, PaymentMethod
from core.domain.sales.models import Sale


class PaymentRepository:
    """
    Data-access layer for Payments.

    Responsibilities (LOCKED):
    - Persist Payment records
    - Fetch payments by sale or ID
    - Mutate persisted fields only
    - Enforce tenant isolation via Sale
    - NO business logic
    """

    # -------------------------------------------------
    # Core fetches
    # -------------------------------------------------

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        payment_id: int,
    ) -> Optional[Payment]:
        """
        Fetch a payment by ID (tenant-safe via Sale).
        """
        stmt = (
            select(Payment)
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.id == payment_id)
            .where(Sale.tenant_id == tenant_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_for_sale(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
    ) -> List[Payment]:
        """
        Fetch all payments associated with a sale.
        """
        stmt = (
            select(Payment)
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.sale_id == sale_id)
            .where(Sale.tenant_id == tenant_id)
            .order_by(Payment.created_at.asc())
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_latest_for_sale(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
    ) -> Optional[Payment]:
        """
        Fetch the most recent payment attempt for a sale.
        """
        stmt = (
            select(Payment)
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.sale_id == sale_id)
            .where(Sale.tenant_id == tenant_id)
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return db.execute(stmt).scalar_one_or_none()

    # -------------------------------------------------
    # Creation / persistence
    # -------------------------------------------------

    @staticmethod
    def create(
        db: Session,
        *,
        payment: Payment,
    ) -> Payment:
        """
        Persist a new Payment.
        """
        db.add(payment)
        return payment

    # -------------------------------------------------
    # Field mutations (NO semantics)
    # -------------------------------------------------

    @staticmethod
    def set_status(
        *,
        payment: Payment,
        status: PaymentStatus,
    ) -> None:
        """
        Set payment status.

        NOTE:
        - Valid transitions enforced by service layer
        """
        payment.status = status

    @staticmethod
    def set_reference(
        *,
        payment: Payment,
        reference: str | None,
    ) -> None:
        """
        Persist external gateway reference.
        """
        payment.reference = reference

    @staticmethod
    def set_completed_at(
        *,
        payment: Payment,
        completed_at: datetime | None,
    ) -> None:
        """
        Set completion timestamp.
        """
        payment.completed_at = completed_at

    # -------------------------------------------------
    # Aggregates (used by service layer)
    # -------------------------------------------------

    @staticmethod
    def sum_paid_for_sale(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
    ) -> float:
        """
        Sum all PAID payments for a sale.

        GUARANTEES:
        - Tenant-safe
        - Returns 0.0 if no successful payments
        - Used to determine sale settlement completeness
        """
        stmt = (
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.sale_id == sale_id)
            .where(Payment.status == PaymentStatus.paid)
            .where(Sale.tenant_id == tenant_id)
        )
        return float(db.execute(stmt).scalar_one())

    # -------------------------------------------------
    # Queries (admin / reconciliation)
    # -------------------------------------------------

    @staticmethod
    def list_by_status(
        db: Session,
        *,
        tenant_id: int,
        status: PaymentStatus,
        limit: int = 50,
    ) -> List[Payment]:
        """
        List payments by status (tenant-safe).
        """
        stmt = (
            select(Payment)
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.status == status)
            .where(Sale.tenant_id == tenant_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_by_method(
        db: Session,
        *,
        tenant_id: int,
        method: PaymentMethod,
        limit: int = 50,
    ) -> List[Payment]:
        """
        List payments by method (cash vs xafpay).
        """
        stmt = (
            select(Payment)
            .join(Sale, Sale.id == Payment.sale_id)
            .where(Payment.method == method)
            .where(Sale.tenant_id == tenant_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())
