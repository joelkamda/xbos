from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from restaurant.customer_channel.swes_r48_cc_event_validation import CCEventRejected
from restaurant.customer_channel.swes_r48_ia0_writer import (
    VerifiedCCEvent,
    persist_verified_event,
)


def event(**changes):
    now=datetime.now(timezone.utc)
    values={
        "tenant_id":910001,"location_id":5,"event_id":"a"*64,
        "fingerprint":"b"*64,"sender_hmac":"c"*64,
        "receipt_reference":"d"*64,"correlation_ref":uuid4(),
        "received_at":now-timedelta(seconds=10),
        "expires_at":now+timedelta(minutes=3),
    }
    values.update(changes)
    return VerifiedCCEvent(**values)

def test_verifier_callbacks_required():
    with pytest.raises(CCEventRejected):
        persist_verified_event(None,event(),authorize_service=None,verify_cc_receipt=None)

@pytest.mark.parametrize("change", [
    {"tenant_id":2},{"location_id":7},{"event_id":"invalid"},
    {"expires_at":datetime(2025,1,1,tzinfo=timezone.utc)},
])
def test_invalid_scope_fails_before_verifier(change):
    with pytest.raises(CCEventRejected):
        persist_verified_event(None,event(**change),
                               authorize_service=lambda _:True,
                               verify_cc_receipt=lambda _:True)

def test_service_denied_before_receipt(monkeypatch):
    called=[]
    with pytest.raises(CCEventRejected,match="SERVICE_AUTH_FORBIDDEN"):
        persist_verified_event(None,event(),
            authorize_service=lambda _:False,
            verify_cc_receipt=lambda _:called.append(1))
    assert not called

def test_receipt_denied_before_repository(monkeypatch):
    with pytest.raises(CCEventRejected,match="RECEIPT_NOT_VERIFIED"):
        persist_verified_event(None,event(),
            authorize_service=lambda _:True,verify_cc_receipt=lambda _:False)
