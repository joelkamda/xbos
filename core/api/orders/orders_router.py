# core/api/orders/orders_router.py

from fastapi import APIRouter, Request, Depends, Body, Query
from sqlalchemy.orm import Session

from database import get_db
from core.api.orders.orders_controller import OrdersController
from core.rbac.utils.permission_decorator import require_permissions

router = APIRouter(tags=["Orders"])
controller = OrdersController()


@router.post("/")
@require_permissions("order.create", "sale.create")
async def create_order(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    return await controller.create_order(request, payload, db)


@router.get("/")
@require_permissions("order.view")
async def list_orders(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.list_orders(request, db)



@router.get("/sale-fulfillment-modes")
@require_permissions("sale.view")
async def sale_fulfillment_modes(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return await controller.sale_fulfillment_modes(
        request,
        db=db,
        limit=limit,
    )


@router.get("/kitchen/history")
@require_permissions("order.view")
async def kitchen_history(
    request: Request,
    start: str = Query(...),
    end: str = Query(...),
    limit: int = Query(500, ge=1, le=2000),
):
    return await controller.kitchen_history(
        request,
        start=start,
        end=end,
        limit=limit,
    )


@router.get("/kitchen/item-summary")
@require_permissions("order.view")
async def kitchen_item_summary(
    request: Request,
    start: str = Query(...),
    end: str = Query(...),
    db: Session = Depends(get_db),
):
    return await controller.kitchen_item_summary(
        request,
        start=start,
        end=end,
        db=db,
    )


@router.get("/{order_id}")
@require_permissions("order.view")
async def get_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.get_order(request, order_id, db)


@router.patch("/{order_id}")
@require_permissions("order.update")
async def update_order(
    order_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    return await controller.update_order(request, order_id, payload, db)


# =====================================================
# UPDATE ITEM FULFILLMENT STATUS
# =====================================================
# Kitchen / prep workflow endpoint.
#
# Example:
# PATCH /kernel/orders/221/items/55/fulfillment-status
#
# Body:
# {
#   "status": "ready"
# }
# =====================================================

@router.patch("/{order_id}/items/{order_item_id}/fulfillment-status")
@require_permissions("order.update_status")
async def update_item_fulfillment_status(
    order_id: int,
    order_item_id: int,
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    return await controller.update_item_fulfillment_status(
        request=request,
        order_id=order_id,
        order_item_id=order_item_id,
        payload=payload,
        db=db,
    )


@router.post("/{order_id}/cancel")
@require_permissions("order.cancel", "order.update", "sale.cancel")
async def cancel_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.cancel_order(request, order_id, db)