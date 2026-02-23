from fastapi import APIRouter, Request, Header, HTTPException, Depends
import hmac
import hashlib
import json
from typing import Optional

from sqlalchemy.orm import Session

from database import get_db
from core.domain.payments.service import PaymentService

router = APIRouter()

SHARED_SECRET = "dev_shared_secret_change_me"


@router.post("/xafpay/webhook")
async def xafpay_webhook(
    request: Request,
    x_xafpay_signature: Optional[str] = Header(None),
    x_xafpay_event_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
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
        tenant_id = 2  # DEV: replace with proper tenant resolution later
        payment_id = int(payload["payment_id"])
        gateway_reference = payload.get("provider_ref")
        callback_reference = payload.get("callback_reference")

        if payload.get("status") == "SUCCEEDED":
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
