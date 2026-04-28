from fastapi import APIRouter, Request, Header, HTTPException, Depends
from starlette.requests import ClientDisconnect
import hmac
import hashlib
import json
from typing import Optional
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session
from sqlalchemy import select

from database import get_db
from core.domain.payments.service import PaymentService, WebhookEvent
from core.domain.payments.models import PaymentIntent
from core.domain.payments.repository import PaymentIntentRepository

router = APIRouter()

SHARED_SECRET = "dev_shared_secret_change_me"


@router.post("/xafpay/webhook")
async def xafpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_xafpay_signature: Optional[str] = Header(None),
    x_xafpay_event_id: Optional[str] = Header(None),
):
    # -------------------------------------------------
    # Read body safely
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

    try:
        # -------------------------------------------------
        # Extract fields
        # -------------------------------------------------
        gateway_intent_id = payload.get("gateway_intent_id") or payload.get("id")
        if not gateway_intent_id:
            raise ValueError("Missing gateway_intent_id")

        raw_status = str(payload.get("status") or "").upper()
        if raw_status in ("SUCCEEDED", "SUCCESS", "PAID"):
            normalized_status = "SUCCEEDED"
        elif raw_status in ("FAILED", "ERROR"):
            normalized_status = "FAILED"
        else:
            normalized_status = raw_status or "UNKNOWN"

        try:
            amount = Decimal(str(payload.get("amount") or "0"))
        except (InvalidOperation, TypeError):
            amount = Decimal("0")

        currency = payload.get("currency") or "XAF"
        provider = payload.get("provider") or "xafpay"

        callback_reference = (
            payload.get("callback_reference")
            or x_xafpay_event_id
            or gateway_intent_id
        )

        # -------------------------------------------------
        # Resolve intent WITHOUT guessing tenant_id
        # -------------------------------------------------
        intent = None

        # 1) If payload includes tenant_id, use the repository path
        payload_tenant_id = payload.get("tenant_id")
        if payload_tenant_id:
            intent = PaymentIntentRepository.get_by_gateway_id(
                db,
                tenant_id=int(payload_tenant_id),
                gateway_intent_id=str(gateway_intent_id),
            )

        # 2) Otherwise, lookup globally (authoritative) — NO DEFAULT TENANT
        if not intent:
            stmt = select(PaymentIntent).where(
                PaymentIntent.gateway_intent_id == str(gateway_intent_id)
            )
            intent = db.execute(stmt).scalar_one_or_none()

        if not intent:
            raise ValueError("PaymentIntent not found for gateway_intent_id")

        tenant_id = intent.tenant_id

        # -------------------------------------------------
        # Build WebhookEvent
        # -------------------------------------------------
        event = WebhookEvent(
            event=payload.get("event") or "payment.updated",
            status=normalized_status,
            amount=amount,
            currency=currency,
            provider=provider,
            gateway_intent_id=str(gateway_intent_id),
            callback_reference=str(callback_reference),
            merchant_reference=payload.get("merchant_reference"),
            provider_reference=payload.get("provider_reference"),
        )

        # -------------------------------------------------
        # Apply settlement (Financial Authority)
        # -------------------------------------------------
        updated_intent = PaymentService.apply_gateway_webhook(
            db,
            tenant_id=tenant_id,
            event=event,
        )

        db.commit()

        return {
            "status": "accepted",
            "intent_id": updated_intent.id,
            "tenant_id": tenant_id,
            "balance_due": float(updated_intent.balance_due),
        }

    except Exception as e:
        db.rollback()
        print("❌ Webhook processing error:", str(e))
        raise HTTPException(status_code=500, detail="Webhook processing failed")