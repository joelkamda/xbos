from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from typing import Optional

from core.api.inventory.inventory_controller import InventoryController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(prefix="/inventory", tags=["Inventory"])
controller = InventoryController()


# -------------------------------------------------
# List inventory (cached quantities)
# -------------------------------------------------

@router.get("/")
@require_permissions("inventory.view")
async def list_inventory(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.list_inventory(
        request=request,
        db=db,
    )


# -------------------------------------------------
# Inventory movements (ledger)
# -------------------------------------------------

@router.get("/movements")
@require_permissions("inventory.view")
async def list_inventory_movements(
    request: Request,
    atomic_unit_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return await controller.list_movements(
        request=request,
        atomic_unit_id=atomic_unit_id,
        db=db,
    )


# -------------------------------------------------
# Manual inventory adjustment
# -------------------------------------------------

@router.post("/adjust")
@require_permissions("inventory.adjust")
async def adjust_inventory(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
):
    return await controller.adjust_inventory(
        request=request,
        payload=payload,
        db=db,
    )
