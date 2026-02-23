from fastapi import APIRouter, Request, Depends, HTTPException, Header
from typing import Dict, Any, Optional
import hmac
import hashlib
import json

from sqlalchemy.orm import Session

from core.api.payments.payments_controller import PaymentsController
from core.domain.payments.service import PaymentService
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Payments"])
controller = PaymentsController()

# -------------------------------------------------
# 🔐 Gateway Shared Secret (DEV)
# -------------------------------------------------

SHARED_SECRET = "dev_shared_secret_change_me"


# -------------------------------------------------
# Initialize XafPay payment
# -------------------------------------------------

@router.post("/xafpay/init")
@require_permissions("payments.receive")
async def init_xafpay_payment(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    return await controller.init_xafpay_payment(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# Cash payment (immediate settlement)
# -------------------------------------------------

@router.post("/cash/pay")
@require_permissions("payments.receive")
async def pay_cash(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    return await controller.pay_cash(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# 🚨 XAFPay Webhook (EXTERNAL SYSTEM — NO RBAC)
# -------------------------------------------------

@router.post("/xafpay/webhook")
async def xafpay_webhook(
    request: Request,
    x_xafpay_signature: Optional[str] = Header(None),
    x_xafpay_event_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """
    Called by XafPay Gateway worker.
    Must:
    - Verify signature
    - Update payment state
    - Never depend on RBAC
    """

    raw_body = await request.body()
    body_str = raw_body.decode()

    # -------------------------------------------------
    # 🔐 Verify signature
    # -------------------------------------------------

    if not x_xafpay_signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    expected_signature = hmac.new(
        SHARED_SECRET.encode(),
        body_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_xafpay_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(body_str)

    print("✅ XAFPay Webhook Received")
    print("Event ID:", x_xafpay_event_id)
    print("Payload:", payload)

    try:
        # DEV: Replace with proper tenant resolution later
        tenant_id = 2

        payment_id = int(payload["payment_id"])
        status = payload.get("status")
        gateway_reference = payload.get("provider_ref")
        callback_reference = payload.get("callback_reference")

        if status == "SUCCEEDED":
            PaymentService.mark_payment_success(
                db,
                tenant_id=tenant_id,
                payment_id=payment_id,
                gateway_reference=gateway_reference,
                callback_reference=callback_reference,
            )
        else:
            PaymentService.mark_payment_failed(
                db,
                tenant_id=tenant_id,
                payment_id=payment_id,
                gateway_reference=gateway_reference,
                callback_reference=callback_reference,
            )

        db.commit()

    except Exception as e:
        db.rollback()
        print("❌ Webhook processing error:", str(e))
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return {"status": "accepted"}


# -------------------------------------------------
# Manual success (internal use)
# -------------------------------------------------

@router.post("/success")
@require_permissions("payments.receive")
async def mark_payment_success(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    return await controller.mark_payment_success(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# Manual failure (internal use)
# -------------------------------------------------

@router.post("/failed")
@require_permissions("payments.receive")
async def mark_payment_failed(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    return await controller.mark_payment_failed(
        request=request,
        payload=payload,
        db=db,
    )
