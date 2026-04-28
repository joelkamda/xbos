from fastapi import Request
from sqlalchemy.orm import Session

from core.domain.orders.service import OrderService
from core.domain.orders.repository import OrderRepository


class OrdersController:

    # =====================================================
    # CREATE ORDER
    # =====================================================

    async def create_order(self, request: Request, payload: dict, db: Session):
        ctx = request.state.user

        return OrderService.create_order(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            payload=payload,
        )

    # =====================================================
    # LIST PENDING ORDERS
    # =====================================================

    async def list_orders(self, request: Request, db: Session):
        ctx = request.state.user

        return OrderRepository.list_pending(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
        )

    # =====================================================
    # 🔥 GET SINGLE ORDER (CRITICAL FOR PAYMENT FLOW)
    # =====================================================

    async def get_order(self, request: Request, order_id: int, db: Session):

        ctx = getattr(request.state, "user", None)

        order = OrderRepository.get_by_id(db, order_id)

        if not order:
            return {"error": "Order not found"}

        # 🔐 Optional auth check (safe)
        if ctx:
            if order.tenant_id != ctx.get("tenant_id"):
                return {"error": "Unauthorized"}

        return {
            "id": order.id,
            "status": order.status,
            "subtotal": float(order.subtotal or 0),
            "total": float(order.total or 0),
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "items": [
                {
                    "atomic_unit_id": i.atomic_unit_id,
                    "name_snapshot": i.name_snapshot,
                    "unit_price": float(i.unit_price or 0),
                    "quantity": i.quantity,
                    "line_total": float(i.line_total or 0),
                }
                for i in (order.items or [])
            ],
        }