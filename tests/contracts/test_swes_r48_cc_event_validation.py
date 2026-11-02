from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from restaurant.customer_channel.swes_r48_cc_event_validation import (
    SCHEMA,
    CCEventRejected,
    validate_cc_event,
)

NOW=datetime(2026,11,2,8,0,tzinfo=timezone.utc)
EVENT_ID="a"*64
CORRELATION=str(uuid4())
def event():
    e={
        "schema":SCHEMA,"tenant_id":910001,
        "merchant_public_id":"4b196022-55a1-548c-b122-f1f9e4b78bea",
        "audience":"wnd-austin-track-a-ia0",
        "context_purpose":"restaurant.customer_channel.checkout",
        "channel":"twilio_whatsapp","event_id":EVENT_ID,
        "correlation_ref":CORRELATION,
        "server_received_at_utc":(NOW-timedelta(seconds=10)).isoformat(),
        "delivered_before_utc":(NOW+timedelta(minutes=4)).isoformat(),
        "sender_reference":{"scheme":"cc_locator_hmac_sha256_v1","version":"v1","value":"b"*64},
        "receipt":{"authority":"xafpay.cc.hosted_pg17_signed_twilio_receipt","processing_state":"processed",
                   "processing_attempt":1,"reference":"c"*64,"payload_sha256":"d"*64},
        "verification":{"source":"twilio_signed_webhook_verified_by_cc",
                        "provider_signature_verified":True,"sender_enrolled_test_only":True,
                        "identity_resolution_state":"channel_identified","verification_state":"channel_verified",
                        "authentication_authority":None,"authentication_reference":None}
    }
    return e
def headers():
    return {"X-CC-Event-Id":EVENT_ID,"X-Idempotency-Key":EVENT_ID,
            "X-Correlation-Ref":CORRELATION,"X-CC-Event-Schema":SCHEMA}
def test_shape_only_does_not_assert_authentication():
    assert validate_cc_event(event(),headers(),now=NOW)==(EVENT_ID,CORRELATION)
@pytest.mark.parametrize("field,value", [
    ("tenant_id",2),("merchant_public_id","4b196022-65a1-548c-b122-f1f9e4b78bea"),
    ("audience","invalid"),("context_purpose","other"),("event_id","invalid"),
    ("channel","sms"),("delivered_before_utc","2026-11-01T00:00:00+00:00")
])
def test_fail_closed_fields(field,value):
    e=event()
    e[field]=value
    with pytest.raises(CCEventRejected):
        validate_cc_event(e,headers(),now=NOW)
def test_claimed_authenticated_external_rejected():
    e=event()
    e["verification"]["authentication_reference"]="fake"
    with pytest.raises(CCEventRejected):
        validate_cc_event(e,headers(),now=NOW)
def test_header_binding_required():
    h=headers()
    h["X-Idempotency-Key"]="different"
    with pytest.raises(CCEventRejected):
        validate_cc_event(event(),h,now=NOW)
