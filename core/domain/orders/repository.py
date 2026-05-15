from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from core.domain.orders.models import Order


def _utc_now_naive() -> datetime:
    """
    Canonical order timestamp for current orders table.

    Important:
    - orders.created_at / orders.paid_at are currently timestamp WITHOUT time zone.
    - So we store UTC wall-clock as naive for now.
    - Long-term preferred migration: convert order timestamps to timestamptz,
      then use datetime.now(timezone.utc) directly.
    """

    return datetime.now(timezone.utc).replace(tzinfo=None)


class OrderRepository:

    @staticmethod
    def create(db: Session, order: Order):
        db.add(order)

    @staticmethod
    def get_by_id(db: Session, order_id: int):
        return (
            db.query(Order)
            .options(joinedload(Order.items))
            .filter(Order.id == order_id)
            .first()
        )

    @staticmethod
    def list_pending(db: Session, tenant_id: int, branch_id: int):
        return (
            db.query(Order)
            .options(joinedload(Order.items))
            .filter(
                Order.tenant_id == tenant_id,
                Order.branch_id == branch_id,
                Order.status == "pending_payment",
            )
            .order_by(Order.created_at.desc())
            .all()
        )

    @staticmethod
    def mark_paid(order: Order):
        order.status = "paid"
        order.paid_at = _utc_now_naive()

    @staticmethod
    def mark_receivable(order: Order):
        """
        Move unpaid or partially paid order out of the cashier queue
        and into Accounts Receivable.
        """
        order.status = "receivable"