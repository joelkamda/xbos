from datetime import datetime, timedelta, timezone

import pytest
from restaurant.customer_channel.swes_r48_cc_attestation_verifier import (
    verify_attestation_response,
)
from restaurant.customer_channel.swes_r48_cc_event_validation import CCEventRejected


def records():
    now = datetime.now(timezone.utc)
    event = {
        "event_id": "a" * 64,
        "correlation_ref": "11111111-1111-4111-8111-111111111111",
        "receipt": {"reference": "b" * 64, "payload_sha256": "c" * 64},
        "server_received_at_utc": (now - timedelta(seconds=15)).isoformat(),
        "delivered_before_utc": (now + timedelta(minutes=4)).isoformat(),
    }
    attestation = {
        "schema": "xafpay.cc.restricted_receipt_attestation.v1",
        "status": "processed_receipt_verified",
        "event_id": event["event_id"],
        "correlation_ref": event["correlation_ref"],
        "receipt_reference": event["receipt"]["reference"],
        "payload_sha256": event["receipt"]["payload_sha256"],
        "first_processed_attempt": 1,
        "server_received_at_utc": event["server_received_at_utc"],
        "sender_provenance_attested": False,
        "customer_authenticated_external": False,
    }
    return event, attestation


def test_current_cc_response_never_unlocks_writer():
    event, result = records()
    with pytest.raises(CCEventRejected, match="SENDER_PROVENANCE"):
        verify_attestation_response(event, result, transport_authenticated=True)


def test_untrusted_transport_rejected():
    event, result = records()
    result["sender_provenance_attested"] = True
    with pytest.raises(CCEventRejected, match="TRANSPORT"):
        verify_attestation_response(event, result, transport_authenticated=False)


@pytest.mark.parametrize("field,invalid", [
    ("event_id", "different"),
    ("correlation_ref", "different"),
    ("receipt_reference", "different"),
    ("payload_sha256", "different"),
    ("server_received_at_utc", "2026-01-01T00:00:00+00:00"),
])
def test_response_mismatch_rejected(field, invalid):
    event, result = records()
    result["sender_provenance_attested"] = True
    result[field] = invalid
    with pytest.raises(CCEventRejected):
        verify_attestation_response(event, result, transport_authenticated=True)


def test_attested_contract_shape_not_independent_proof():
    event, result = records()
    result["sender_provenance_attested"] = True
    assert verify_attestation_response(event, result, transport_authenticated=True)
