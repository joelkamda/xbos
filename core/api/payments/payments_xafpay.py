from fastapi import APIRouter, Request, Header, HTTPException
import hmac
import hashlib
import json
from typing import Optional

router = APIRouter()


SHARED_SECRET = "dev_shared_secret_change_me"  # match DB


@router.post("/payments/xafpay/webhook")
async def xafpay_webhook(
    request: Request,
    x_xafpay_signature: Optional[str] = Header(None),
    x_xafpay_event_id: Optional[str] = Header(None),
):
    raw_body = await request.body()
    body_str = raw_body.decode()

    # 🔐 Verify signature
    expected_signature = hmac.new(
        SHARED_SECRET.encode(),
        body_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not x_xafpay_signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    if not hmac.compare_digest(expected_signature, x_xafpay_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = json.loads(body_str)

    print("✅ XAFPay Webhook Received")
    print("Event ID:", x_xafpay_event_id)
    print("Payload:", payload)

    # TODO:
    # - Confirm payment in XBOS
    # - Apply treasury append
    # - Mark order paid
    # - Ensure idempotency using callback_reference

    return {"status": "accepted"}
