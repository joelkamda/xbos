import hashlib
import hmac
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


WEBHOOK_PATH = "/kernel/payments/xafpay/webhook"
CALLBACK_AMOUNT = Decimal("3500.00")


def _signed_callback(payload, *, event_id):
    from core.api.xafpay_webhook import SHARED_SECRET

    raw_body = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    signature = hmac.new(
        SHARED_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return raw_body, {
        "Content-Type": "application/json",
        "X-XafPay-Signature": signature,
        "X-XafPay-Event-Id": event_id,
    }


def test_xafpay_webhook_is_not_public_in_legacy_middleware(client):
    gateway_intent_id = f"b1-webhook-public-gap-{uuid4().hex}"
    event_id = f"b1-webhook-event-{uuid4().hex}"

    raw_body, callback_headers = _signed_callback(
        {
            "event": "payment.updated",
            "status": "SUCCEEDED",
            "amount": float(CALLBACK_AMOUNT),
            "currency": "XAF",
            "provider": "xafpay",
            "gateway_intent_id": gateway_intent_id,
            "callback_reference": event_id,
        },
        event_id=event_id,
    )

    response = client.post(
        WEBHOOK_PATH,
        content=raw_body,
        headers=callback_headers,
    )

    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "Missing Authorization header"}


def test_authenticated_valid_xafpay_callback_exposes_missing_service_contract(
    client,
    auth_headers,
    wnd_test_identity,
):
    from core.domain.payments.service import PaymentService
    from database import SessionLocal

    gateway_intent_id = f"b1-webhook-gateway-{uuid4().hex}"
    callback_reference = f"b1-webhook-callback-{uuid4().hex}"
    intent_reference = f"b1-webhook-intent-{uuid4().hex}"

    db = SessionLocal()

    try:
        intent = PaymentService.init_intent(
            db,
            tenant_id=wnd_test_identity["tenant_id"],
            branch_id=wnd_test_identity["branch_id"],
            payable_type="manual",
            payable_id=0,
            currency="XAF",
            amount=CALLBACK_AMOUNT,
            channel="xafpay",
            created_by_user_id=wnd_test_identity["user_id"],
            client_reference=intent_reference,
            gateway_intent_id=gateway_intent_id,
            meta={
                "source": "track_b_webhook_characterization",
            },
        )
        db.commit()
        db.refresh(intent)
        intent_id = intent.id
    finally:
        db.close()

    payload = {
        "event": "payment.updated",
        "status": "SUCCEEDED",
        "amount": float(CALLBACK_AMOUNT),
        "currency": "XAF",
        "provider": "xafpay",
        "gateway_intent_id": gateway_intent_id,
        "callback_reference": callback_reference,
        "provider_reference": f"provider-{uuid4().hex}",
        "tenant_id": wnd_test_identity["tenant_id"],
    }

    raw_body, callback_headers = _signed_callback(
        payload,
        event_id=callback_reference,
    )

    response = client.post(
        WEBHOOK_PATH,
        content=raw_body,
        headers={
            **auth_headers,
            **callback_headers,
        },
    )

    assert not hasattr(PaymentService, "apply_gateway_webhook")
    assert response.status_code == 500, response.text
    assert response.json() == {"detail": "Webhook processing failed"}

    db = SessionLocal()

    try:
        intent_state = (
            db.execute(
                text(
                    """
                    SELECT status, amount, total_paid, balance_due
                    FROM payment_intents
                    WHERE id = :intent_id
                    """
                ),
                {"intent_id": intent_id},
            )
            .mappings()
            .one()
        )

        attempt_count = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM payment_attempts
                WHERE payment_intent_id = :intent_id
                """
            ),
            {"intent_id": intent_id},
        ).scalar_one()
    finally:
        db.close()

    assert intent_state["status"] == "pending"
    assert Decimal(str(intent_state["amount"])) == CALLBACK_AMOUNT
    assert Decimal(str(intent_state["total_paid"])) == Decimal("0")
    assert Decimal(str(intent_state["balance_due"])) == CALLBACK_AMOUNT
    assert attempt_count == 0
