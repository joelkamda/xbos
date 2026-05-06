# core/api/sales/sales_router.py

from fastapi import APIRouter, Request, Depends, HTTPException, status, Body

from core.api.sales.sales_controller import SalesController
from core.domain.sales.repository import SaleRepository
from core.domain.sales.models import SaleStatus
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Sales"])
controller = SalesController()


@router.get("/")
@require_permissions("sale.view")
async def list_sales(
    request: Request,
    db=Depends(get_db),
    sale_status: str | None = None,
):
    ctx = getattr(request.state, "user", None)

    if not ctx or not isinstance(ctx, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication context",
        )

    if sale_status:
        try:
            sale_status_enum = SaleStatus(sale_status)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sale status",
            )

        sales = SaleRepository.list_by_status(
            db,
            tenant_id=ctx["tenant_id"],
            status=sale_status_enum,
        )

    else:
        sales = SaleRepository.list_for_branch(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
        )

    return [
        SalesController._sale_response(sale)
        for sale in sales
    ]


# =================================================
# CREATE SALE
# =================================================
@router.post("/")
@require_permissions("sale.create", "order.create")
async def create_sale(
    request: Request,
    payload: dict = Body(...),
    db=Depends(get_db),
):
    print("\n========== CREATE SALE ==========")
    print("🔥 USER:", getattr(request.state, "user", None))
    print("🔥 PAYLOAD:", payload)

    try:
        sale = await controller.create_sale(
            request=request,
            payload=payload,
            db=db,
        )

        print("🔥 SALE CREATED:", sale)

        return sale

    except Exception as e:
        print("❌ CREATE SALE ERROR:", str(e))

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create sale",
        )


# =================================================
# GET SINGLE SALE
# =================================================
@router.get("/{sale_id}")
@require_permissions("sale.view")
async def get_sale(
    sale_id: int,
    request: Request,
    db=Depends(get_db),
):
    print("\n========== GET SALE ==========")
    print("🔥 SALE ID:", sale_id)
    print("🔥 USER:", getattr(request.state, "user", None))

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