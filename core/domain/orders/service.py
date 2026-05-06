from decimal import Decimal
from typing import Dict, Any, List
from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from core.domain.orders.models import Order, OrderItem
from core.domain.catalog.repository import AtomicUnitRepository
from core.domain.inventory.service import InventoryService


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

            order_item = OrderItem(
                atomic_unit_id=atomic.id,
                name_snapshot=atomic.name,
                unit_price=price,
                quantity=qty,
                line_total=line_total,
            )

            # If fulfillment columns exist on the model, initialize safely.
            if hasattr(order_item, "fulfillment_status"):
                order_item.fulfillment_status = "waiting"

            order_items.append(order_item)

            subtotal += line_total

        # =================================================
        # CREATE ORDER
        # =================================================

        order = Order(
            tenant_id=tenant_id,
            branch_id=branch_id,
            subtotal=subtotal,
            total=subtotal,
        )

        order.items = order_items

        # =================================================
        # SINGLE TRANSACTION:
        # - create order
        # - flush to get order.id
        # - reserve inventory immediately
        # - commit together
        #
        # If stock reservation fails, order creation rolls back.
        # =================================================

        try:
            db.add(order)
            db.flush()

            InventoryService.reserve_order_inventory(
                db,
                order=order,
            )

            db.commit()
            db.refresh(order)

            return order

        except Exception:
            db.rollback()
            raise

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

        Inventory behavior:
        - Old order quantities are compared to new quantities.
        - Only the reservation delta is applied.
        - Increasing quantity reserves more stock.
        - Reducing/removing quantity releases stock.
        """

        order = (
            db.query(Order)
            .options(selectinload(Order.items))
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
        # SNAPSHOT OLD ITEMS BEFORE REPLACEMENT
        # =================================================

        old_items_snapshot = [
            {
                "atomic_unit_id": item.atomic_unit_id,
                "quantity": item.quantity,
            }
            for item in (order.items or [])
        ]

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

            price = _d(atomic.unit_price)
            line_total = price * qty

            replacement_item = OrderItem(
                order_id=order.id,
                atomic_unit_id=atomic.id,
                name_snapshot=atomic.name,
                unit_price=price,
                quantity=qty,
                line_total=line_total,
            )

            # New/replaced order lines start as waiting if the column exists.
            if hasattr(replacement_item, "fulfillment_status"):
                replacement_item.fulfillment_status = "waiting"

            replacement_items.append(replacement_item)

            subtotal += line_total

        new_items_snapshot = [
            {
                "atomic_unit_id": item.atomic_unit_id,
                "quantity": item.quantity,
            }
            for item in replacement_items
        ]

        # =================================================
        # SINGLE TRANSACTION:
        # - adjust inventory reservation delta
        # - replace old items
        # - update totals
        # - commit together
        #
        # If extra stock reservation fails, the order edit rolls back.
        # =================================================

        try:
            InventoryService.adjust_order_reservation(
                db,
                order=order,
                old_items=old_items_snapshot,
                new_items=new_items_snapshot,
            )

            db.query(OrderItem).filter(
                OrderItem.order_id == order.id
            ).delete(synchronize_session=False)

            db.flush()

            for item in replacement_items:
                db.add(item)

            order.subtotal = subtotal
            order.total = subtotal

            if hasattr(order, "updated_at"):
                order.updated_at = datetime.utcnow()

            db.add(order)
            db.commit()
            db.refresh(order)

            return order

        except Exception:
            db.rollback()
            raise

    # =====================================================
    # UPDATE ITEM FULFILLMENT STATUS
    # =====================================================

    @staticmethod
    def update_item_fulfillment_status(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        order_id: int,
        order_item_id: int,
        status: str,
        user_id: int | None = None,
    ) -> OrderItem:
        """
        Updates readiness/prep status for one order item.

        Intended for kitchen workflow:
        PATCH /kernel/orders/{order_id}/items/{order_item_id}/fulfillment-status

        Valid statuses:
        - waiting
        - preparing
        - ready
        - served
        - cancelled

        Important:
        - This updates one exact order item line.
        - It uses order_item_id, not atomic_unit_id.
        - This requires fulfillment columns to exist on OrderItem model/table
          for persistence:
            fulfillment_status
            fulfilled_at
            fulfilled_by_user_id
        """

        clean_status = str(status or "").strip().lower()

        allowed_statuses = {
            "waiting",
            "preparing",
            "in_progress",
            "ready",
            "served",
            "cancelled",
        }

        if clean_status not in allowed_statuses:
            raise ValueError("Invalid fulfillment status")

        order = (
            db.query(Order)
            .options(selectinload(Order.items))
            .filter(
                Order.id == order_id,
                Order.tenant_id == tenant_id,
                Order.branch_id == branch_id,
            )
            .first()
        )

        if not order:
            raise ValueError("Order not found")

        if str(order.status) not in {
            "pending_payment",
            "ready",
            "preparing",
            "in_progress",
        }:
            raise ValueError("Order is not editable for fulfillment")

        order_item = None

        for item in order.items or []:
            if int(item.id) == int(order_item_id):
                order_item = item
                break

        if not order_item:
            raise ValueError("Order item not found")

        # -------------------------------------------------
        # Persist item status if model/table supports it
        # -------------------------------------------------

        if hasattr(order_item, "fulfillment_status"):
            order_item.fulfillment_status = clean_status
        else:
            raise ValueError(
                "OrderItem.fulfillment_status column is missing. "
                "Run migration and update model before using kitchen status."
            )

        if clean_status == "ready":
            if hasattr(order_item, "fulfilled_at"):
                order_item.fulfilled_at = datetime.utcnow()

            if hasattr(order_item, "fulfilled_by_user_id"):
                order_item.fulfilled_by_user_id = user_id

        elif clean_status in {"waiting", "preparing", "in_progress"}:
            if hasattr(order_item, "fulfilled_at"):
                order_item.fulfilled_at = None

            if hasattr(order_item, "fulfilled_by_user_id"):
                order_item.fulfilled_by_user_id = None

        # -------------------------------------------------
        # Optional order-level rollup
        # -------------------------------------------------
        # If every fulfillment-capable item is ready later,
        # the controller/frontend can show order as ready.
        # For now, do not mark the whole order paid/complete here.
        # -------------------------------------------------

        if hasattr(order, "updated_at"):
            order.updated_at = datetime.utcnow()

        try:
            db.add(order_item)
            db.add(order)
            db.commit()
            db.refresh(order_item)

            return order_item

        except Exception:
            db.rollback()
            raise

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

        Inventory behavior:
        - Releases active reservation for the order.
        - Then marks order cancelled.
        - Happens in one transaction.
        """

        order = (
            db.query(Order)
            .options(selectinload(Order.items))
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

        try:
            InventoryService.release_order_reservation(
                db,
                order=order,
            )

            order.status = "cancelled"

            if hasattr(order, "cancelled_at"):
                order.cancelled_at = datetime.utcnow()

            if hasattr(order, "updated_at"):
                order.updated_at = datetime.utcnow()

            db.add(order)
            db.commit()
            db.refresh(order)

            return order

        except Exception:
            db.rollback()
            raise