from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from typing import Optional

from core.api.inventory.inventory_controller import InventoryController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Inventory"])
controller = InventoryController()


# -------------------------------------------------
# List inventory cached state
# Final path: GET /kernel/inventory/
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
# Commerce inventory products
# Final path: GET /kernel/inventory/products
#
# IMPORTANT:
# This must stay before /status/{atomic_unit_id}
# so "products" is never treated like an atomic_unit_id.
# -------------------------------------------------

@router.get("/products")
@require_permissions("inventory.view")
async def list_inventory_products(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.list_inventory_products(
        request=request,
        db=db,
    )


# -------------------------------------------------
# Inventory movements ledger
# Final path: GET /kernel/inventory/movements
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
# Stock status for one atomic unit
# Final path: GET /kernel/inventory/status/{atomic_unit_id}
# -------------------------------------------------

@router.get("/status/{atomic_unit_id}")
@require_permissions("inventory.view")
async def stock_status(
    request: Request,
    atomic_unit_id: int,
    db: Session = Depends(get_db),
):
    return await controller.stock_status(
        request=request,
        atomic_unit_id=atomic_unit_id,
        db=db,
    )


# -------------------------------------------------
# Stock-in / receive new stock
# Final path: POST /kernel/inventory/stock-in
# -------------------------------------------------

@router.post("/stock-in")
@require_permissions("inventory.adjust")
async def stock_in(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
):
    return await controller.stock_in(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# Manual inventory adjustment
# Final path: POST /kernel/inventory/adjust
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