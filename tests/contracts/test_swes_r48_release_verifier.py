import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from restaurant.customer_channel.swes_r48_cc_event_validation import CCEventRejected
from restaurant.customer_channel.swes_r48_protected_composition import (
    R48ProtectedAdmission,
)
from restaurant.customer_channel.swes_r48_release_verifier import (
    SignedR48Release,
    verify_signed_release,
)


def release():
    now = datetime.now(timezone.utc)
    adm = R48ProtectedAdmission("a"*40, 910001, 5, "wnd-austin-track-a-ia0", now + timedelta(minutes=10))
    unsigned = SignedR48Release(adm, "srv-db3vej67bikc73ai2080", "wnd-xafpay-demo-austin-backend.onrender.com", now, b"")
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signed = replace(unsigned, signature=key.sign(unsigned.canonical_bytes()))
    env = {"RENDER":"true", "RENDER_SERVICE_ID":signed.service_id,
           "RENDER_EXTERNAL_HOSTNAME":signed.hostname, "RENDER_GIT_COMMIT":adm.source_commit}
    return signed, public, hashlib.sha256(public).hexdigest(), env


def test_signed_exact_release():
    grant, pub, pin, env = release()
    assert verify_signed_release(grant=grant, public_key=pub, externally_pinned_digest=pin, environment=env)


@pytest.mark.parametrize("wrong", ["pin", "commit", "service", "signature"])
def test_wrong_release_fails(wrong):
    grant, pub, pin, env = release()
    if wrong == "pin": pin = "0"*64
    if wrong == "commit": env["RENDER_GIT_COMMIT"] = "b"*40
    if wrong == "service": env["RENDER_SERVICE_ID"] = "wrong"
    if wrong == "signature": grant = replace(grant, signature=b"0"*64)
    with pytest.raises(CCEventRejected):
        verify_signed_release(grant=grant, public_key=pub, externally_pinned_digest=pin, environment=env)
