"""Validate independently authenticated CC receipt attestations; fail closed.

Use only on a response fetched from the pinned CC staging HTTPS host using a
separate server-owned WND-to-CC service credential. Untrusted event JSON, or a
caller supplied "attested" flag, does not constitute independent provenance.
"""
from datetime import datetime, timezone
from hmac import compare_digest

from .swes_r48_cc_event_validation import CCEventRejected

ATTEST_SCHEMA = "xafpay.cc.restricted_receipt_attestation.v1"


def verify_attestation_response(event: dict, response: dict, *,
                                transport_authenticated: bool,
                                now: datetime | None = None) -> bool:
    """Exact response binding; never accept receipt-only as sender proof."""
    if transport_authenticated is not True:
        raise CCEventRejected("CC_ATTESTATION_TRANSPORT_UNTRUSTED")
    if not isinstance(event, dict) or not isinstance(response, dict):
        raise CCEventRejected("CC_ATTESTATION_INVALID")
    receipt = event.get("receipt")
    if not isinstance(receipt, dict):
        raise CCEventRejected("CC_ATTESTATION_INVALID")
    expected = {
        "event_id": event.get("event_id"),
        "correlation_ref": event.get("correlation_ref"),
        "receipt_reference": receipt.get("reference"),
        "payload_sha256": receipt.get("payload_sha256"),
    }
    if (response.get("schema") != ATTEST_SCHEMA
        or response.get("status") != "processed_receipt_verified"
        or type(response.get("first_processed_attempt")) is not int
        or response.get("first_processed_attempt") != 1
        or response.get("customer_authenticated_external") is not False):
        raise CCEventRejected("CC_ATTESTATION_UNQUALIFIED")
    for field, value in expected.items():
        if not isinstance(value, str) or not isinstance(response.get(field), str):
            raise CCEventRejected("CC_ATTESTATION_BINDING_MISMATCH")
        if not compare_digest(value, response[field]):
            raise CCEventRejected("CC_ATTESTATION_BINDING_MISMATCH")
    try:
        event_time = datetime.fromisoformat(
            event["server_received_at_utc"].replace("Z", "+00:00")
        )
        attested_time = datetime.fromisoformat(
            response["server_received_at_utc"].replace("Z", "+00:00")
        )
        expiry = datetime.fromisoformat(
            event["delivered_before_utc"].replace("Z", "+00:00")
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CCEventRejected("CC_ATTESTATION_TIME_INVALID") from exc
    current = now or datetime.now(timezone.utc)
    if (any(x.tzinfo is None for x in (event_time, attested_time, expiry, current))
        or event_time != attested_time
        or not event_time <= current < expiry):
        raise CCEventRejected("CC_ATTESTATION_TIME_INVALID")
    # CC currently returns False because its existing processed-receipt row
    # does not durably bind the signed sender to the keyed sender reference.
    if response.get("sender_provenance_attested") is not True:
        raise CCEventRejected("CC_SENDER_PROVENANCE_NOT_ATTESTED")
    return True
