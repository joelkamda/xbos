"""Isolated Track A first-IA0 route: source-grade tests, not hosted evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import get_db
from restaurant.customer_channel import swes_track_a_first_ia0_receiver as t
from restaurant.customer_channel.swes_r48_cc_event_validation import SCHEMA

NOW = datetime.now(timezone.utc)
EVENT = "a" * 64
FORM = "c" * 64
SENDER = "d" * 64
MERCHANT = "4b196022-55a1-548c-b122-f1f9e4b78bea"
CORRELATION = "c8aed62e-e458-4906-b5c7-559a01500002"
CONTEXT = "c8aed62e-e458-4906-b5c7-559a01500001"
SESSION = "c8aed62e-e458-4906-b5c7-559a01500003"
BEARER = "synthetic-local-tests-only-never-hosted-bearer"


class Scalars:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class DB:
    def __init__(self):
        self.writes = 0
        self.commits = 0
        self.rollbacks = 0
        self.binding_rows = [CONTEXT]
        self.last_sql = None

    def flush(self):
        self.writes += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def execute(self, sql, values):
        self.last_sql = (str(sql), dict(values))
        return Scalars(self.binding_rows)


def environment():
    return {
        "XAFPAY_SWES_TRACK_A_IA0_ENABLED": "1",
        "RENDER": "true",
        "RENDER_SERVICE_ID": "srv-db3vej67bikc73ai2080",
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": "wnd-xafpay-demo-austin-backend.onrender.com",
        "RENDER_GIT_BRANCH": "compat/wnd-demo-cc-r1-legacy-neutral-bridge",
        "RENDER_GIT_COMMIT": "b" * 40,
    }


def event():
    return {
        "schema": SCHEMA, "tenant_id": 910001,
        "merchant_public_id": MERCHANT,
        "audience": "wnd-austin-track-a-ia0",
        "context_purpose": "restaurant.customer_channel.checkout",
        "channel": "twilio_whatsapp",
        "event_id": EVENT, "correlation_ref": CORRELATION,
        "provider_message_id": "SM123456789",
        "sender_reference": {
            "scheme": "cc_locator_hmac_sha256_v1",
            "version": "test-v1", "value": SENDER,
        },
        "provider_endpoint_ref": "test-sandbox", "provider_account_ref": "test-account",
        "server_received_at_utc": (NOW - timedelta(seconds=3)).isoformat(),
        "delivered_before_utc": (NOW + timedelta(seconds=240)).isoformat(),
        "receipt": {
            "authority": "xafpay.cc.hosted_pg17_signed_twilio_receipt",
            "reference": "f" * 64, "payload_sha256": FORM,
            "processing_state": "processed", "processing_attempt": 1,
        },
        "verification": {
            "source": "twilio_signed_webhook_verified_by_cc",
            "provider_signature_verified": True,
            "sender_enrolled_test_only": True,
            "identity_resolution_state": "channel_identified",
            "verification_state": "channel_verified",
            "authentication_authority": None,
            "authentication_reference": None,
        },
    }


def headers():
    return {
        "Authorization": "Bearer " + BEARER,
        "X-CC-Event-Id": EVENT,
        "X-Idempotency-Key": EVENT,
        "X-Correlation-Ref": CORRELATION,
        "X-CC-Event-Schema": SCHEMA,
    }


def make_client(monkeypatch, env=None, *, auth=True, receipt=True, rows=None):
    env = environment() if env is None else env
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    # NEVER carry deployment env from this test out to hosted resources.
    db = DB()
    if rows is not None:
        db.binding_rows = rows
    calls = {"auth": 0, "receipt": 0, "write": 0}
    def check_auth(_db, *, bearer):
        calls["auth"] += 1
        return auth and _db is db and bearer == BEARER
    async def check_receipt(_proof, _payload):
        calls["receipt"] += 1
        return receipt
    def write(_db, proof, *, authorize_service, verify_cc_receipt):
        calls["write"] += 1
        assert authorize_service(proof) is True
        assert verify_cc_receipt(proof) is True
        return SimpleNamespace(public_id=UUID(SESSION))

    monkeypatch.setattr(t, "authorize_cc_ingest", check_auth)
    monkeypatch.setattr(t, "attest_cc_signed_sender", check_receipt)
    monkeypatch.setattr(t, "persist_verified_event", write)

    app = FastAPI()
    if t.install_track_a_first_ia0(app, environ=env):
        path = t.TRACK_A_PREFIX + "/first-ia0"
        assert path in [r.path for r in app.router.routes]
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db, calls


def test_default_off_even_if_app_imported(monkeypatch):
    monkeypatch.delenv(t.TRACK_A_FLAG, raising=False)
    monkeypatch.setenv("GATEWAY_API_KEY", "synthetic-test-only-not-credential")
    monkeypatch.setenv("JWT_SECRET", "synthetic-test-only-not-credential")
    from startup import create_app
    app = create_app()
    assert (t.TRACK_A_PREFIX + "/first-ia0") not in [r.path for r in app.routes]
    assert "/internal/swes/track-a/test-only/ia0-events" not in [r.path for r in app.routes]


@pytest.mark.parametrize("bad", [
    {"XAFPAY_SWES_TRACK_A_IA0_ENABLED": "0"},
    {"XAFPAY_SWES_TRACK_A_IA0_ENABLED": "true"},
    {"RENDER": "false"},
    {"RENDER_SERVICE_ID": "srv-wnd-real"},
    {"RENDER_EXTERNAL_HOSTNAME": "live-restaurant.example"},
    {"RENDER_GIT_COMMIT": "not-a-sha"},
    {"RENDER_GIT_BRANCH": "production"},
])
def test_no_route_when_point_of_use_context_not_exact(monkeypatch, bad):
    env = environment() | bad
    client, db, calls = make_client(monkeypatch, env)
    response = client.post(t.TRACK_A_PREFIX + "/first-ia0", json=event(), headers=headers())
    assert response.status_code == 404
    assert (db.commits, calls["auth"], calls["receipt"], calls["write"]) == (0, 0, 0, 0)


def test_local_stubbed_contract_success_not_hosted_proof(monkeypatch):
    client, db, calls = make_client(monkeypatch)
    response = client.post(t.TRACK_A_PREFIX + "/first-ia0", json=event(), headers=headers())
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["context_binding_ref"] == CONTEXT
    assert body["ia0_session_ref"] == SESSION
    assert body["verification_state"] == "channel_verified"
    assert body["order_state"] == "NOT_CREATED"
    assert (db.commits, db.rollbacks) == (1, 0)
    assert (calls["auth"], calls["receipt"], calls["write"]) == (2, 1, 1)
    assert db.last_sql[1]["tenant"] == 910001


@pytest.mark.parametrize("change", [
    {"tenant_id": 2},
    {"merchant_public_id": "4b196022-65a1-548c-b122-f1f9e4b78bea"},
    {"audience": "wrong"},
    {"location_id": 2},
    {"event_id": "invalid"},
    {"context_purpose": "wrong"},
    {"server_received_at_utc": "2020-01-01T00:00:00Z"},
    {"delivered_before_utc": "2020-01-01T00:05:00Z"},
    {"forged_bool": True},
])
def test_wrong_scope_and_unapproved_fields_never_auth_or_write(monkeypatch, change):
    client, db, calls = make_client(monkeypatch)
    response = client.post(t.TRACK_A_PREFIX + "/first-ia0", json=event() | change, headers=headers())
    assert response.status_code == 403
    assert db.commits == 0
    assert calls["write"] == 0


@pytest.mark.parametrize("header, value", [
    ("Authorization", "Bearer invalid"),
    ("Authorization", "Basic " + BEARER),
    ("X-CC-Event-Id", "f" * 64),
    ("X-Idempotency-Key", "f" * 64),
    ("X-Correlation-Ref", "bad-correlation"),
])
def test_bearer_and_header_binding_fail_closed(monkeypatch, header, value):
    client, db, calls = make_client(monkeypatch)
    response = client.post(
        t.TRACK_A_PREFIX + "/first-ia0", json=event(), headers=headers() | {header: value}
    )
    assert response.status_code == 403
    assert db.commits == 0
    assert calls["write"] == 0


@pytest.mark.parametrize("auth,receipt,rows", [
    (False, True, [CONTEXT]),
    (True, False, [CONTEXT]),
    (True, True, []),
    (True, True, [CONTEXT, CONTEXT]),
])
def test_bilateral_role_receipt_and_canonical_binding_required(monkeypatch, auth, receipt, rows):
    client, db, _ = make_client(monkeypatch, auth=auth, receipt=receipt, rows=rows)
    response = client.post(t.TRACK_A_PREFIX + "/first-ia0", json=event(), headers=headers())
    assert response.status_code == 403
    assert db.commits == 0
    assert db.rollbacks == 1


def test_protected_v2_cannot_be_assumed_from_track_a(monkeypatch):
    client, db, _ = make_client(monkeypatch)
    assert client.get("/internal/swes/track-a/test-only/ia0-events").status_code == 404
    response = client.post(t.TRACK_A_PREFIX + "/first-ia0", json=event(), headers=headers())
    assert response.status_code == 202
    assert db.commits == 1
    source = ( __import__("pathlib").Path(t.__file__).read_text(encoding="utf-8"))
    assert "R48PgReleaseFence" not in source
    assert "persist_verified_event(" in source
    assert "authorize_cc_ingest(" in source
    assert "attest_cc_signed_sender(" in source
    assert "db.commit()" in source
