from fastapi import APIRouter, Request, Depends, HTTPException, status

from core.api.sales.sales_controller import SalesController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Sales"])
controller = SalesController()


# -------------------------------------------------
# LIST SALES
# -------------------------------------------------
@router.get("/")
@require_permissions("sale.view")
async def list_sales(
    request: Request,
    db = Depends(get_db),
):
    print("\n========== SALES LIST ==========")
    print("🔥 USER:", request.state.user)
    return await controller.list_sales(request, db)


# -------------------------------------------------
# CREATE SALE
# -------------------------------------------------
@router.post("/")
@require_permissions("sale.create")
async def create_sale(
    request: Request,
    payload: dict,
    db = Depends(get_db),
):
    print("\n========== CREATE SALE ==========")
    print("🔥 USER:", request.state.user)
    print("🔥 PAYLOAD:", payload)

    return await controller.create_sale(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# 🔥 GET SINGLE SALE (REQUIRED FOR POLLING)
# -------------------------------------------------
@router.get("/{sale_id}")
@require_permissions("sale.view")
async def get_sale(
    sale_id: int,
    request: Request,
    db = Depends(get_db),
):
    print("\n========== GET SALE ==========")
    print("🔥 SALE ID:", sale_id)
    print("🔥 USER:", request.state.user)

    sale = await controller.get_sale(
        request=request,
        sale_id=sale_id,
        db=db,
    )

    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sale not found",
        )

    return sale
