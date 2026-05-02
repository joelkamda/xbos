from decimal import Decimal
from typing import Dict, Any, List
from datetime import datetime

from sqlalchemy.orm import Session

from core.domain.orders.models import Order, OrderItem
from core.domain.catalog.repository import AtomicUnitRepository


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


class OrderService:

    # =====================================================
    # CREATE ORDER
    # =====================================================

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
        # ATTACH ITEMS VIA RELATIONSHIP
        # =================================================

        order.items = order_items

        # =================================================
        # SINGLE TRANSACTION
        # =================================================

        db.add(order)
        db.commit()
        db.refresh(order)

        return order

    # =====================================================
    # UPDATE PENDING ORDER
    # =====================================================

    @staticmethod
    def update_order(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        order_id: int,
        payload: Dict[str, Any],
    ) -> Order:
        """
        Updates an existing pending order.

        Used by:
        PendingOrdersScreen / PaymentScreen
            → Edit
            → SalesAndCartScreen edit mode
            → Save Order

        Important invariant:
        - This updates the existing order.
        - It must NOT create a new order.
        - Only pending/unpaid orders may be edited.
        """

        order = (
            db.query(Order)
            .filter(
                Order.id == order_id,
                Order.tenant_id == tenant_id,
                Order.branch_id == branch_id,
            )
            .first()
        )

        if not order:
            raise ValueError("Order not found")

        if str(order.status) != "pending_payment":
            raise ValueError("Only pending orders can be edited")

        items_payload = payload.get("items")

        if not items_payload or not isinstance(items_payload, list):
            raise ValueError("Order must contain items")

        # =================================================
        # BUILD REPLACEMENT ITEMS
        # Source of truth remains catalog.
        # Frontend snapshots are accepted as hints only.
        # =================================================

        replacement_items: List[OrderItem] = []
        subtotal = Decimal("0")

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

            qty = int(item.get("quantity", 0))

            if qty <= 0:
                raise ValueError("Quantity must be greater than zero")

            # Keep catalog as source of truth for price/name.
            price = _d(atomic.unit_price)
            line_total = price * qty

            replacement_items.append(
                OrderItem(
                    order_id=order.id,
                    atomic_unit_id=atomic.id,
                    name_snapshot=atomic.name,
                    unit_price=price,
                    quantity=qty,
                    line_total=line_total,
                )
            )

            subtotal += line_total

        # =================================================
        # REPLACE OLD ITEMS
        # =================================================

        db.query(OrderItem).filter(
            OrderItem.order_id == order.id
        ).delete(synchronize_session=False)

        db.flush()

        for item in replacement_items:
            db.add(item)

        # =================================================
        # UPDATE TOTALS
        # =================================================

        order.subtotal = subtotal
        order.total = subtotal

        if hasattr(order, "updated_at"):
            order.updated_at = datetime.utcnow()

        db.add(order)
        db.commit()
        db.refresh(order)

        return order

    # =====================================================
    # CANCEL PENDING ORDER
    # =====================================================

    @staticmethod
    def cancel_order(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        order_id: int,
    ) -> Order:
        """
        Cancels/voids a pending order.

        Important:
        - This is not a hard delete.
        - Paid/completed orders must not be cancelled here.
        """

        order = (
            db.query(Order)
            .filter(
                Order.id == order_id,
                Order.tenant_id == tenant_id,
                Order.branch_id == branch_id,
            )
            .first()
        )

        if not order:
            raise ValueError("Order not found")

        if str(order.status) != "pending_payment":
            raise ValueError("Only pending orders can be cancelled")

        order.status = "cancelled"

        if hasattr(order, "cancelled_at"):
            order.cancelled_at = datetime.utcnow()

        if hasattr(order, "updated_at"):
            order.updated_at = datetime.utcnow()

        db.add(order)
        db.commit()
        db.refresh(order)

        return order