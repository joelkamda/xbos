"""R48 WND mutual-authenticated readiness is secret-free and default-off."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_swes_r48_gateway_custody import FakeDB, env, make_grant

from database import get_db
from restaurant.customer_channel import swes_r48_gateway_custody as custody
from restaurant.customer_channel import swes_r48_gateway_readiness as ready


@pytest.fixture(scope="module")
def keys():
    signer = ed25519.Ed25519PrivateKey.generate()
    receiver = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    from cryptography.hazmat.primitives import serialization
    public = signer.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return signer, receiver, hashlib.sha256(public).hexdigest()


def challenge(grant, *, now=None, **updates):
    now = now or datetime.now(timezone.utc)
    req = {
        "schema": ready.REQUEST_SCHEMA,
        "nonce": str(grant.approved_nonce),
        "challenge_b64": base64.b64encode(b"Q" * 32).decode(),
        "issued_at_utc": now.isoformat().replace("+00:00", "Z"),
        "tenant_id": 910001,
        "location_id": 5,
        "merchant_public_id": custody.MERCHANT,
        "gateway_merchant_id": custody.GATEWAY_MERCHANT,
        "wnd_source_sha": grant.wnd_source_sha,
        "gateway_source_sha": grant.gateway_source_sha,
        "audience": "xafpay-gateway-v2",
        "environment": "staging",
    }
    req.update(updates)
    return req


def signed(keys, req):
    return base64.b64encode(
        keys[0].sign(ready._REQUEST_CONTEXT + custody._canonical(req))
    ).decode()


def test_proof_recipient_private_key_and_exact_source_scope(keys):
    grant = make_grant(keys)
    req = challenge(grant)
    response = ready.sign_readiness_proof(
        req, signature_b64=signed(keys, req),
        admission=grant, now=datetime.now(timezone.utc),
    )
    proof = response["proof"]
    assert proof["nonce"] == req["nonce"]
    assert proof["challenge_b64"] == req["challenge_b64"]
    assert proof["wnd_source_sha"] == grant.wnd_source_sha
    assert proof["gateway_source_sha"] == grant.gateway_source_sha
    assert proof["recipient_key_sha256"] == hashlib.sha256(
        ready.recipient_public_spki(grant)
    ).hexdigest()
    grant.recipient_private_key.public_key().verify(
        base64.b64decode(response["signature_b64"], validate=True),
        ready._PROOF_CONTEXT + custody._canonical(proof),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )


@pytest.mark.parametrize("wrong", [
    {"tenant_id": 2},
    {"location_id": 1},
    {"merchant_public_id": str(uuid4())},
    {"gateway_merchant_id": "mch_wrong"},
    {"environment": "production"},
    {"audience": "wrong"},
    {"wnd_source_sha": "f" * 40},
    {"gateway_source_sha": "f" * 40},
    {"nonce": str(uuid4())},
    {"challenge_b64": base64.b64encode(b"Q" * 10).decode()},
])
def test_bad_signed_readiness_is_denied(keys, wrong):
    grant = make_grant(keys)
    req = challenge(grant, **wrong)
    with pytest.raises(custody.CustodyDenied):
        ready.sign_readiness_proof(
            req, signature_b64=signed(keys, req), admission=grant,
            now=datetime.now(timezone.utc),
        )


def test_invalid_signature_and_stale_challenge_denied(keys):
    grant = make_grant(keys)
    now = datetime.now(timezone.utc)
    req = challenge(grant, now=now)
    with pytest.raises(custody.CustodyDenied):
        ready.sign_readiness_proof(
            req, signature_b64=base64.b64encode(b"X"*64).decode(),
            admission=grant, now=now,
        )
    with pytest.raises(custody.CustodyDenied):
        ready.sign_readiness_proof(
            req, signature_b64=signed(keys,req),
            admission=grant, now=now+timedelta(seconds=46),
        )


def test_live_shaped_readiness_route_requires_valid_gateway_signature(keys):
    grant = make_grant(keys)
    app = FastAPI()
    db = FakeDB()
    assert custody.install_signed_gateway_custody_receiver(
        app, admission=grant, environ=env(grant),
    ) is True
    app.dependency_overrides[get_db] = lambda: db
    req = challenge(grant)
    client = TestClient(app)
    denied = client.post(ready.PATH, json=req)
    assert denied.status_code == 403
    response = client.post(
        ready.PATH, json=req,
        headers={"X-R48-Gateway-Ready-Signature":signed(keys,req)},
    )
    assert response.status_code == 200
    assert response.json()["proof"]["nonce"] == str(grant.approved_nonce)
    assert response.json()["proof"]["recipient_key_sha256"] == hashlib.sha256(
        ready.recipient_public_spki(grant)
    ).hexdigest()
    assert db.commits == 0
    assert db.used == set()
    assert db.pending == set()
    # Successfully proven readiness is non-destructive; the same nonce is
    # reserved for the later authenticated actual encrypted delivery.


def test_readiness_is_denied_after_nonce_consumed(keys):
    grant = make_grant(keys)
    app, db = FastAPI(), FakeDB()
    assert custody.install_signed_gateway_custody_receiver(
        app, admission=grant, environ=env(grant),
    ) is True
    app.dependency_overrides[get_db] = lambda: db
    db.used.add("r48:gateway:checkout:" + str(grant.approved_nonce))
    req = challenge(grant)
    response = TestClient(app).post(
        ready.PATH, json=req,
        headers={"X-R48-Gateway-Ready-Signature":signed(keys,req)},
    )
    assert response.status_code == 403
    assert db.commits == 0
