from fastapi import APIRouter, Request, Header, HTTPException, Depends
from starlette.requests import ClientDisconnect
import hmac
import hashlib
import json
from typing import Optional
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from database import get_db
from core.domain.payments.service import PaymentService, WebhookEvent

router = APIRouter()

SHARED_SECRET = "dev_shared_secret_change_me"


@router.post("/xafpay/webhook")
async def xafpay_webhook(
    request: Request,
    x_xafpay_signature: Optional[str] = Header(None),
    x_xafpay_event_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    # -------------------------------------------------
    # Safely read request body
    # -------------------------------------------------
    try:
        raw_body = await request.body()
    except ClientDisconnect:
        print("⚠️ Client disconnected during webhook read")
        return {"status": "ignored"}

    body_str = raw_body.decode()

    # -------------------------------------------------
    # Verify signature
    # -------------------------------------------------
    if not x_xafpay_signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    expected_signature = hmac.new(
        SHARED_SECRET.encode(),
        body_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, x_xafpay_signature):
        print("❌ Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # -------------------------------------------------
    # Parse JSON safely
    # -------------------------------------------------
    try:
        payload = json.loads(body_str)
    except json.JSONDecodeError:
        print("❌ Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    print("✅ XAFPay Webhook Received")
    print("Event ID:", x_xafpay_event_id)
    print("Payload:", payload)

    # -------------------------------------------------
    # Normalize + Apply Business Logic
    # -------------------------------------------------
    try:
        tenant_id = 2  # TODO: replace with proper tenant resolution

        gateway_intent_id = payload.get("gateway_intent_id")
        if not gateway_intent_id:
            raise ValueError("Missing gateway_intent_id")

        raw_status = (payload.get("status") or "").upper()

        # Normalize status
        if raw_status in ("SUCCEEDED", "SUCCESS", "PAID"):
            normalized_status = "SUCCEEDED"
        elif raw_status in ("FAILED", "ERROR"):
            normalized_status = "FAILED"
        else:
            normalized_status = raw_status or "UNKNOWN"

        # Safe Decimal conversion
        try:
            amount = Decimal(str(payload.get("amount") or "0"))
        except (InvalidOperation, TypeError):
            amount = Decimal("0")

        currency = payload.get("currency") or "XAF"
        provider = payload.get("provider") or "unknown"

        event = WebhookEvent(
            event=payload.get("event") or "payment.unknown",
            status=normalized_status,
            amount=amount,
            currency=currency,
            provider=provider,
            gateway_intent_id=gateway_intent_id,
            callback_reference=payload.get("callback_reference")
            or (x_xafpay_event_id or ""),
            merchant_reference=payload.get("merchant_reference"),
            provider_reference=payload.get("provider_reference"),
        )

        # -------------------------------------------------
        # Apply settlement logic
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