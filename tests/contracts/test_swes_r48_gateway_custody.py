"""R48 WND protected one-use Gateway checkout custody (TEST-only).

Synthetic signer/recipient keys are generated in memory, never in files.
No Gateway credential created in live systems or logged by these tests.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import get_db
from restaurant.customer_channel import swes_r48_gateway_custody as m


@pytest.fixture(scope="module")
def keys():
    signer = ed25519.Ed25519PrivateKey.generate()
    rsa_priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    signer_pub = signer.public_key()
    pub = signer_pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return signer, rsa_priv, hashlib.sha256(pub).hexdigest()


def make_grant(keys, *, now=None):
    _, rsa_priv, digest = keys
    now = now or datetime.now(timezone.utc)
    return m.PinnedGatewayCustodyAdmission(
        signer_public_key=keys[0].public_key(),
        signer_public_sha256=digest,
        recipient_private_key=rsa_priv,
        approved_nonce=uuid4(),
        wnd_source_sha="a" * 40,
        gateway_source_sha="b" * 40,
        approved_until_utc=now + timedelta(hours=1),
    )


def env(grant, **updates):
    fields = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": m.SERVICE,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": "wnd-xafpay-demo-austin-backend.onrender.com",
        "RENDER_GIT_BRANCH": m.EXPECTED_BRANCH,
        "RENDER_GIT_COMMIT": grant.wnd_source_sha,
        "XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED": "1",
        m.FLAG: "1",
    }
    fields.update(updates)
    return fields


def sealed(keys, grant, *, now=None, token=None, **header_changes):
    now = now or datetime.now(timezone.utc)
    token = token or "xps_synthetic.only-for-memory-tests"
    h = {
        "schema": m.SCHEMA,
        "tenant_id": 910001,
        "location_id": 5,
        "merchant_public_id": m.MERCHANT,
        "gateway_merchant_id": m.GATEWAY_MERCHANT,
        "gateway_source_sha": grant.gateway_source_sha,
        "wnd_source_sha": grant.wnd_source_sha,
        "credential_id": str(uuid4()),
        "nonce": str(grant.approved_nonce),
        "audience": "xafpay-gateway-v2",
        "scopes": list(m.SCOPE),
        "environment": "staging",
        "issued_at_utc": now.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "credential_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }
    h.update(header_changes)
    encrypted = grant.recipient_private_key.public_key().encrypt(
        token.encode(), padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(), label=None,
        ),
    )
    sign = keys[0].sign(m._canonical(h) + b"." + encrypted)
    return {
        "header": h,
        "ciphertext_b64": base64.b64encode(encrypted).decode(),
        "signature_b64": base64.b64encode(sign).decode(),
    }


def test_default_off_never_mounts_no_issuer_or_runtime(keys):
    grant = make_grant(keys)
    app = FastAPI()
    assert m.install_signed_gateway_custody_receiver(
        app, admission=grant, environ=env(grant, **{m.FLAG: "0"})
    ) is False
    assert m.ENDPOINT not in [r.path for r in app.routes]
    assert not hasattr(app.state, "wnd_gateway_checkout_runtime")


@pytest.mark.parametrize("change", [
    {m.FLAG: "1", "RENDER_GIT_COMMIT": "c" * 40},
    {m.FLAG: "1", "RENDER_SERVICE_ID": "different"},
    {m.FLAG: "1", "RENDER_SERVICE_TYPE": "worker"},
    {m.FLAG: "1", "XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED": "0"},
    {m.FLAG: "1", "RENDER_GIT_BRANCH": "main"},
])
def test_wrong_runtime_source_scope_fails_closed(keys, change):
    grant = make_grant(keys)
    app = FastAPI()
    with pytest.raises(m.CustodyDenied):
        m.install_signed_gateway_custody_receiver(
            app, admission=grant, environ=env(grant, **change),
        )
    assert m.ENDPOINT not in [r.path for r in app.routes]


def test_pcr_pinned_signer_and_operator_nonce_mandatory(keys):
    grant = make_grant(keys)
    with pytest.raises(m.CustodyDenied):
        replace(grant, signer_public_sha256="c" * 64).validate()
    with pytest.raises(m.CustodyDenied):
        replace(grant, approved_nonce=UUID(int=0)).validate()
    with pytest.raises(m.CustodyDenied):
        replace(grant, gateway_source_sha="not-hex").validate()
    with pytest.raises(m.CustodyDenied):
        replace(grant, approved_until_utc=datetime.now(timezone.utc)-timedelta(seconds=1)).validate()


def test_signed_sealed_envelope_valid_and_never_returns_plaintext(keys):
    grant = make_grant(keys)
    now = datetime.now(timezone.utc)
    envelope = sealed(keys, grant, now=now)
    token, credential_id, nonce, expires = m.verify_sealed_gateway_checkout(
        envelope, admission=grant, now=now
    )
    assert token.startswith("xps_")
    assert credential_id == UUID(envelope["header"]["credential_id"])
    assert nonce == str(grant.approved_nonce)
    assert expires > now
    assert token not in repr(envelope)


@pytest.mark.parametrize("bad", [
    {"tenant_id": 2},
    {"location_id": 1},
    {"merchant_public_id": str(uuid4())},
    {"gateway_merchant_id": "mch_wrong"},
    {"audience": "some-other-api"},
    {"environment": "production"},
    {"scopes": ["checkout:create", "transfer:create"]},
    {"wnd_source_sha": "f" * 40},
    {"gateway_source_sha": "f" * 40},
    {"nonce": str(uuid4())},
    {"credential_sha256": "0" * 64},
])
def test_wrong_signed_target_never_decrypts(keys, bad):
    grant = make_grant(keys)
    now = datetime.now(timezone.utc)
    envelope = sealed(keys, grant, now=now, **bad)
    with pytest.raises(m.CustodyDenied):
        m.verify_sealed_gateway_checkout(envelope, admission=grant, now=now)


def test_signature_tampering_rejected(keys):
    grant = make_grant(keys)
    now = datetime.now(timezone.utc)
    e = sealed(keys, grant, now=now)
    e["signature_b64"] = base64.b64encode(b"a" * 64).decode()
    with pytest.raises(m.CustodyDenied):
        m.verify_sealed_gateway_checkout(e, admission=grant, now=now)


def test_expired_and_late_delivery_rejected(keys):
    grant = make_grant(keys)
    now = datetime.now(timezone.utc)
    e = sealed(keys, grant, now=now)
    with pytest.raises(m.CustodyDenied):
        m.verify_sealed_gateway_checkout(e, admission=grant, now=now + timedelta(minutes=2, seconds=1))
    with pytest.raises(m.CustodyDenied):
        m.verify_sealed_gateway_checkout(e, admission=grant, now=now + timedelta(minutes=31))


class Rows:
    def __init__(self, value): self.value = value
    def scalar_one(self): return self.value
    def scalar(self): return self.value


class FakeDB:
    def __init__(self):
        self.used = set()
        self.pending = set()
        self.fail_commit = False
        self.commits = 0
        self.rollbacks = 0
    def execute(self, sql, args=None):
        s = str(sql)
        if "current_database()" in s:
            return Rows(m.DB_NAME)
        if "FROM public.r1_restaurant_orders" in s:
            return Rows(1)
        if "FROM public.r1_restaurant_commands" in s:
            return Rows(int(args["key"] in self.used))
        if "INSERT INTO public.r1_restaurant_commands" in s:
            nonce = args["key"]
            if nonce in self.used or nonce in self.pending:
                return Rows(None)
            self.pending.add(nonce)
            return Rows(11)
        raise AssertionError("query_not_expected")
    def commit(self):
        if self.fail_commit:
            raise RuntimeError("synthetic_test_commit_failure")
        self.commits += 1
        self.used.update(self.pending)
        self.pending.clear()
    def rollback(self):
        self.rollbacks += 1
        self.pending.clear()


def test_real_receiver_accepts_once_and_installs_trusted_runtime(keys):
    grant = make_grant(keys)
    app = FastAPI()
    db = FakeDB()
    assert m.install_signed_gateway_custody_receiver(
        app, admission=grant, environ=env(grant)
    )
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    envelope = sealed(keys, grant)
    response = client.post(m.ENDPOINT, json=envelope)
    assert response.status_code == 202
    assert response.json()["state"] == "ACCEPTED"
    assert "xps_" not in response.text
    runtime = app.state.wnd_gateway_checkout_runtime
    assert runtime.binding.tenant_id == 910001
    assert runtime.binding.gateway_merchant_id == m.GATEWAY_MERCHANT
    assert isinstance(runtime.client, m.ExpiringGatewayCheckoutClient)
    assert db.commits == 1
    again = client.post(m.ENDPOINT, json=envelope)
    assert again.status_code == 403
    assert db.commits == 1


def test_restart_never_reactivates_or_replays_consumed_gateway_custody(keys):
    """A process restart cannot silently restore temporary checkout authority."""
    grant = make_grant(keys)
    db = FakeDB()
    first = FastAPI()
    assert m.install_signed_gateway_custody_receiver(
        first, admission=grant, environ=env(grant)
    )
    first.dependency_overrides[get_db] = lambda: db
    envelope = sealed(keys, grant)
    assert TestClient(first).post(m.ENDPOINT, json=envelope).status_code == 202
    assert db.commits == 1
    assert hasattr(first.state, "wnd_gateway_checkout_runtime")

    # A new in-process application receives the same durable simulated DB,
    # but no bearer/session or runtime is silently resurrected from it.
    restarted = FastAPI()
    assert m.install_signed_gateway_custody_receiver(
        restarted, admission=grant, environ=env(grant)
    )
    restarted.dependency_overrides[get_db] = lambda: db
    assert not hasattr(restarted.state, "wnd_gateway_checkout_runtime")
    replay = TestClient(restarted).post(m.ENDPOINT, json=envelope)
    assert replay.status_code == 403
    assert db.commits == 1
    assert not hasattr(restarted.state, "wnd_gateway_checkout_runtime")
    assert len(db.used) == 1


def test_wrong_signed_request_does_not_insert_custody(keys):
    grant = make_grant(keys)
    app = FastAPI()
    db = FakeDB()
    m.install_signed_gateway_custody_receiver(app, admission=grant, environ=env(grant))
    app.dependency_overrides[get_db] = lambda: db
    reply = TestClient(app).post(m.ENDPOINT, json=sealed(keys, grant, tenant_id=2))
    assert reply.status_code == 403
    assert db.commits == 0
    assert db.used == set()


@pytest.mark.parametrize("failure", ["raise", "returns_false", "partial_runtime", "commit"])
def test_failed_runtime_never_consumes_custody_nonce_and_can_retry(
    keys, monkeypatch, failure
):
    grant = make_grant(keys)
    app, db = FastAPI(), FakeDB()
    assert m.install_signed_gateway_custody_receiver(
        app, admission=grant, environ=env(grant)
    )
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    envelope = sealed(keys, grant)
    original = m.install_staging_checkout_runtime

    if failure == "commit":
        db.fail_commit = True
    else:
        def broken_installer(app, **kw):
            if failure == "returns_false":
                return False
            if failure == "partial_runtime":
                app.state.wnd_gateway_checkout_runtime = object()
            raise RuntimeError("synthetic_injected_install_failure")
        monkeypatch.setattr(m, "install_staging_checkout_runtime", broken_installer)

    first = client.post(m.ENDPOINT, json=envelope)
    assert first.status_code == 403
    assert db.commits == 0
    assert db.rollbacks >= 1
    assert db.used == set()
    assert db.pending == set()
    assert not hasattr(app.state, "wnd_gateway_checkout_runtime")

    # Same signed envelope and nonce must remain usable after the failure.
    monkeypatch.setattr(m, "install_staging_checkout_runtime", original)
    db.fail_commit = False
    second = client.post(m.ENDPOINT, json=envelope)
    assert second.status_code == 202
    assert db.commits == 1
    assert len(db.used) == 1
    assert hasattr(app.state, "wnd_gateway_checkout_runtime")
    third = client.post(m.ENDPOINT, json=envelope)
    assert third.status_code == 403
    assert db.commits == 1
