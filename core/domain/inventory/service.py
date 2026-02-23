from datetime import datetime
from uuid import uuid4
from typing import Optional

from sqlalchemy.orm import Session

from core.domain.inventory.models import (
    InventoryItem,
    InventoryMovement,
    InventoryMovementType,
    InventorySource,
)
from core.domain.inventory.repository import InventoryRepository
from core.domain.sales.models import Sale
from core.domain.catalog.models import BillableUnit


class InventoryService:
    """
    Domain service for inventory.

    Responsibilities:
    - Apply inventory movements
    - Maintain cached quantity_on_hand
    - Enforce ledger-first invariant
    - Handle sale-driven deductions ONLY after payment success
    """

    # -------------------------------------------------
    # Sale-driven inventory deduction
    # -------------------------------------------------

    @staticmethod
    def apply_sale_inventory(
        db: Session,
        *,
        sale: Sale,
    ) -> None:
        """
        Deduct inventory for a PAID sale.

        HARD RULES:
        - Must be called ONLY after payment success
        - Must be executed inside the same transaction
        - Inventory is deducted per SaleItem
        """

        if sale.status.value != "paid":
            raise ValueError("Inventory can only be applied to PAID sales")

        for item in sale.items:
            InventoryService._apply_item_deduction(
                db=db,
                tenant_id=sale.tenant_id,
                branch_id=sale.branch_id,
                billable_unit_id=item.billable_unit_id,
                quantity=item.quantity,
                reference_id=sale.id,
            )

    # -------------------------------------------------
    # Internal helpers
    # -------------------------------------------------

    @staticmethod
    def _apply_item_deduction(
        db: Session,
        *,
        tenant_id: str,
        branch_id: str,
        billable_unit_id: str,
        quantity: int,
        reference_id: str,
    ) -> None:
        """
        Apply inventory deduction for a single SaleItem.
        """

        # Fetch or create inventory item
        inventory_item = InventoryRepository.get_item(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            billable_unit_id=billable_unit_id,
        )

        if not inventory_item:
            inventory_item = InventoryItem(
                id=str(uuid4()),
                tenant_id=tenant_id,
                branch_id=branch_id,
                billable_unit_id=billable_unit_id,
                quantity_on_hand=0,
                created_at=datetime.utcnow(),
            )
            InventoryRepository.create_item(
                db,
                inventory_item=inventory_item,
            )

        # Calculate new cached quantity
        new_quantity = inventory_item.quantity_on_hand - quantity

        # Create ledger movement
        movement = InventoryMovement(
            id=str(uuid4()),
            tenant_id=tenant_id,
            branch_id=branch_id,
            inventory_item_id=inventory_item.id,
            billable_unit_id=billable_unit_id,
            quantity_delta=-quantity,
            movement_type=InventoryMovementType.sale,
            source=InventorySource.system,
            reference_type="sale",
            reference_id=reference_id,
            created_at=datetime.utcnow(),
        )

        # Persist movement + cache update (atomic)
        InventoryRepository.create_movement(
            db,
            movement=movement,
        )
        InventoryRepository.update_quantity(
            inventory_item=inventory_item,
            new_quantity=new_quantity,
        )

    # -------------------------------------------------
    # Manual adjustments (future UI / admin)
    # -------------------------------------------------

    @staticmethod
    def adjust_inventory(
        db: Session,
        *,
        tenant_id: str,
        branch_id: str,
        billable_unit_id: str,
        quantity_delta: int,
        source: InventorySource = InventorySource.manual,
        note: Optional[str] = None,
    ) -> InventoryMovement:
        """
        Apply a manual inventory adjustment.

        Used for:
        - Stock counts
        - Corrections
        - Initial stock imports
        """

        inventory_item = InventoryRepository.get_item(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            billable_unit_id=billable_unit_id,
        )

        if not inventory_item:
            inventory_item = InventoryItem(
                id=str(uuid4()),
                tenant_id=tenant_id,
                branch_id=branch_id,
                billable_unit_id=billable_unit_id,
                quantity_on_hand=0,
                created_at=datetime.utcnow(),
            )
            InventoryRepository.create_item(
                db,
                inventory_item=inventory_item,
            )

        new_quantity = inventory_item.quantity_on_hand + quantity_delta

        movement = InventoryMovement(
            id=str(uuid4()),
            tenant_id=tenant_id,
            branch_id=branch_id,
            inventory_item_id=inventory_item.id,
            billable_unit_id=billable_unit_id,
            quantity_delta=quantity_delta,
            movement_type=InventoryMovementType.adjustment,
            source=source,
            reference_type="manual",
            reference_id=None,
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

        return movement
