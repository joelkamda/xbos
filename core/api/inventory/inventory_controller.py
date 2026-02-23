from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.inventory.service import InventoryService
from core.domain.inventory.repository import InventoryRepository
from core.errors.api_error import APIError


class InventoryController:
    """
    HTTP controller for Inventory.

    Responsibilities:
    - Extract tenant / branch context
    - Delegate to InventoryService / Repository
    - Return audit-friendly payloads
    - NO business logic
    """

    def __init__(self):
        pass

    # -------------------------------------------------
    # List inventory items (cached state)
    # -------------------------------------------------

    async def list_inventory(
        self,
        request: Request,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)
        branch_id = getattr(request.state, "branch_id", None)

        if not tenant_id or not branch_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant or branch context",
            )

        try:
            items = InventoryRepository.list_items_for_branch(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
            )

            return [
                {
                    "billable_unit_id": i.billable_unit_id,
                    "quantity_on_hand": i.quantity_on_hand,
                }
                for i in items
            ]

        except Exception as e:
            raise ApiError(
                message="Failed to list inventory",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Inventory movements (ledger)
    # -------------------------------------------------

    async def list_movements(
        self,
        request: Request,
        billable_unit_id: str | None,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)
        branch_id = getattr(request.state, "branch_id", None)

        if not tenant_id or not branch_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant or branch context",
            )

        try:
            movements = InventoryRepository.list_movements(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                billable_unit_id=billable_unit_id,
            )

            return [
                {
                    "billable_unit_id": m.billable_unit_id,
                    "quantity_delta": m.quantity_delta,
                    "movement_type": m.movement_type.value,
                    "reference_type": m.reference_type,
                    "reference_id": m.reference_id,
                    "created_at": m.created_at.isoformat(),
                }
                for m in movements
            ]

        except Exception as e:
            raise ApiError(
                message="Failed to list inventory movements",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # Manual inventory adjustment
    # -------------------------------------------------

    async def adjust_inventory(
        self,
        request: Request,
        payload: dict,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)
        branch_id = getattr(request.state, "branch_id", None)

        if not tenant_id or not branch_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant or branch context",
            )

        billable_unit_id = payload.get("billable_unit_id")
        quantity_delta = payload.get("quantity_delta")

        if not billable_unit_id or quantity_delta is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="billable_unit_id and quantity_delta are required",
            )

        try:
            movement = InventoryService.adjust_inventory(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                billable_unit_id=billable_unit_id,
                quantity_delta=int(quantity_delta),
            )

            return {
                "movement_id": movement.id,
                "billable_unit_id": movement.billable_unit_id,
                "quantity_delta": movement.quantity_delta,
                "movement_type": movement.movement_type.value,
                "created_at": movement.created_at.isoformat(),
            }

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        except Exception as e:
            raise ApiError(
                message="Failed to adjust inventory",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e
