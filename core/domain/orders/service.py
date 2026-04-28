from decimal import Decimal
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from core.domain.orders.models import Order, OrderItem
from core.domain.catalog.repository import AtomicUnitRepository


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


class OrderService:

    @staticmethod
    def create_order(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        payload: Dict[str, Any],
    ) -> Order:

        items_payload = payload.get("items")

        if not items_payload or not isinstance(items_payload, list):
            raise ValueError("Order must contain items")

        order_items: List[OrderItem] = []
        subtotal = Decimal("0")

        # =================================================
        # BUILD ITEMS (SOURCE OF TRUTH = CATALOG)
        # =================================================

        for item in items_payload:

            atomic_unit_id = item.get("atomic_unit_id")

            if not atomic_unit_id:
                raise ValueError("Missing atomic_unit_id")

            atomic = AtomicUnitRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                atomic_unit_id=atomic_unit_id,
            )

            if not atomic:
                raise ValueError(f"Invalid atomic unit: {atomic_unit_id}")

            qty = int(item.get("quantity", 1))

            if qty <= 0:
                raise ValueError("Quantity must be greater than zero")

            price = _d(atomic.unit_price)
            line_total = price * qty

            order_items.append(
                OrderItem(
                    atomic_unit_id=atomic.id,
                    name_snapshot=atomic.name,
                    unit_price=price,
                    quantity=qty,
                    line_total=line_total,
                )
            )

            subtotal += line_total

        # =================================================
        # CREATE ORDER (LET DB HANDLE STATUS DEFAULT)
        # =================================================

        order = Order(
            tenant_id=tenant_id,
            branch_id=branch_id,
            subtotal=subtotal,
            total=subtotal,
        )

        # =================================================
        # ATTACH ITEMS VIA RELATIONSHIP (CRITICAL FIX)
        # =================================================

        order.items = order_items

        # =================================================
        # SINGLE TRANSACTION
        # =================================================

        db.add(order)
        db.commit()
        db.refresh(order)

        return order