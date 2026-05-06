from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import select, func

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
    - Provide audit/reconciliation helpers
    - NO business rules
    """

    # -------------------------------------------------
    # InventoryItem cached state
    # -------------------------------------------------

    @staticmethod
    def get_item(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
    ) -> Optional[InventoryItem]:
        """
        Fetch inventory item for an atomic unit at a branch.
        """

        stmt = (
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.branch_id == branch_id)
            .where(InventoryItem.atomic_unit_id == atomic_unit_id)
        )

        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_item_by_id(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        inventory_item_id: int,
    ) -> Optional[InventoryItem]:
        """
        Fetch inventory item by inventory item id.
        """

        stmt = (
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.branch_id == branch_id)
            .where(InventoryItem.id == inventory_item_id)
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
            .order_by(InventoryItem.atomic_unit_id.asc())
        )

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_items_for_branch_with_stock(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        only_positive: bool = False,
    ) -> List[InventoryItem]:
        """
        List inventory items with optional positive-stock filter.
        """

        stmt = (
            select(InventoryItem)
            .where(InventoryItem.tenant_id == tenant_id)
            .where(InventoryItem.branch_id == branch_id)
        )

        if only_positive:
            stmt = stmt.where(InventoryItem.quantity_on_hand > 0)

        stmt = stmt.order_by(InventoryItem.atomic_unit_id.asc())

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
        - Must be called ONLY inside a transaction.
        - Must accompany an InventoryMovement insert.
        """

        inventory_item.quantity_on_hand = int(new_quantity)

    @staticmethod
    def update_reorder_level(
        *,
        inventory_item: InventoryItem,
        reorder_level: Optional[int],
    ) -> None:
        """
        Update reorder level for an inventory item.
        """

        inventory_item.reorder_level = reorder_level

    # -------------------------------------------------
    # InventoryMovement ledger
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
        atomic_unit_id: Optional[int] = None,
        inventory_item_id: Optional[int] = None,
        movement_type: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[InventoryMovement]:
        """
        List inventory movements with optional filters.

        NOTE:
        - movement_type is a STRING.
        - business validation belongs in InventoryService.
        """

        stmt = select(InventoryMovement).where(
            InventoryMovement.tenant_id == tenant_id
        )

        if branch_id is not None:
            stmt = stmt.where(InventoryMovement.branch_id == branch_id)

        if atomic_unit_id is not None:
            stmt = stmt.where(
                InventoryMovement.atomic_unit_id == atomic_unit_id
            )

        if inventory_item_id is not None:
            stmt = stmt.where(
                InventoryMovement.inventory_item_id == inventory_item_id
            )

        if movement_type is not None:
            stmt = stmt.where(
                InventoryMovement.movement_type == movement_type
            )

        if reference_type is not None:
            stmt = stmt.where(
                InventoryMovement.reference_type == reference_type
            )

        if reference_id is not None:
            stmt = stmt.where(
                InventoryMovement.reference_id == reference_id
            )

        if source is not None:
            stmt = stmt.where(
                InventoryMovement.source == source
            )

        stmt = stmt.order_by(
            InventoryMovement.created_at.desc(),
            InventoryMovement.id.desc(),
        ).limit(limit)

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_movements_for_reference(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        reference_type: str,
        reference_id: int,
        movement_type: Optional[str] = None,
        atomic_unit_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[InventoryMovement]:
        """
        List movements for a referenced business object.

        Used for:
        - sale reservation detection
        - sale commit idempotency
        - release/cancel reservation flows
        """

        return InventoryRepository.list_movements(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            reference_type=reference_type,
            reference_id=reference_id,
            movement_type=movement_type,
            atomic_unit_id=atomic_unit_id,
            limit=limit,
        )

    @staticmethod
    def has_movement_for_reference(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        reference_type: str,
        reference_id: int,
        movement_type: str,
        atomic_unit_id: Optional[int] = None,
    ) -> bool:
        """
        Fast idempotency helper for movement existence.
        """

        stmt = (
            select(InventoryMovement.id)
            .where(InventoryMovement.tenant_id == tenant_id)
            .where(InventoryMovement.branch_id == branch_id)
            .where(InventoryMovement.reference_type == reference_type)
            .where(InventoryMovement.reference_id == reference_id)
            .where(InventoryMovement.movement_type == movement_type)
        )

        if atomic_unit_id is not None:
            stmt = stmt.where(
                InventoryMovement.atomic_unit_id == atomic_unit_id
            )

        return db.execute(stmt).first() is not None

    @staticmethod
    def sum_quantity_delta(
        db: Session,
        *,
        inventory_item_id: int,
    ) -> int:
        """
        Recompute quantity from ledger for one inventory item.

        Useful for reconciliation/audits.
        """

        stmt = (
            select(func.coalesce(func.sum(InventoryMovement.quantity_delta), 0))
            .where(InventoryMovement.inventory_item_id == inventory_item_id)
        )

        return int(db.execute(stmt).scalar_one() or 0)

    @staticmethod
    def sum_quantity_delta_for_unit(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        atomic_unit_id: int,
    ) -> int:
        """
        Recompute quantity from ledger by atomic unit.
        """

        stmt = (
            select(func.coalesce(func.sum(InventoryMovement.quantity_delta), 0))
            .where(InventoryMovement.tenant_id == tenant_id)
            .where(InventoryMovement.branch_id == branch_id)
            .where(InventoryMovement.atomic_unit_id == atomic_unit_id)
        )

        return int(db.execute(stmt).scalar_one() or 0)

    @staticmethod
    def movement_count_for_reference(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        reference_type: str,
        reference_id: int,
        movement_type: Optional[str] = None,
    ) -> int:
        """
        Count movements for a referenced business object.
        """

        stmt = (
            select(func.count(InventoryMovement.id))
            .where(InventoryMovement.tenant_id == tenant_id)
            .where(InventoryMovement.branch_id == branch_id)
            .where(InventoryMovement.reference_type == reference_type)
            .where(InventoryMovement.reference_id == reference_id)
        )

        if movement_type is not None:
            stmt = stmt.where(InventoryMovement.movement_type == movement_type)

        return int(db.execute(stmt).scalar_one() or 0)