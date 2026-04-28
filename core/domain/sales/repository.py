from typing import Optional, List
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select

from core.domain.sales.models import Sale, SaleItem, SaleStatus


class SaleRepository:
    """
    Data-access layer for Sales.

    Responsibilities (LOCKED):
    - Persist Sale and SaleItem records
    - Fetch sales by tenant / branch / status
    - Mutate persisted fields only
    - NO business logic
    - NO payment or treasury concerns
    """

    # -------------------------------------------------
    # Sale (header)
    # -------------------------------------------------

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        sale_id: int,
    ) -> Optional[Sale]:
        """
        Fetch a sale by ID within a tenant scope.
        """
        stmt = (
            select(Sale)
            .where(Sale.id == sale_id)
            .where(Sale.tenant_id == tenant_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create(
        db: Session,
        *,
        sale: Sale,
    ) -> Sale:
        """
        Persist a new Sale.
        """
        db.add(sale)
        return sale

    @staticmethod
    def update_status(
        *,
        sale: Sale,
        new_status: SaleStatus,
    ) -> None:
        """
        Update sale status.

        NOTE:
        - Status validity is enforced in service layer
        - This method mutates state only
        """
        sale.status = new_status

    @staticmethod
    def set_paid_at(
        *,
        sale: Sale,
        paid_at: datetime,
    ) -> None:
        """
        Set paid_at timestamp.

        NOTE:
        - Should be called once, on transition to PAID
        - Informational only; ledger is source of truth
        """
        sale.paid_at = paid_at

    # -------------------------------------------------
    # SaleItem (lines)
    # -------------------------------------------------

    @staticmethod
    def create_items(
        db: Session,
        *,
        items: List[SaleItem],
    ) -> None:
        """
        Persist SaleItem records.
        """
        db.add_all(items)

    # -------------------------------------------------
    # Queries
    # -------------------------------------------------

    @staticmethod
    def list_for_branch(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        limit: int = 50,
    ) -> List[Sale]:
        """
        List recent sales for a branch.
        """
        stmt = (
            select(Sale)
            .where(Sale.tenant_id == tenant_id)
            .where(Sale.branch_id == branch_id)
            .order_by(Sale.created_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_by_status(
        db: Session,
        *,
        tenant_id: int,
        status: SaleStatus,
        limit: int = 50,
    ) -> List[Sale]:
        """
        List sales by status.
        """
        stmt = (
            select(Sale)
            .where(Sale.tenant_id == tenant_id)
            .where(Sale.status == status)
            .order_by(Sale.created_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_by_order_id(
        db: Session,
        *,
        tenant_id: int,
        order_id: int,
    ) -> Optional[Sale]:
        """
        Resolve sale from originating order.
        """
        stmt = (
            select(Sale)
            .where(Sale.tenant_id == tenant_id)
            .where(Sale.order_id == order_id)
        )
        return db.execute(stmt).scalar_one_or_none()
