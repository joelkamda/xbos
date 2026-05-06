from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.domain.inventory.models import (
    InventoryItem,
    InventoryMovement,
)
from core.domain.inventory.repository import InventoryRepository
from core.domain.sales.models import Sale
from core.domain.orders.models import Order
from core.domain.taxonomy.models import (
    AtomicUnit,
    AtomicUnitTaxonomy,
    TaxonomyNode,
)
from core.domain.inventory.taxonomy_profile import resolve_inventory_profile


# ============================================================
# CONSTANTS
# ============================================================

MOVEMENT_STOCK_IN = "stock_in"
MOVEMENT_ADJUSTMENT = "adjustment"
MOVEMENT_SALE = "sale"

# Temporary reservation lifecycle
MOVEMENT_SALE_HOLD = "sale_hold"
MOVEMENT_SALE_HOLD_ADJUST = "sale_hold_adjust"
MOVEMENT_SALE_HOLD_RELEASE = "sale_hold_release"
MOVEMENT_SALE_COMMIT = "sale_commit"

# Loss / operational events
MOVEMENT_WASTE = "waste"
MOVEMENT_LOSS = "loss"
MOVEMENT_SPOILAGE = "spoilage"
MOVEMENT_STOCK_COUNT = "stock_count"

VALID_MOVEMENT_TYPES = {
    MOVEMENT_STOCK_IN,
    MOVEMENT_ADJUSTMENT,
    MOVEMENT_SALE,
    MOVEMENT_SALE_HOLD,
    MOVEMENT_SALE_HOLD_ADJUST,
    MOVEMENT_SALE_HOLD_RELEASE,
    MOVEMENT_SALE_COMMIT,
    MOVEMENT_WASTE,
    MOVEMENT_LOSS,
    MOVEMENT_SPOILAGE,
    MOVEMENT_STOCK_COUNT,
}

SOURCE_SYSTEM = "system"
SOURCE_MANUAL = "manual"
SOURCE_SALES = "sales"
SOURCE_INVENTORY = "inventory"
SOURCE_STOCK_COUNT = "stock_count"


# ============================================================
# SMALL HELPERS
# ============================================================

def _int(value: Any, fallback: int = 0) -> int:
    try:
        if value is None:
            return fallback
        return int(value)
    except Exception:
        return fallback


def _decimal(value: Any) -> Decimal:
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _atomic_meta(unit: Optional[AtomicUnit]) -> Dict[str, Any]:
    if not unit or not unit.meta:
        return {}

    if isinstance(unit.meta, dict):
        return unit.meta

    return {}


def _is_truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    text = str(value).strip().lower()

    if text in {"true", "1", "yes", "y", "on"}:
        return True

    if text in {"false", "0", "no", "n", "off"}:
        return False

    return default


def _normalize_source(source: Optional[str], fallback: str = SOURCE_SYSTEM) -> str:
    value = str(source or fallback).strip().lower()
    return value or fallback


def _movement_type(value: str) -> str:
    movement_type = str(value or "").strip().lower()

    if movement_type not in VALID_MOVEMENT_TYPES:
        raise ValueError(f"Invalid inventory movement_type: {value}")

    return movement_type


def _cost_price_from_meta(meta: Dict[str, Any]) -> Decimal:
    """
    Cost lookup priority.

    Canonical going forward:
      cost_price

    Compatibility:
      buying_price, unit_cost, purchase_price
    """

    for key in ("cost_price", "buying_price", "unit_cost", "purchase_price"):
        cost = _decimal(meta.get(key))
        if cost > 0:
            return cost

    return Decimal("0")


def _item_qty_map(items: Any) -> Dict[int, int]:
    """
    Converts OrderItem/SaleItem-like rows into:
      { atomic_unit_id: total_quantity }

    Works with:
    - SQLAlchemy item objects
    - dict payload items
    """

    result: Dict[int, int] = {}

    for item in items or []:
        if isinstance(item, dict):
            atomic_unit_id = _int(item.get("atomic_unit_id"))
            quantity = _int(item.get("quantity"))
        else:
            atomic_unit_id = _int(getattr(item, "atomic_unit_id", None))
            quantity = _int(getattr(item, "quantity", None))

        if not atomic_unit_id or quantity <= 0:
            continue

        result[atomic_unit_id] = result.get(atomic_unit_id, 0) + quantity

    return result


# ============================================================
# INVENTORY SERVICE
# ============================================================

class InventoryService:
    """
    Domain service for inventory.

    Core invariants:
    - InventoryMovement is the source of truth.
    - InventoryItem.quantity_on_hand is only a cached balance.
    - Quantity cache changes only inside the same transaction that creates
      an InventoryMovement.
    - No frontend should directly mutate stock.

    Current stock lifecycle:
    1. Pending Order created:
       reserve_order_inventory()
       -> sale_hold movements reduce available stock immediately.

    2. Pending Order edited:
       adjust_order_reservation()
       -> sale_hold_adjust movements apply only the delta.

    3. Pending Order cancelled:
       release_order_reservation()
       -> sale_hold_release movements restore withheld stock.

    4. Payment confirmed / sale paid:
       commit_order_reservation()
       -> sale_commit zero-delta markers confirm that the hold is final.
       -> no second deduction.
    """

    # ========================================================
    # Atomic unit / stock-tracking helpers
    # ========================================================

    @staticmethod
    def get_atomic_unit(
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: int,
    ) -> Optional[AtomicUnit]:
        return (
            db.query(AtomicUnit)
            .filter(
                AtomicUnit.tenant_id == tenant_id,
                AtomicUnit.id == atomic_unit_id,
            )
            .first()
        )

    @staticmethod
    def is_stock_tracked(unit: Optional[AtomicUnit]) -> bool:
        """
        Backward-compatible meta-based stock tracking check.

        Preferred new check:
          get_inventory_profile() + is_stock_tracked_profile()
        """

        if not unit:
            return True

        meta = _atomic_meta(unit)

        if "track_stock" in meta:
            return _is_truthy(meta.get("track_stock"), default=True)

        if "is_stock_tracked" in meta:
            return _is_truthy(meta.get("is_stock_tracked"), default=True)

        return True

    @staticmethod
    def get_cost_price(unit: Optional[AtomicUnit]) -> Decimal:
        return _cost_price_from_meta(_atomic_meta(unit))

    @staticmethod
    def get_inventory_profile(
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: int,
    ) -> Dict[str, Any]:
        """
        Resolve taxonomy-aware inventory policy for an atomic unit.

        Preferred way to decide:
        - stock_tracked
        - inventory_family
        - allow_negative_stock
        - disable_when_out
        - cost_mode
        """

        return resolve_inventory_profile(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

    @staticmethod
    def is_stock_tracked_profile(profile: Optional[Dict[str, Any]]) -> bool:
        """
        Preferred taxonomy-aware stock tracking check.
        """

        if not profile:
            return False

        return bool(profile.get("stock_tracked"))

    @staticmethod
    def allow_negative_from_profile(
        profile: Optional[Dict[str, Any]],
        *,
        allow_negative_food: bool = True,
        allow_negative_other: bool = False,
    ) -> bool:
        """
        Preferred taxonomy-aware negative stock policy.

        Resolver encodes WND V1 behavior:
        - kitchen: soft-negative allowed
        - bar/drinks: no negative
        - other: usually no negative
        """

        if not profile:
            return allow_negative_other

        family = str(profile.get("inventory_family") or "").lower()

        if "allow_negative_stock" in profile:
            return bool(profile.get("allow_negative_stock"))

        if family == "kitchen":
            return allow_negative_food

        if family == "bar":
            return False

        return allow_negative_other

    # ========================================================
    # Core item / movement helpers
    # ========================================================

    @staticmethod
    def get_or_create_item(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
        reorder_level: Optional[int] = None,
    ) -> InventoryItem:
        inventory_item = InventoryRepository.get_item(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
        )

        if inventory_item:
            if reorder_level is not None:
                inventory_item.reorder_level = _int(reorder_level)
            return inventory_item

        inventory_item = InventoryItem(
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
            quantity_on_hand=0,
            reorder_level=_int(reorder_level) if reorder_level is not None else None,
            created_at=datetime.utcnow(),
        )

        InventoryRepository.create_item(
            db,
            inventory_item=inventory_item,
        )

        db.flush()

        return inventory_item

    @staticmethod
    def _reference_movements(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        reference_type: str,
        reference_id: int,
        movement_type: Optional[str] = None,
        atomic_unit_id: Optional[int] = None,
    ) -> List[InventoryMovement]:
        q = (
            db.query(InventoryMovement)
            .filter(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.branch_id == branch_id,
                InventoryMovement.reference_type == reference_type,
                InventoryMovement.reference_id == reference_id,
            )
        )

        if movement_type:
            q = q.filter(InventoryMovement.movement_type == movement_type)

        if atomic_unit_id is not None:
            q = q.filter(InventoryMovement.atomic_unit_id == atomic_unit_id)

        return q.order_by(
            InventoryMovement.created_at.asc(),
            InventoryMovement.id.asc(),
        ).all()

    @staticmethod
    def has_reference_movement(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        reference_type: str,
        reference_id: int,
        movement_type: str,
        atomic_unit_id: Optional[int] = None,
    ) -> bool:
        rows = InventoryService._reference_movements(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            reference_type=reference_type,
            reference_id=reference_id,
            movement_type=_movement_type(movement_type),
            atomic_unit_id=atomic_unit_id,
        )

        return len(rows) > 0

    @staticmethod
    def _active_reserved_qty_by_atomic(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        reference_type: str,
        reference_id: int,
    ) -> Dict[int, int]:
        """
        Computes active withheld quantity for a reference.

        Movement convention:
        - sale_hold / sale_hold_adjust negative deltas reduce stock.
        - sale_hold_adjust positive deltas release partial stock.
        - sale_hold_release positive deltas release stock.

        Active reserved quantity is represented as a positive number.
        """

        rows = InventoryService._reference_movements(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            reference_type=reference_type,
            reference_id=reference_id,
        )

        tracked_types = {
            MOVEMENT_SALE_HOLD,
            MOVEMENT_SALE_HOLD_ADJUST,
            MOVEMENT_SALE_HOLD_RELEASE,
        }

        net_by_atomic: Dict[int, int] = {}

        for row in rows:
            if row.movement_type not in tracked_types:
                continue

            atomic_unit_id = _int(row.atomic_unit_id)
            if not atomic_unit_id:
                continue

            net_by_atomic[atomic_unit_id] = (
                net_by_atomic.get(atomic_unit_id, 0)
                + _int(row.quantity_delta)
            )

        active: Dict[int, int] = {}

        for atomic_unit_id, net_delta in net_by_atomic.items():
            if net_delta < 0:
                active[atomic_unit_id] = abs(net_delta)

        return active

    @staticmethod
    def _apply_quantity_movement(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
        quantity_delta: int,
        movement_type: str,
        source: str = SOURCE_SYSTEM,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        reorder_level: Optional[int] = None,
        allow_negative: bool = False,
    ) -> InventoryMovement:
        """
        Single low-level writer.

        Creates one InventoryMovement and updates quantity_on_hand in the same
        transaction. Does not commit; caller controls commit.
        """

        movement_type = _movement_type(movement_type)
        quantity_delta = _int(quantity_delta)

        # Allow zero only for explicit sale_commit audit markers.
        if quantity_delta == 0 and movement_type != MOVEMENT_SALE_COMMIT:
            raise ValueError("quantity_delta cannot be zero")

        inventory_item = InventoryService.get_or_create_item(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
            reorder_level=reorder_level,
        )

        current_quantity = _int(inventory_item.quantity_on_hand)
        new_quantity = current_quantity + quantity_delta

        if new_quantity < 0 and not allow_negative:
            raise ValueError(
                f"Insufficient stock for atomic_unit_id={atomic_unit_id}. "
                f"Current={current_quantity}, requested_delta={quantity_delta}."
            )

        movement = InventoryMovement(
            tenant_id=tenant_id,
            branch_id=branch_id,
            inventory_item_id=inventory_item.id,
            atomic_unit_id=atomic_unit_id,
            quantity_delta=quantity_delta,
            movement_type=movement_type,
            source=_normalize_source(source),
            reference_type=reference_type,
            reference_id=reference_id,
            created_at=datetime.utcnow(),
        )

        InventoryRepository.create_movement(
            db,
            movement=movement,
        )

        InventoryRepository.update_quantity(
            inventory_item=inventory_item,
            new_quantity=new_quantity,
        )

        db.flush()

        return movement

    # ========================================================
    # Manual stock operations
    # ========================================================

    @staticmethod
    def stock_in(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
        quantity: int,
        unit_cost: Optional[Any] = None,
        supplier: Optional[str] = None,
        receipt_ref: Optional[str] = None,
        note: Optional[str] = None,
        reorder_level: Optional[int] = None,
        update_cost_price: bool = True,
        reference_type: str = "stock_in",
        reference_id: Optional[int] = None,
    ) -> InventoryMovement:
        """
        Add stock to an item.

        Used for:
        - opening stock
        - new purchases
        - received stock
        - bar/drink stock replenishment
        """

        quantity = _int(quantity)

        if quantity <= 0:
            raise ValueError("Stock-in quantity must be greater than zero")

        unit = InventoryService.get_atomic_unit(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

        if not unit:
            raise ValueError(f"Atomic unit not found: {atomic_unit_id}")

        if update_cost_price and unit_cost is not None:
            cost = _decimal(unit_cost)

            if cost > 0:
                meta = _atomic_meta(unit).copy()
                meta["cost_price"] = float(cost)
                meta["last_purchase_price"] = float(cost)

                if supplier:
                    meta["last_supplier"] = supplier

                if receipt_ref:
                    meta["last_receipt_ref"] = receipt_ref

                if note:
                    meta["last_stock_note"] = note

                unit.meta = meta

        movement = InventoryService._apply_quantity_movement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
            quantity_delta=quantity,
            movement_type=MOVEMENT_STOCK_IN,
            source=SOURCE_INVENTORY,
            reference_type=reference_type,
            reference_id=reference_id,
            reorder_level=reorder_level,
            allow_negative=True,
        )

        return movement

    @staticmethod
    def adjust_inventory(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
        quantity_delta: int,
        source: str = SOURCE_MANUAL,
        note: Optional[str] = None,
        allow_negative: bool = False,
        reference_type: str = "manual",
        reference_id: Optional[int] = None,
    ) -> InventoryMovement:
        """
        Apply a manual inventory adjustment.
        """

        quantity_delta = _int(quantity_delta)

        if quantity_delta == 0:
            raise ValueError("quantity_delta cannot be zero")

        unit = InventoryService.get_atomic_unit(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

        if not unit:
            raise ValueError(f"Atomic unit not found: {atomic_unit_id}")

        return InventoryService._apply_quantity_movement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
            quantity_delta=quantity_delta,
            movement_type=MOVEMENT_ADJUSTMENT,
            source=source,
            reference_type=reference_type,
            reference_id=reference_id,
            allow_negative=allow_negative,
        )

    @staticmethod
    def record_waste_or_loss(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
        quantity: int,
        movement_type: str = MOVEMENT_WASTE,
        source: str = SOURCE_MANUAL,
        reference_type: str = "waste",
        reference_id: Optional[int] = None,
        allow_negative: bool = False,
    ) -> InventoryMovement:
        """
        Reduce stock for waste/loss/spoilage.

        quantity should be positive. Service converts it to negative delta.
        """

        movement_type = _movement_type(movement_type)

        if movement_type not in {MOVEMENT_WASTE, MOVEMENT_LOSS, MOVEMENT_SPOILAGE}:
            raise ValueError("movement_type must be waste, loss, or spoilage")

        quantity = _int(quantity)

        if quantity <= 0:
            raise ValueError("quantity must be greater than zero")

        return InventoryService._apply_quantity_movement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
            quantity_delta=-abs(quantity),
            movement_type=movement_type,
            source=source,
            reference_type=reference_type,
            reference_id=reference_id,
            allow_negative=allow_negative,
        )

    # ========================================================
    # ORDER RESERVATION LIFECYCLE
    # ========================================================

    @staticmethod
    def reserve_order_inventory(
        db: Session,
        *,
        order: Order,
        allow_negative_food: bool = True,
        allow_negative_other: bool = False,
    ) -> List[InventoryMovement]:
        """
        Temporarily withhold stock when a pending order is created.
        """

        if not order or not order.id:
            raise ValueError("order with id is required")

        movements: List[InventoryMovement] = []
        qty_by_atomic = _item_qty_map(order.items)

        for atomic_unit_id, quantity in qty_by_atomic.items():
            if quantity <= 0:
                continue

            profile = InventoryService.get_inventory_profile(
                db,
                tenant_id=order.tenant_id,
                atomic_unit_id=atomic_unit_id,
            )

            if not InventoryService.is_stock_tracked_profile(profile):
                continue

            active_reserved = InventoryService._active_reserved_qty_by_atomic(
                db,
                tenant_id=order.tenant_id,
                branch_id=order.branch_id,
                reference_type="order",
                reference_id=order.id,
            ).get(atomic_unit_id, 0)

            if active_reserved >= quantity:
                continue

            reserve_delta = quantity - active_reserved

            allow_negative = InventoryService.allow_negative_from_profile(
                profile,
                allow_negative_food=allow_negative_food,
                allow_negative_other=allow_negative_other,
            )

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=order.tenant_id,
                branch_id=order.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=-abs(reserve_delta),
                movement_type=MOVEMENT_SALE_HOLD,
                source=SOURCE_SALES,
                reference_type="order",
                reference_id=order.id,
                allow_negative=allow_negative,
            )

            movements.append(movement)

        return movements

    @staticmethod
    def adjust_order_reservation(
        db: Session,
        *,
        order: Order,
        old_items: Any,
        new_items: Any,
        allow_negative_food: bool = True,
        allow_negative_other: bool = False,
    ) -> List[InventoryMovement]:
        """
        Adjust order stock reservation after a pending order is edited.

        Only the delta is posted.
        """

        if not order or not order.id:
            raise ValueError("order with id is required")

        old_map = _item_qty_map(old_items)
        new_map = _item_qty_map(new_items)

        all_atomic_ids = sorted(set(old_map.keys()) | set(new_map.keys()))
        movements: List[InventoryMovement] = []

        for atomic_unit_id in all_atomic_ids:
            old_qty = _int(old_map.get(atomic_unit_id))
            new_qty = _int(new_map.get(atomic_unit_id))

            delta_needed = new_qty - old_qty

            if delta_needed == 0:
                continue

            profile = InventoryService.get_inventory_profile(
                db,
                tenant_id=order.tenant_id,
                atomic_unit_id=atomic_unit_id,
            )

            if not InventoryService.is_stock_tracked_profile(profile):
                continue

            quantity_delta = -abs(delta_needed) if delta_needed > 0 else abs(delta_needed)

            allow_negative = True

            if quantity_delta < 0:
                allow_negative = InventoryService.allow_negative_from_profile(
                    profile,
                    allow_negative_food=allow_negative_food,
                    allow_negative_other=allow_negative_other,
                )

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=order.tenant_id,
                branch_id=order.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=quantity_delta,
                movement_type=MOVEMENT_SALE_HOLD_ADJUST,
                source=SOURCE_SALES,
                reference_type="order",
                reference_id=order.id,
                allow_negative=allow_negative,
            )

            movements.append(movement)

        return movements

    @staticmethod
    def release_order_reservation(
        db: Session,
        *,
        order: Order,
    ) -> List[InventoryMovement]:
        """
        Release active stock reservation for a cancelled/abandoned pending order.
        """

        if not order or not order.id:
            raise ValueError("order with id is required")

        active_reserved = InventoryService._active_reserved_qty_by_atomic(
            db,
            tenant_id=order.tenant_id,
            branch_id=order.branch_id,
            reference_type="order",
            reference_id=order.id,
        )

        released: List[InventoryMovement] = []

        for atomic_unit_id, reserved_qty in active_reserved.items():
            if reserved_qty <= 0:
                continue

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=order.tenant_id,
                branch_id=order.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=abs(reserved_qty),
                movement_type=MOVEMENT_SALE_HOLD_RELEASE,
                source=SOURCE_SALES,
                reference_type="order",
                reference_id=order.id,
                allow_negative=True,
            )

            released.append(movement)

        return released

    @staticmethod
    def commit_order_reservation(
        db: Session,
        *,
        order: Optional[Order] = None,
        order_id: Optional[int] = None,
        sale: Optional[Sale] = None,
    ) -> List[InventoryMovement]:
        """
        Mark an order reservation as permanently committed after payment.

        This does not deduct stock again.
        """

        if not order:
            if not order_id:
                raise ValueError("order or order_id is required")

            tenant_id = sale.tenant_id if sale else None
            branch_id = sale.branch_id if sale else None

            q = db.query(Order).filter(Order.id == order_id)

            if tenant_id is not None:
                q = q.filter(Order.tenant_id == tenant_id)

            if branch_id is not None:
                q = q.filter(Order.branch_id == branch_id)

            order = q.first()

        if not order:
            raise ValueError("Order not found for inventory commit")

        active_reserved = InventoryService._active_reserved_qty_by_atomic(
            db,
            tenant_id=order.tenant_id,
            branch_id=order.branch_id,
            reference_type="order",
            reference_id=order.id,
        )

        committed: List[InventoryMovement] = []

        for atomic_unit_id, reserved_qty in active_reserved.items():
            if reserved_qty <= 0:
                continue

            if InventoryService.has_reference_movement(
                db,
                tenant_id=order.tenant_id,
                branch_id=order.branch_id,
                reference_type="order",
                reference_id=order.id,
                movement_type=MOVEMENT_SALE_COMMIT,
                atomic_unit_id=atomic_unit_id,
            ):
                continue

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=order.tenant_id,
                branch_id=order.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=0,
                movement_type=MOVEMENT_SALE_COMMIT,
                source=SOURCE_SALES,
                reference_type="order",
                reference_id=order.id,
                allow_negative=True,
            )

            committed.append(movement)

        return committed

    # ========================================================
    # SALE RESERVATION / CONFIRMATION LIFECYCLE
    # ========================================================

    @staticmethod
    def reserve_sale_inventory(
        db: Session,
        *,
        sale: Sale,
        allow_negative_food: bool = True,
        allow_negative_other: bool = False,
    ) -> List[InventoryMovement]:
        """
        Backward-compatible sale-level temporary hold.
        """

        movements: List[InventoryMovement] = []

        for item in sale.items:
            atomic_unit_id = _int(item.atomic_unit_id)
            quantity = _int(item.quantity)

            if not atomic_unit_id or quantity <= 0:
                continue

            profile = InventoryService.get_inventory_profile(
                db,
                tenant_id=sale.tenant_id,
                atomic_unit_id=atomic_unit_id,
            )

            if not InventoryService.is_stock_tracked_profile(profile):
                continue

            active_reserved = InventoryService._active_reserved_qty_by_atomic(
                db,
                tenant_id=sale.tenant_id,
                branch_id=sale.branch_id,
                reference_type="sale",
                reference_id=sale.id,
            ).get(atomic_unit_id, 0)

            if active_reserved >= quantity:
                continue

            reserve_delta = quantity - active_reserved

            allow_negative = InventoryService.allow_negative_from_profile(
                profile,
                allow_negative_food=allow_negative_food,
                allow_negative_other=allow_negative_other,
            )

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=sale.tenant_id,
                branch_id=sale.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=-abs(reserve_delta),
                movement_type=MOVEMENT_SALE_HOLD,
                source=SOURCE_SALES,
                reference_type="sale",
                reference_id=sale.id,
                allow_negative=allow_negative,
            )

            movements.append(movement)

        return movements

    @staticmethod
    def release_sale_reservation(
        db: Session,
        *,
        sale: Sale,
    ) -> List[InventoryMovement]:
        """
        Release sale-level temporary stock hold.
        """

        active_reserved = InventoryService._active_reserved_qty_by_atomic(
            db,
            tenant_id=sale.tenant_id,
            branch_id=sale.branch_id,
            reference_type="sale",
            reference_id=sale.id,
        )

        released: List[InventoryMovement] = []

        for atomic_unit_id, reserved_qty in active_reserved.items():
            if reserved_qty <= 0:
                continue

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=sale.tenant_id,
                branch_id=sale.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=abs(reserved_qty),
                movement_type=MOVEMENT_SALE_HOLD_RELEASE,
                source=SOURCE_SALES,
                reference_type="sale",
                reference_id=sale.id,
                allow_negative=True,
            )

            released.append(movement)

        return released

    @staticmethod
    def finalize_sale_inventory(
        db: Session,
        *,
        sale: Sale,
        allow_negative_food: bool = True,
        allow_negative_other: bool = False,
    ) -> List[InventoryMovement]:
        """
        Permanently apply inventory impact for a sale.

        Logic:
        - If sale has order_id and order reservation exists:
          commit order reservation with zero-delta sale_commit markers.
          No second deduction.

        - Else if sale-level hold exists:
          create sale_commit markers.
          No second deduction.

        - Else:
          direct-sale flow; deduct now with movement_type="sale".
        """

        movements: List[InventoryMovement] = []

        if getattr(sale, "order_id", None):
            order_commit_movements = InventoryService.commit_order_reservation(
                db,
                order_id=sale.order_id,
                sale=sale,
            )

            if order_commit_movements:
                return order_commit_movements

        existing_sale_holds = InventoryService._active_reserved_qty_by_atomic(
            db,
            tenant_id=sale.tenant_id,
            branch_id=sale.branch_id,
            reference_type="sale",
            reference_id=sale.id,
        )

        if existing_sale_holds:
            for atomic_unit_id, reserved_qty in existing_sale_holds.items():
                if reserved_qty <= 0:
                    continue

                if InventoryService.has_reference_movement(
                    db,
                    tenant_id=sale.tenant_id,
                    branch_id=sale.branch_id,
                    reference_type="sale",
                    reference_id=sale.id,
                    movement_type=MOVEMENT_SALE_COMMIT,
                    atomic_unit_id=atomic_unit_id,
                ):
                    continue

                movement = InventoryService._apply_quantity_movement(
                    db,
                    tenant_id=sale.tenant_id,
                    branch_id=sale.branch_id,
                    atomic_unit_id=atomic_unit_id,
                    quantity_delta=0,
                    movement_type=MOVEMENT_SALE_COMMIT,
                    source=SOURCE_SALES,
                    reference_type="sale",
                    reference_id=sale.id,
                    allow_negative=True,
                )

                movements.append(movement)

            return movements

        for item in sale.items:
            atomic_unit_id = _int(item.atomic_unit_id)
            quantity = _int(item.quantity)

            if not atomic_unit_id or quantity <= 0:
                continue

            profile = InventoryService.get_inventory_profile(
                db,
                tenant_id=sale.tenant_id,
                atomic_unit_id=atomic_unit_id,
            )

            if not InventoryService.is_stock_tracked_profile(profile):
                continue

            if InventoryService.has_reference_movement(
                db,
                tenant_id=sale.tenant_id,
                branch_id=sale.branch_id,
                reference_type="sale",
                reference_id=sale.id,
                movement_type=MOVEMENT_SALE,
                atomic_unit_id=atomic_unit_id,
            ):
                continue

            allow_negative = InventoryService.allow_negative_from_profile(
                profile,
                allow_negative_food=allow_negative_food,
                allow_negative_other=allow_negative_other,
            )

            movement = InventoryService._apply_quantity_movement(
                db,
                tenant_id=sale.tenant_id,
                branch_id=sale.branch_id,
                atomic_unit_id=atomic_unit_id,
                quantity_delta=-abs(quantity),
                movement_type=MOVEMENT_SALE,
                source=SOURCE_SALES,
                reference_type="sale",
                reference_id=sale.id,
                allow_negative=allow_negative,
            )

            movements.append(movement)

        return movements

    @staticmethod
    def apply_sale_inventory(
        db: Session,
        *,
        sale: Sale,
    ) -> None:
        """
        Backward-compatible alias for old callers.
        """

        InventoryService.finalize_sale_inventory(
            db,
            sale=sale,
        )

    # ========================================================
    # Stock status / sellability
    # ========================================================

    @staticmethod
    def stock_status_for_quantity(
        *,
        quantity_on_hand: int,
        reorder_level: Optional[int] = None,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        quantity = _int(quantity_on_hand)
        reorder = _int(reorder_level) if reorder_level is not None else None

        if not is_active:
            status = "inactive"
            color = "gray"
            is_sellable = False
        elif quantity <= 0:
            status = "out_of_stock"
            color = "red"
            is_sellable = False
        elif reorder is not None and quantity <= reorder:
            status = "low_stock"
            color = "amber"
            is_sellable = True
        else:
            status = "available"
            color = "green"
            is_sellable = True

        return {
            "quantity_on_hand": quantity,
            "reorder_level": reorder,
            "stock_status": status,
            "stock_color": color,
            "is_sellable": is_sellable,
        }

    @staticmethod
    def get_stock_status(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
    ) -> Dict[str, Any]:
        unit = InventoryService.get_atomic_unit(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

        profile = InventoryService.get_inventory_profile(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

        item = InventoryRepository.get_item(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            atomic_unit_id=atomic_unit_id,
        )

        if not item:
            status_payload = InventoryService.stock_status_for_quantity(
                quantity_on_hand=0,
                reorder_level=None,
                is_active=bool(unit.is_active) if unit else True,
            )

            status_payload.update(profile)
            status_payload["disable_sale"] = (
                bool(profile.get("disable_when_out"))
                and status_payload["stock_status"] == "out_of_stock"
            )

            return status_payload

        status_payload = InventoryService.stock_status_for_quantity(
            quantity_on_hand=item.quantity_on_hand,
            reorder_level=item.reorder_level,
            is_active=bool(unit.is_active) if unit else True,
        )

        status_payload.update(profile)
        status_payload["disable_sale"] = (
            bool(profile.get("disable_when_out"))
            and status_payload["stock_status"] == "out_of_stock"
        )

        return status_payload

    @staticmethod
    def list_commerce_inventory_products(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
    ) -> Dict[str, Any]:
        """
        Return all active COMMERCE → Inventory atomic units for stock management.

        This is different from list_inventory():
        - list_inventory() returns only existing inventory_items rows.
        - this method returns all commerce inventory atomic units, even if
          no inventory_items row exists yet.

        Grouping rule:
        - If commerce_subcategory exists: group under subcategory.
        - Else if commerce_category exists: group under category.
        - Else: group under "Other".

        Example:
        - Beer items -> Beer
        - White Beans -> Main Dish
        - Cigarettes / Charcoal / Shisha directly mapped to Others -> Others
        """

        # ----------------------------------------------------
        # 1. Load all active atomic units that have at least one
        #    active COMMERCE taxonomy mapping.
        # ----------------------------------------------------
        rows = (
            db.query(AtomicUnit)
            .join(
                AtomicUnitTaxonomy,
                AtomicUnitTaxonomy.atomic_unit_id == AtomicUnit.id,
            )
            .join(
                TaxonomyNode,
                TaxonomyNode.id == AtomicUnitTaxonomy.taxonomy_node_id,
            )
            .filter(AtomicUnit.tenant_id == tenant_id)
            .filter(AtomicUnit.is_active.is_(True))
            .filter(TaxonomyNode.tenant_id == tenant_id)
            .filter(TaxonomyNode.taxonomy_type == "COMMERCE")
            .filter(TaxonomyNode.is_active.is_(True))
            .order_by(AtomicUnit.name.asc(), AtomicUnit.id.asc())
            .all()
        )

        # Remove duplicates caused by multiple taxonomy mappings.
        units_by_id: Dict[int, AtomicUnit] = {}

        for unit in rows:
            if unit and unit.id:
                units_by_id[int(unit.id)] = unit

        # ----------------------------------------------------
        # 2. Build product payloads using taxonomy-aware profile
        #    and live stock status.
        # ----------------------------------------------------
        groups_map: Dict[str, Dict[str, Any]] = {}

        total_items = 0
        total_value = Decimal("0")
        available = 0
        low_stock = 0
        out_of_stock = 0
        inactive = 0

        for unit in units_by_id.values():
            profile = InventoryService.get_inventory_profile(
                db,
                tenant_id=tenant_id,
                atomic_unit_id=unit.id,
            )

            # Keep only COMMERCE → Inventory items.
            if profile.get("commerce_domain") != "Inventory":
                continue

            # If resolver explicitly says not stock tracked, skip.
            # This protects future services/subscriptions/digital goods.
            if not InventoryService.is_stock_tracked_profile(profile):
                continue

            status_payload = InventoryService.get_stock_status(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                atomic_unit_id=unit.id,
            )

            cost_price = InventoryService.get_cost_price(unit)
            quantity_on_hand = _int(status_payload.get("quantity_on_hand"))
            unit_price = _decimal(getattr(unit, "unit_price", 0))

            estimated_stock_value = cost_price * Decimal(quantity_on_hand)

            commerce_category = (
                profile.get("commerce_category")
                or "Other"
            )

            commerce_subcategory = profile.get("commerce_subcategory")

            group_label = (
                commerce_subcategory
                or commerce_category
                or "Other"
            )

            group_key = (
                str(group_label)
                .strip()
                .lower()
                .replace("&", "and")
                .replace("/", "-")
                .replace(" ", "-")
            ) or "other"

            if group_key not in groups_map:
                groups_map[group_key] = {
                    "key": group_key,
                    "label": group_label,
                    "category": commerce_category,
                    "subcategory": commerce_subcategory,
                    "items": [],
                }

            product_payload = {
                "id": str(unit.id),
                "atomic_unit_id": unit.id,
                "name": unit.name,
                "sku": unit.sku,
                "unit_type": unit.unit_type,
                "is_active": bool(unit.is_active),

                "category": commerce_category,
                "subcategory": commerce_subcategory or commerce_category or "Other",
                "commerce_category": commerce_category,
                "commerce_subcategory": commerce_subcategory,
                "group_label": group_label,

                "stock_on_hand": quantity_on_hand,
                "quantity_on_hand": quantity_on_hand,
                "reorder_level": status_payload.get("reorder_level"),

                "buying_price": float(cost_price) if cost_price > 0 else None,
                "cost_price": float(cost_price) if cost_price > 0 else None,
                "unit_cost": float(cost_price) if cost_price > 0 else None,

                "selling_price": float(unit_price) if unit_price > 0 else None,
                "unit_price": float(unit_price) if unit_price > 0 else None,

                "estimated_stock_value": float(estimated_stock_value),

                "stock_status": status_payload.get("stock_status"),
                "stock_color": status_payload.get("stock_color"),
                "is_sellable": bool(status_payload.get("is_sellable")),
                "disable_sale": bool(status_payload.get("disable_sale")),

                "stock_tracked": bool(profile.get("stock_tracked")),
                "inventory_family": profile.get("inventory_family"),
                "allow_negative_stock": bool(profile.get("allow_negative_stock")),
                "disable_when_out": bool(profile.get("disable_when_out")),
                "cost_mode": profile.get("cost_mode"),
                "mapping_warnings": profile.get("mapping_warnings") or [],
            }

            groups_map[group_key]["items"].append(product_payload)

            total_items += 1
            total_value += estimated_stock_value

            stock_status = str(status_payload.get("stock_status") or "")

            if stock_status == "available":
                available += 1
            elif stock_status == "low_stock":
                low_stock += 1
            elif stock_status == "out_of_stock":
                out_of_stock += 1
            elif stock_status == "inactive":
                inactive += 1

        # ----------------------------------------------------
        # 3. Sort groups and items alphabetically.
        # ----------------------------------------------------
        groups = list(groups_map.values())

        for group in groups:
            group["items"] = sorted(
                group["items"],
                key=lambda item: str(item.get("name") or "").lower(),
            )

        groups = sorted(
            groups,
            key=lambda group: str(group.get("label") or "").lower(),
        )

        return {
            "count": total_items,
            "groups": groups,
            "summary": {
                "total_items": total_items,
                "available": available,
                "low_stock": low_stock,
                "out_of_stock": out_of_stock,
                "inactive": inactive,
                "estimated_stock_value": float(total_value),
            },
        }

    # ========================================================
    # Internal stock policy helpers
    # ========================================================

    @staticmethod
    def _allow_negative_for_unit(
        *,
        unit: Optional[AtomicUnit],
        allow_negative_food: bool,
        allow_negative_other: bool,
    ) -> bool:
        """
        Backward-compatible meta-based negative-stock policy.

        Preferred new check:
          get_inventory_profile() + allow_negative_from_profile()
        """

        if not unit:
            return allow_negative_other

        meta = _atomic_meta(unit)

        if "allow_negative_stock" in meta:
            return _is_truthy(meta.get("allow_negative_stock"), default=False)

        category = str(meta.get("category") or meta.get("category_name") or "").lower()
        segment = str(meta.get("segment") or "").lower()

        if category == "food" or segment == "kitchen":
            return allow_negative_food

        if category == "drinks" or segment == "bar":
            return False

        return allow_negative_other