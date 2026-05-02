from fastapi import APIRouter, Request, Depends, Body
from database import get_db

from core.api.orders.orders_controller import OrdersController

router = APIRouter(tags=["Orders"])
controller = OrdersController()


@router.post("/")
async def create_order(
    request: Request,
    payload: dict = Body(...),
    db=Depends(get_db),
):
    return await controller.create_order(request, payload, db)


@router.get("/")
async def list_orders(
    request: Request,
    db=Depends(get_db),
):
    return await controller.list_orders(request, db)


@router.get("/{order_id}")
async def get_order(
    order_id: int,
    request: Request,
    db=Depends(get_db),
):
    return await controller.get_order(request, order_id, db)


@router.patch("/{order_id}")
async def update_order(
    order_id: int,
    request: Request,
    payload: dict = Body(...),
    db=Depends(get_db),
):
    return await controller.update_order(request, order_id, payload, db)


@router.post("/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    request: Request,
    db=Depends(get_db),
):
    return await controller.cancel_order(request, order_id, db)