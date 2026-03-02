from fastapi import APIRouter, Request, Depends, HTTPException, Header
from typing import Dict, Any, Optional
from decimal import Decimal
import hmac
import hashlib
import json

from sqlalchemy.orm import Session

from core.api.payments.payments_controller import PaymentsController
from core.domain.payments.service import PaymentService, WebhookEvent
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
# 🚨 XAFPay Webhook (INTENT-BASED ARCHITECTURE)
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

    Responsibilities:
    - Verify signature
    - Normalize payload
    - Apply settlement via PaymentService.apply_gateway_webhook
    - NEVER use RBAC
    """

    # -------------------------------------------------
    # Safely read body
    # -------------------------------------------------

    try:
        raw_body = await request.body()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

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

    # -------------------------------------------------
    # Parse JSON safely
    # -------------------------------------------------

    try:
        payload = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    print("✅ XAFPay Webhook Received")
    print("Event ID:", x_xafpay_event_id)
    print("Payload:", payload)

    # -------------------------------------------------
    # Normalize to WebhookEvent
    # -------------------------------------------------

    try:
        tenant_id = 2  # TODO: Replace with proper tenant resolution

        gateway_intent_id = payload.get("gateway_intent_id")
        if not gateway_intent_id:
            raise ValueError("Missing gateway_intent_id")

        event = WebhookEvent(
            event=payload.get("event") or "payment.unknown",
            status=payload.get("status") or "",
            amount=Decimal(str(payload.get("amount") or "0")),
            currency=payload.get("currency") or "XAF",
            provider=payload.get("provider") or "unknown",
            gateway_intent_id=gateway_intent_id,
            callback_reference=payload.get("callback_reference")
                or (x_xafpay_event_id or ""),
            merchant_reference=payload.get("merchant_reference"),
            provider_reference=payload.get("provider_reference"),
        )

        # -------------------------------------------------
        # Apply settlement
        # -------------------------------------------------

        intent = PaymentService.apply_gateway_webhook(
            db,
            tenant_id=tenant_id,
            event=event,
        )

        db.commit()

        return {
            "status": "accepted",
            "intent_id": intent.id,
            "gateway_intent_id": gateway_intent_id,
        }

    except Exception as e:
        db.rollback()
        print("❌ Webhook processing error:", str(e))
        raise HTTPException(status_code=500, detail="Webhook processing failed")


# -------------------------------------------------
# 🚫 Legacy manual success/failure endpoints removed
# (Intent architecture handles settlement via webhook)
# -------------------------------------------------