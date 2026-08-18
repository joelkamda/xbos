from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from core.api.inventory.inventory_controller import InventoryController
from core.domain.inventory.reconciliation_service import StockReconciliationService
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
    movement_type: Optional[str] = None,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    source: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return await controller.list_movements(
        request=request,
        atomic_unit_id=atomic_unit_id,
        movement_type=movement_type,
        reference_type=reference_type,
        reference_id=reference_id,
        source=source,
        limit=limit,
        offset=offset,
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
@require_permissions("inventory.receive")
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

# -------------------------------------------------
# Waste / loss / spoilage
# Final path: POST /kernel/inventory/waste
# -------------------------------------------------

@router.post("/waste")
@require_permissions("inventory.consume")
async def record_inventory_waste(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
):
    return await controller.record_waste_or_loss(
        request=request,
        payload=payload,
        db=db,
    )

# -------------------------------------------------
# Stock reconciliation window
# -------------------------------------------------

def _stock_recon_ctx(request: Request):
    ctx = getattr(request.state, "user", None)
    if not ctx or not isinstance(ctx, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing auth context",
        )
    return {
        "tenant_id": int(ctx["tenant_id"]),
        "branch_id": int(ctx["branch_id"]),
        "user_id": int(ctx["user_id"]) if ctx.get("user_id") else None,
    }


@router.get("/reconciliation")
@require_permissions("inventory.reconcile")
async def get_inventory_reconciliation(
    request: Request,
    business_date: str,
    shift: str = "day",
    db: Session = Depends(get_db),
):
    ctx = _stock_recon_ctx(request)
    try:
        return StockReconciliationService.get_window(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            business_date=business_date,
            shift=shift,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/reconciliation/close")
@require_permissions("inventory.reconcile")
async def close_inventory_reconciliation(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
):
    ctx = _stock_recon_ctx(request)
    try:
        result = StockReconciliationService.close_window(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            business_date=str(payload.get("business_date") or ""),
            shift=str(payload.get("shift") or "day"),
            lines=payload.get("lines") or [],
            note=str(payload.get("note") or ""),
            closed_by_user_id=ctx.get("user_id"),
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        detail = str(exc)
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if "already closed" in detail.lower()
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=detail,
        )
    except Exception:
        db.rollback()
        raise
