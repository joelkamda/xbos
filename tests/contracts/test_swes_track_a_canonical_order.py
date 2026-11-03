"""Gated real-canonical Track A order adapter: no fake SQL or provider success."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import get_db
from restaurant.customer_channel import swes_track_a_canonical_order as m

CONTEXT = "11111111-2222-4333-8444-555555555555"
CORRELATION = "66666666-7777-4888-8999-aaaaaaaaaaaa"
ORDER = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
EVENT = "a" * 64
BEARER = "test-standin-only-distinct-real-checkout-bearer"
SHA = "c" * 40
NOW = datetime.now(timezone.utc)


class QueryRows:
    def __init__(self, rows):
        self.rows = rows
    def mappings(self):
        return self
    def all(self):
        return self.rows


class DB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.calls = []
        self.price = Decimal(1000)
        self.source = [{
            "source_reference": EVENT,
            "source_hash": "b" * 64,
            "provenance_reference": "c" * 64,
            "effective_from": NOW - timedelta(seconds=10),
            "expires_at": NOW + timedelta(minutes=4),
            "sender_digest": "d" * 64,
            "session_public_id": UUID(CONTEXT),
            "participant_public_id": UUID(CONTEXT),
        }]

    def execute(self, query, args):
        sql = str(query)
        self.calls.append((sql, dict(args)))
        if "ia0_external_channel_identities" in sql:
            return QueryRows(self.source)
        if "JOIN public.so1_catalog_entries e" in sql:
            return QueryRows([{
                "item_ref": UUID("12121212-3333-4444-8555-666666666666"),
                "amount": self.price, "currency": "XAF",
            }])
        if "LEFT JOIN public.r1_restaurant_order_lines" in sql:
            return QueryRows([{
                "public_id": UUID(ORDER), "lifecycle_status": "submitted",
                "amount": self.price, "line_count": 1,
                "currency_count": 1, "currency": "XAF",
            }])
        raise AssertionError("unexpected query")

    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1


def env(**updates):
    e = dict(m._RENDER)
    e.update({
        m.FLAG: "1", m.APPROVED_SOURCE_SHA: SHA,
        "RENDER_GIT_COMMIT": SHA,
    })
    e.update(updates)
    return e


def body(**updates):
    r = {
        "context_binding_ref": CONTEXT,
        "correlation_ref": CORRELATION,
        "event_id": EVENT,
        "action": m.ORDER_ACTION,
    }
    r.update(updates)
    return r


def headers(**updates):
    h = {
        "Authorization": "Bearer " + BEARER,
        "X-CC-Event-Id": EVENT,
        "X-Correlation-Ref": CORRELATION,
    }
    h.update(updates)
    return h


def client(monkeypatch, admitted=None):
    e = env() if admitted is None else admitted
    for key, val in e.items():
        monkeypatch.setenv(key, val)
    db = DB()
    app = FastAPI()
    if m.install_track_a_order(app, environ=e):
        assert m.PATH in [r.path for r in app.routes]
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db


@pytest.mark.parametrize("change", [
    {m.FLAG: "0"}, {m.FLAG: "true"}, {m.APPROVED_SOURCE_SHA: ""},
    {m.APPROVED_SOURCE_SHA: "b" * 40}, {"RENDER_GIT_COMMIT": "b" * 40},
    {"RENDER_SERVICE_ID": "srv-live-real"}, {"RENDER_GIT_BRANCH": "main"},
    {"RENDER": "false"}, {"RENDER_EXTERNAL_HOSTNAME": "wnd-real.example.com"},
])
def test_owner_pin_and_host_source_mandatory_no_route(monkeypatch, change):
    c, db = client(monkeypatch, env(**change))
    assert c.post(m.PATH, json=body(), headers=headers()).status_code == 404
    assert db.commits == 0


@pytest.mark.parametrize("change", [
    {"action": "hello wnd"}, {"action": "greeting"},
    {"action": "order"}, {"event_id": "f" * 64},
    {"context_binding_ref": "not-a-uuid"}, {"correlation_ref": "other"},
    {"tenant_id": 2}, {"merchant_public_id": "wrong"},
    {"amount": "1000"}, {"payment_state": "paid"},
    {"service_mode": "delivery"}, {"item_ref": CONTEXT},
])
def test_no_caller_scope_price_or_greeting_authority(monkeypatch, change):
    c, db = client(monkeypatch)
    response = c.post(m.PATH, json=body(**change), headers=headers())
    assert response.status_code == 403
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.parametrize("bad_headers", [
    {"Authorization": "Bearer wrong"},
    {"Authorization": "Basic " + BEARER},
    {"Authorization": ""},
    {"X-Correlation-Ref": "f" * 36},
    {"X-CC-Event-Id": "b" * 64},
])
def test_wrong_protected_token_and_event_binding_denied(monkeypatch, bad_headers):
    c, db = client(monkeypatch)
    monkeypatch.setattr(m, "qualify_registered_test_order_scope",
                        lambda *_a, **_kw: (_ for _ in ()).throw(m.H1BError("SERVICE_AUTH_FORBIDDEN")))
    response = c.post(m.PATH, json=body(), headers=headers(**bad_headers))
    assert response.status_code == 403
    assert db.commits == 0


def test_real_canonical_draft_confirm_submit_source_path(monkeypatch):
    db = DB()
    scope = SimpleNamespace(context_binding_public_id=UUID(CONTEXT))
    calls = []
    class Authority:
        def __init__(self, _db):
            assert _db is db
        def create_draft(self, **kw):
            calls.append(("create", kw))
            return {"draft_ref": CONTEXT, "draft_version": 1,
                    "order_state": "DRAFT", "lines": []}
        def mutate_draft(self, **kw):
            calls.append(("mutate", kw))
            return {"canonical_total": "1000", "currency": "XAF"}
        def confirm_draft(self, **kw):
            calls.append(("confirm", kw))
            return SimpleNamespace(
                confirmation_ref=UUID(CONTEXT),
                canonical_total=Decimal(1000), currency="XAF",
                authoritative_lines=[object()],
            )
        def submit_draft(self, **kw):
            calls.append(("submit", kw))
            return SimpleNamespace(order_ref=UUID(ORDER))
    monkeypatch.setattr(m, "CustomerChannelDraftOrderAuthority", Authority)
    monkeypatch.setattr(m, "_make_sender_bound_contact",
                        lambda *_a, **_kw: UUID(CONTEXT))
    order = m._order_from_verified_context(
        db, scope=scope, event_id=EVENT, correlation=UUID(CORRELATION)
    )
    assert order == UUID(ORDER)
    assert [c[0] for c in calls] == ["create", "mutate", "confirm", "submit"]
    assert calls[0][1]["service_mode"] == "takeaway"
    assert calls[1][1]["payload"]["quantity"] == "1"
    assert calls[1][1]["payload"]["modifier_refs"] == []
    assert calls[3][1]["client_submit_ref"].endswith(EVENT + ":submit")
    assert db.commits == 0
    assert not any("INSERT INTO public.r1_restaurant_orders" in x[0] for x in db.calls)


def test_conflicting_canonical_price_aborts_before_contact(monkeypatch):
    db = DB()
    db.price = Decimal(999)
    monkeypatch.setattr(m, "_make_sender_bound_contact",
                        lambda *_a, **_kw: pytest.fail("contact should not be created"))
    with pytest.raises(m.H1BError, match="ORDER_NOT_READY"):
        m._order_from_verified_context(
            db, scope=SimpleNamespace(context_binding_public_id=UUID(CONTEXT)),
            event_id=EVENT, correlation=UUID(CORRELATION),
        )


def test_wrong_event_cannot_reuse_authenticated_greeting_context():
    db = DB()
    with pytest.raises(m.H1BError, match="CONTEXT_MISMATCH"):
        m._read_source(
            db, binding=UUID(CONTEXT), correlation=UUID(CORRELATION),
            event_id="b" * 64,
        )


def test_source_contains_no_protected_release_or_forged_payment():
    from pathlib import Path
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "qualify_registered_test_order_scope(" in src
    assert "CustomerChannelDraftOrderAuthority(" in src
    assert "PartyAuthority(SQLPartyRepository(db))" in src
    assert "PublicAuthorityReference(" in src
    assert "R48PgReleaseFence(" not in src
    assert "INSERT INTO public.r1_restaurant_orders" not in src
    assert "payment_state\": \"NOT_INITIATED" in src
    assert "ORDER_ACTION = \"order wnd test\"" in src
