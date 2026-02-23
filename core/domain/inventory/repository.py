from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import select

from core.domain.inventory.models import (
    InventoryItem,
    InventoryMovement,
)


class InventoryRepository:
    """
    Data-access layer for Inventory.

    Responsibilities:
    - Fetch inventory items
    - Persist inventory movements
    - Persist cached quantity updates
    - NO business rules
    """

    # -------------------------------------------------
    # InventoryItem (cached state)
    # -------------------------------------------------

    @staticmethod
    def get_item(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        billable_unit_id: int,
    ) -> Optional[InventoryItem]:
        """
        Fetch inventory item for a billable unit at a branch.
        """
        stmt = (
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.branch_id == branch_id)
            .where(InventoryItem.billable_unit_id == billable_unit_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_items_for_branch(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
    ) -> List[InventoryItem]:
        """
        List all inventory items for a branch.
        """
        stmt = (
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.branch_id == branch_id)
            .order_by(InventoryItem.billable_unit_id.asc())
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def create_item(
        db: Session,
        *,
        inventory_item: InventoryItem,
    ) -> InventoryItem:
        """
        Persist a new InventoryItem.
        """
        db.add(inventory_item)
        return inventory_item

    @staticmethod
    def update_quantity(
        *,
        inventory_item: InventoryItem,
        new_quantity: int,
    ) -> None:
        """
        Update cached quantity_on_hand.

        IMPORTANT:
        - Must be called ONLY inside a transaction
        - Must accompany an InventoryMovement insert
        """
        inventory_item.quantity_on_hand = new_quantity

    # -------------------------------------------------
    # InventoryMovement (ledger)
    # -------------------------------------------------

    @staticmethod
    def create_movement(
        db: Session,
        *,
        movement: InventoryMovement,
    ) -> InventoryMovement:
        """
        Persist an inventory movement.
        """
        db.add(movement)
        return movement

    @staticmethod
    def list_movements(
        db: Session,
        *,
        tenant_id: int,
        branch_id: Optional[int] = None,
        billable_unit_id: Optional[int] = None,
        movement_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[InventoryMovement]:
        """
        List inventory movements with optional filters.

        NOTE:
        - movement_type is a STRING (validated by service layer)
        """
        stmt = select(InventoryMovement).where(
            InventoryMovement.tenant_id == tenant_id
        )

        if branch_id is not None:
            stmt = stmt.where(InventoryMovement.branch_id == branch_id)

        if billable_unit_id is not None:
            stmt = stmt.where(
                InventoryMovement.billable_unit_id == billable_unit_id
            )

        if movement_type is not None:
            stmt = stmt.where(
                InventoryMovement.movement_type == movement_type
            )

        stmt = stmt.order_by(
            InventoryMovement.created_at.desc()
        ).limit(limit)

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def sum_quantity_delta(
        db: Session,
        *,
        inventory_item_id: int,
    ) -> int:
        """
        Recompute quantity from ledger (reconciliation / audits).
        """
        stmt = (
            select(InventoryMovement.quantity_delta)
            .where(InventoryMovement.inventory_item_id == inventory_item_id)
        )

        deltas = db.execute(stmt).scalars().all()
        return sum(deltas)
