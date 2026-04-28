from sqlalchemy.orm import Session, joinedload
from core.domain.orders.models import Order


class OrderRepository:

    @staticmethod
    def create(db: Session, order: Order):
        db.add(order)

    @staticmethod
    def get_by_id(db: Session, order_id: int):
        return (
            db.query(Order)
            .options(joinedload(Order.items))   # ✅ FIXED
            .filter(Order.id == order_id)
            .first()
        )

    @staticmethod
    def list_pending(db: Session, tenant_id: int, branch_id: int):
        return (
            db.query(Order)
            .options(joinedload(Order.items))   # ✅ CRITICAL FIX
            .filter(
                Order.tenant_id == tenant_id,
                Order.branch_id == branch_id,
                Order.status == "pending_payment",   # ✅ FIXED
            )
            .order_by(Order.created_at.desc())
            .all()
        )

    @staticmethod
    def mark_paid(order: Order):
        from datetime import datetime

        order.status = "paid"   # ✅ FIXED
        order.paid_at = datetime.utcnow()