"""Verified signed admission reaches protected app; invalid evidence never does."""
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from restaurant.customer_channel.swes_r48_cc_event_validation import CCEventRejected
from restaurant.customer_channel.swes_r48_protected_composition import (
    R48ProtectedAdmission,
    compose_r48_signed_release_app,
)
from restaurant.customer_channel.swes_r48_release_verifier import SignedR48Release

PATH = "/internal/swes/track-a/test-only/ia0-events"


def signed():
    now = datetime.now(timezone.utc)
    grant = SignedR48Release(
        R48ProtectedAdmission("a" * 40, 910001, 5, "wnd-austin-track-a-ia0",
                              now + timedelta(minutes=10)),
        "srv-db3vej67bikc73ai2080", "wnd-xafpay-demo-austin-backend.onrender.com", now, b"",
    )
    key = Ed25519PrivateKey.generate()
    grant = replace(grant, signature=key.sign(grant.canonical_bytes()))
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    env = {"RENDER": "true", "RENDER_SERVICE_ID": grant.service_id,
           "RENDER_EXTERNAL_HOSTNAME": grant.hostname, "RENDER_GIT_COMMIT": "a" * 40}
    return grant, public, hashlib.sha256(public).hexdigest(), env


def test_real_signed_release_installs_real_https_attestor():
    grant, pub, pin, env = signed()
    app = compose_r48_signed_release_app(
        grant=grant, signer_public_key=pub,
        independently_pinned_digest=pin, hosted_environment=env,
    )
    assert sum(route.path == PATH for route in app.routes) == 1
    assert app.state.swes_r48_cc_receipt_attestor.__name__ == "attest_cc_signed_sender"


@pytest.mark.parametrize("failure", ["pin", "wrong_commit", "wrong_scope", "signature"])
def test_invalid_signer_or_scope_never_installs(failure):
    grant, pub, pin, env = signed()
    if failure == "pin": pin = "0" * 64
    elif failure == "wrong_commit": env["RENDER_GIT_COMMIT"] = "b" * 40
    elif failure == "wrong_scope":
        grant = replace(grant, admission=replace(grant.admission, tenant_id=2))
    else: grant = replace(grant, signature=b"0" * 64)
    with pytest.raises(CCEventRejected):
        compose_r48_signed_release_app(
            grant=grant, signer_public_key=pub,
            independently_pinned_digest=pin, hosted_environment=env,
        )
