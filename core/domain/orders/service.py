from decimal import Decimal
from typing import Dict, Any, List
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload

from core.domain.orders.models import Order, OrderItem, OrderItemModifier
from core.domain.catalog.repository import AtomicUnitRepository
from core.domain.inventory.service import InventoryService


def _utc_now_naive() -> datetime:
    """
    Canonical order timestamp for the current orders table.

    Important:
    - orders.created_at / orders.paid_at are currently timestamp WITHOUT time zone.
    - Some optional order fields such as updated_at/cancelled_at/fulfilled_at may
      follow the same model/table convention.
    - So we store UTC wall-clock as naive for now.

    Long-term preferred migration:
    - Convert order timestamps to timestamptz.
    - Then use datetime.now(timezone.utc) directly.
    """

    return datetime.now(timezone.utc).replace(tzinfo=None)


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


def _clean_modifier_type(value) -> str:
    clean = str(value or "side").strip().lower()
    return clean or "side"


def _clean_modifier_name(value) -> str:
    return str(value or "").strip()


def _clean_modifier_quantity(value) -> int:
    try:
        qty = int(value or 1)
    except Exception:
        qty = 1

    return max(qty, 1)


FULFILLMENT_MODES = {"DINE_IN", "TAKEAWAY", "DELIVERY"}


def _normalize_fulfillment_mode(
    value,
    *,
    allow_unspecified: bool = False,
) -> str | None:
    if value is None:
        return None if allow_unspecified else "DINE_IN"

    clean = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")

    aliases = {
        "DINEIN": "DINE_IN",
        "DINE_IN": "DINE_IN",
        "TAKEOUT": "TAKEAWAY",
        "TAKE_OUT": "TAKEAWAY",
        "TAKE_AWAY": "TAKEAWAY",
        "TAKEAWAY": "TAKEAWAY",
        "DELIVERY": "DELIVERY",
        "UNSPECIFIED": None,
        "UNKNOWN": None,
    }

    normalized = aliases.get(clean, clean)

    if normalized is None:
        if allow_unspecified:
            return None
        return "DINE_IN"

    if normalized not in FULFILLMENT_MODES:
        raise ValueError(
            "fulfillment_mode must be DINE_IN, TAKEAWAY, or DELIVERY"
        )

    return normalized


def _build_modifiers_for_item(item_payload: Dict[str, Any]) -> List[OrderItemModifier]:
    """
    Build modifier child rows for an order item.

    V1 use case:
    - Free side dish attached to a food item.

    Payload shape:
    modifiers: [
        {
            "modifier_type": "side",
            "name_snapshot": "Gari",
            "price_delta": 0,
            "quantity": 1
        }
    ]

    Notes:
    - Main item price remains catalog-controlled.
    - Modifier price_delta is supported for future paid extras.
    - Empty modifier names are ignored.
    """

    modifiers_payload = item_payload.get("modifiers") or []

    if not isinstance(modifiers_payload, list):
        return []

    modifier_rows: List[OrderItemModifier] = []

    for modifier in modifiers_payload:
        if not isinstance(modifier, dict):
            continue

        modifier_name = _clean_modifier_name(
            modifier.get("name_snapshot") or modifier.get("name")
        )

        if not modifier_name:
            continue

        modifier_rows.append(
            OrderItemModifier(
                modifier_type=_clean_modifier_type(
                    modifier.get("modifier_type") or modifier.get("type")
                ),
                name_snapshot=modifier_name,
                price_delta=_d(modifier.get("price_delta", 0)),
                quantity=_clean_modifier_quantity(modifier.get("quantity", 1)),
            )
        )

    return modifier_rows


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
        created_by_user_id: int | None,
        payload: Dict[str, Any],
    ) -> Order:

        items_payload = payload.get("items")

        if not items_payload or not isinstance(items_payload, list):
            raise ValueError("Order must contain items")

        order_items: List[OrderItem] = []
        subtotal = Decimal("0")

        # =================================================
        # BUILD ITEMS — SOURCE OF TRUTH = CATALOG
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

            if hasattr(order_item, "fulfillment_status"):
                order_item.fulfillment_status = "waiting"

            order_item.modifiers = _build_modifiers_for_item(item)

            order_items.append(order_item)
            subtotal += line_total

        # =================================================
        # CREATE ORDER
        # =================================================

        fulfillment_mode = _normalize_fulfillment_mode(
            payload.get("fulfillment_mode", payload.get("order_type"))
        )

        order = Order(
            tenant_id=tenant_id,
            branch_id=branch_id,
            created_by_user_id=created_by_user_id,
            status="pending_payment",
            fulfillment_mode=fulfillment_mode,
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

        Important:
        - This updates the existing order.
        - It must NOT create a new order.
        - Only pending/unpaid orders may be edited.
        - Original created_by_user_id is preserved for commission tracking.
        """

        order = (
            db.query(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.modifiers))
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

            if hasattr(replacement_item, "fulfillment_status"):
                replacement_item.fulfillment_status = "waiting"

            replacement_item.modifiers = _build_modifiers_for_item(item)

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
        # - preserve order creator
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

            if "fulfillment_mode" in payload or "order_type" in payload:
                raw_mode = (
                    payload.get("fulfillment_mode")
                    if "fulfillment_mode" in payload
                    else payload.get("order_type")
                )
                order.fulfillment_mode = _normalize_fulfillment_mode(
                    raw_mode,
                    allow_unspecified=True,
                )

            if hasattr(order, "updated_at"):
                order.updated_at = _utc_now_naive()

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

        Valid statuses:
        - waiting
        - preparing
        - in_progress
        - ready
        - served
        - cancelled
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
            .options(selectinload(Order.items).selectinload(OrderItem.modifiers))
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

        if hasattr(order_item, "fulfillment_status"):
            order_item.fulfillment_status = clean_status
        else:
            raise ValueError(
                "OrderItem.fulfillment_status column is missing. "
                "Run migration and update model before using kitchen status."
            )

        now = _utc_now_naive()

        if clean_status == "ready":
            if hasattr(order_item, "fulfilled_at"):
                order_item.fulfilled_at = now

            if hasattr(order_item, "fulfilled_by_user_id"):
                order_item.fulfilled_by_user_id = user_id

        elif clean_status in {"waiting", "preparing", "in_progress"}:
            if hasattr(order_item, "fulfilled_at"):
                order_item.fulfilled_at = None

            if hasattr(order_item, "fulfilled_by_user_id"):
                order_item.fulfilled_by_user_id = None

        if hasattr(order, "updated_at"):
            order.updated_at = now

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
        - Original created_by_user_id remains preserved for audit.
        """

        order = (
            db.query(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.modifiers))
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

            now = _utc_now_naive()

            order.status = "cancelled"

            if hasattr(order, "cancelled_at"):
                order.cancelled_at = now

            if hasattr(order, "updated_at"):
                order.updated_at = now

            db.add(order)
            db.commit()
            db.refresh(order)

            return order

        except Exception:
            db.rollback()
            raise