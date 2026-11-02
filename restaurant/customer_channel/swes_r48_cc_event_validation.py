"""R48 TEST-only CC -> WND ingress shape gate; not authentication or a route.

Call ONLY after source-independent service bearer authorization and CC receipt
attestation. Untrusted JSON cannot prove a Twilio signature or a customer login.
"""
from datetime import datetime, timezone
from uuid import UUID

TENANT = 910001
MERCHANT = "4b196022-55a1-548c-b122-f1f9e4b78bea"
SCHEMA = "xafpay.cc.signed_twilio_ia0_ingress.v1"
AUDIENCE = "wnd-austin-track-a-ia0"
PURPOSE = "restaurant.customer_channel.checkout"

class CCEventRejected(ValueError):
    pass

def validate_cc_event(event: dict, headers: dict, *, now: datetime | None = None) -> tuple[str, str]:
    """Return (event_id, correlation_ref) after restrictive structural checks.

    This is NOT sufficient to admit an event: service authorization and trusted
    provider receipt provenance must be established independently.
    """
    if type(event) is not dict or type(headers) is not dict:
        raise CCEventRejected("INVALID_EVENT")
    if (event.get("schema") != SCHEMA
        or type(event.get("tenant_id")) is not int
        or event["tenant_id"] != TENANT
        or event.get("merchant_public_id") != MERCHANT
        or event.get("audience") != AUDIENCE
        or event.get("context_purpose") != PURPOSE
        or event.get("channel") != "twilio_whatsapp"):
        raise CCEventRejected("SCOPE_MISMATCH")
    event_id = event.get("event_id")
    if (not isinstance(event_id, str) or len(event_id) != 64
        or any(c not in "0123456789abcdef" for c in event_id)):
        raise CCEventRejected("EVENT_ID_INVALID")
    try:
        correlation = str(UUID(str(event["correlation_ref"])))
        received = datetime.fromisoformat(event["server_received_at_utc"].replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(event["delivered_before_utc"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise CCEventRejected("TIME_OR_CORRELATION_INVALID") from exc
    current = now or datetime.now(timezone.utc)
    if (received.tzinfo is None or expiry.tzinfo is None
        or current.tzinfo is None
        or not (received <= current < expiry <= received + __import__("datetime").timedelta(minutes=5))):
        raise CCEventRejected("EVENT_EXPIRED_OR_INVALID")
    if (headers.get("X-CC-Event-Id") != event_id
        or headers.get("X-Idempotency-Key") != event_id
        or headers.get("X-Correlation-Ref") != correlation
        or headers.get("X-CC-Event-Schema") != SCHEMA):
        raise CCEventRejected("HEADER_BINDING_INVALID")
    reference = event.get("sender_reference")
    if (not isinstance(reference, dict)
        or reference.get("scheme") != "cc_locator_hmac_sha256_v1"
        or not isinstance(reference.get("version"), str)
        or not reference.get("version")
        or not isinstance(reference.get("value"), str)
        or len(reference["value"]) != 64
        or any(c not in "0123456789abcdef" for c in reference["value"])):
        raise CCEventRejected("SENDER_REFERENCE_INVALID")
    receipt = event.get("receipt")
    verification = event.get("verification")
    if (not isinstance(receipt, dict)
        or receipt.get("authority") != "xafpay.cc.hosted_pg17_signed_twilio_receipt"
        or receipt.get("processing_state") != "processed"
        or type(receipt.get("processing_attempt")) is not int
        or receipt["processing_attempt"] != 1
        or not isinstance(receipt.get("reference"), str)
        or not isinstance(receipt.get("payload_sha256"), str)
        or not isinstance(verification, dict)
        or verification.get("source") != "twilio_signed_webhook_verified_by_cc"
        or verification.get("provider_signature_verified") is not True
        or verification.get("sender_enrolled_test_only") is not True
        or verification.get("identity_resolution_state") != "channel_identified"
        or verification.get("verification_state") != "channel_verified"
        or verification.get("authentication_authority") is not None
        or verification.get("authentication_reference") is not None):
        raise CCEventRejected("PROVENANCE_CLAIM_INVALID")
    # These are asserted CLAIMS only. A privileged WND adapter must compare
    # them with independently authenticated CC evidence before any IA0 write.
    return event_id, correlation
