from fastapi import APIRouter, Request, Depends
from typing import Dict, Any
from sqlalchemy.orm import Session

from core.api.payments.payments_controller import PaymentsController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Payments"])
controller = PaymentsController()


# -------------------------------------------------
# List payments (for Payments dashboard)
# -------------------------------------------------

@router.get("/")
@require_permissions("payments.view")
async def list_payments(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return recent payments for the Payments dashboard.

    Supports tenant + branch isolation through request context.
    """
    return await controller.list_payments(
        request=request,
        db=db,
    )


# -------------------------------------------------
# Get single payment
# -------------------------------------------------

@router.get("/{payment_id}")
@require_permissions("payments.view")
async def get_payment(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return a single payment with attempts and settlement info.
    """
    return await controller.get_payment(
        payment_id=payment_id,
        request=request,
        db=db,
    )


# -------------------------------------------------
# XafPay payment initialization
# -------------------------------------------------

@router.post("/xafpay/init")
@require_permissions("payments.receive")
async def init_xafpay_payment(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Start XafPay payment flow.

    Creates or reuses a PaymentIntent
    and returns a gateway checkout URL.
    """
    return await controller.init_xafpay_payment(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# POS Settlement (Cash / MTN / Orange / Split / Unpaid)
# -------------------------------------------------

@router.post("/pos/settle")
@require_permissions("payments.receive")
async def pos_settle(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Manual POS settlement.

    Delegates all financial logic to PaymentService
    through the controller.
    """
    return await controller.pos_settle(
        request=request,
        payload=payload,
        db=db,
    )