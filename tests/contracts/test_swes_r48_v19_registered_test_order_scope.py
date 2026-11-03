"""Track A registered merchant: isolated source-only, fail-closed test suite.

All keys are synthetic in-process test data. No hosted DB, Render env, Twilio,
Tranzak or protected RELEASE path is touched.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from restaurant.customer_channel.contracts import H1BError, TrustedCheckoutScope
from restaurant.customer_channel.swes_track_a_registered_order_scope import (
    MERCHANT,
    qualify_registered_test_order_scope,
)

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
TOKEN = "synthetic-unit-test-bearer-with-adequate-entropy-123456789"
SHA = "a" * 40
CTX = UUID("c8aed62e-e458-4906-b5c7-559a01500001")
CORR = UUID("c8aed62e-e458-4906-b5c7-559a01500002")
SERVICE = UUID("c8aed62e-e458-4906-b5c7-559a01500003")


class Rows:
    def __init__(self, data):
        self.data = data

    def mappings(self):
        return self

    def all(self):
        return self.data


class StubDB:
    def __init__(self):
        self.principal = [{
            "id": 3, "public_id": str(SERVICE), "scope_id": 5
        }]
        self.merchant = [{
            "public_id": str(MERCHANT), "tenant_id": 910001,
            "administration_state": "registered",
            "external_reference": "SWES-R2-WND-AUSTIN-TEST-ONLY",
        }]
        self.ia0 = [{
            "public_id": str(CTX), "tenant_id": 910001,
            "purpose_code": "restaurant.customer_channel.checkout",
            "source_authority": "xafpay.customer_channel.signed_twilio",
            "source_reference": "1" * 64,
            "source_hash": "2" * 64,
            "source_version": "v1",
            "provenance_authority": "xafpay.cc.hosted_pg17_signed_twilio_receipt",
            "provenance_reference": "3" * 64,
            "correlation_id": str(CORR),
            "effective_from": NOW - timedelta(minutes=2),
            "expires_at": NOW + timedelta(minutes=3),
            "session_expires_at": NOW + timedelta(minutes=3),
            "ended_at": None, "closed_at": None,
            "session_status": "active",
            "verification_state": "channel_verified",
            "identity_resolution_state": "channel_identified",
        }]
        self.structure = [{
            "branch_id": 1, "organization_unit_id": 1,
            "location_id": 5, "currency": "XAF",
        }]
        self.calls = []

    def execute(self, query, values):
        sql = str(query)
        self.calls.append((sql, dict(values)))
        if "FROM public.service_identities s" in sql:
            return Rows(self.principal)
        if "FROM public.pa_merchants" in sql:
            return Rows(self.merchant)
        if "FROM public.ia0_interaction_context_bindings b" in sql:
            return Rows(self.ia0)
        if "FROM public.legacy_branch_structural_mappings m" in sql:
            return Rows(self.structure)
        raise AssertionError("unexpected SQL")


def env(**changes):
    e = {
        "XAFPAY_SWES_TRACK_A_REGISTERED_ORDER_ENABLED": "1",
        "RENDER": "true",
        "RENDER_SERVICE_ID": "srv-db3vej67bikc73ai2080",
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": "wnd-xafpay-demo-austin-backend.onrender.com",
        "RENDER_GIT_BRANCH": "compat/wnd-demo-cc-r1-legacy-neutral-bridge",
        "RENDER_GIT_COMMIT": SHA,
        "XAFPAY_SWES_TRACK_A_ORDER_BEARER_SHA256":
            hashlib.sha256(TOKEN.encode()).hexdigest(),
        "XAFPAY_SWES_TRACK_A_ORDER_EXPIRES_UTC":
            (NOW + timedelta(hours=1)).isoformat(),
    }
    e.update(changes)
    return e


def verify(db, **changes):
    options = {
        "authorization_header": "Bearer " + TOKEN,
        "context_binding_ref": CTX,
        "correlation_ref": CORR,
        "expected_deployed_sha": SHA,
        "environ": env(),
        "now": NOW,
    }
    options.update(changes)
    return qualify_registered_test_order_scope(db, **options)


def expect_deny(db, **changes):
    with pytest.raises(H1BError) as e:
        verify(db, **changes)
    assert e.value.code in ("SERVICE_AUTH_FORBIDDEN", "CONTEXT_MISMATCH")


def test_valid_separately_authenticated_test_only_scope_from_actual_rows():
    db = StubDB()
    result = verify(db)
    assert isinstance(result, TrustedCheckoutScope)
    assert (result.tenant_id, result.location_id, result.currency) == (910001, 5, "XAF")
    assert result.merchant_public_id == MERCHANT
    assert result.context_binding_public_id == CTX
    assert result.service_identity_public_id == SERVICE
    assert result.correlation_ref == str(CORR)
    assert len(db.calls) == 4
    assert db.calls[0][1]["service"] == "swes-track-a-customer-channel"
    assert db.calls[0][1]["credential"] == "env.swes_track_a_order_cc_bearer"
    assert db.calls[0][1]["permission"] == "restaurant.customer_channel.checkout"
    assert db.calls[1][1]["merchant"] == "4b196022-55a1-548c-b122-f1f9e4b78bea"


@pytest.mark.parametrize("change", [
    {"XAFPAY_SWES_TRACK_A_REGISTERED_ORDER_ENABLED": "0"},
    {"XAFPAY_SWES_TRACK_A_REGISTERED_ORDER_ENABLED": "true"},
    {"RENDER": "false"},
    {"RENDER_SERVICE_ID": "srv-another"},
    {"RENDER_SERVICE_TYPE": "cron"},
    {"RENDER_EXTERNAL_HOSTNAME": "wnd-production.example"},
    {"RENDER_GIT_BRANCH": "main"},
    {"RENDER_GIT_COMMIT": "b" * 40},
])
def test_unauthorized_source_or_flag_never_reaches_database(change):
    db = StubDB()
    expect_deny(db, environ=env(**change))
    assert db.calls == []


def test_unpinned_external_source_never_reaches_database():
    db = StubDB()
    expect_deny(db, expected_deployed_sha="b" * 40)
    assert db.calls == []


@pytest.mark.parametrize("bad_header", [
    None, "", TOKEN, "Basic " + TOKEN, "Bearer ", "Bearer " + "x" * 16,
    "Bearer " + TOKEN + " ", "Bearer wrong-" + "x" * 43,
])
def test_bad_distinct_test_bearer_never_reaches_database(bad_header):
    db = StubDB()
    expect_deny(db, authorization_header=bad_header)
    assert db.calls == []


@pytest.mark.parametrize("change", [
    {"XAFPAY_SWES_TRACK_A_ORDER_BEARER_SHA256": "fake"},
    {"XAFPAY_SWES_TRACK_A_ORDER_BEARER_SHA256": ""},
    {"XAFPAY_SWES_TRACK_A_ORDER_EXPIRES_UTC": "not-a-time"},
    {"XAFPAY_SWES_TRACK_A_ORDER_EXPIRES_UTC": (NOW-timedelta(seconds=1)).isoformat()},
    {"XAFPAY_SWES_TRACK_A_ORDER_EXPIRES_UTC": (NOW+timedelta(hours=25)).isoformat()},
    {"XAFPAY_SWES_TRACK_A_ORDER_EXPIRES_UTC": "2026-11-03T13:00:00"},
])
def test_test_credential_custody_or_expiry_must_be_valid(change):
    db = StubDB()
    expect_deny(db, environ=env(**change))
    assert db.calls == []


@pytest.mark.parametrize("field,value", [
    ("scope_id", 2),
    ("public_id", None),
])
def test_mismatched_test_service_denied(field, value):
    db = StubDB()
    db.principal[0][field] = value
    expect_deny(db)
    assert len(db.calls) == 1


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_or_missing_test_credential_denied(count):
    db = StubDB()
    db.principal = db.principal * count
    expect_deny(db)
    assert len(db.calls) == 1


@pytest.mark.parametrize("field,value", [
    ("public_id", "4b196022-65a1-548c-b122-f1f9e4b78bea"),
    ("tenant_id", 2),
    ("administration_state", "operational"),
    ("external_reference", "real-merchant"),
])
def test_retracted_wrong_lifecycle_or_unmarked_merchant_denied(field, value):
    db = StubDB()
    db.merchant[0][field] = value
    expect_deny(db)
    assert len(db.calls) == 2


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_or_missing_test_merchant_denied(count):
    db = StubDB()
    db.merchant = db.merchant * count
    expect_deny(db)
    assert len(db.calls) == 2


@pytest.mark.parametrize("field,value", [
    ("public_id", str(uuid4())),
    ("tenant_id", 2),
    ("purpose_code", "different-purpose"),
    ("source_authority", "unverified-client"),
    ("source_reference", "not-a-hash"),
    ("source_hash", "not-a-hash"),
    ("source_version", "v0"),
    ("provenance_authority", "caller-json"),
    ("provenance_reference", "not-a-hash"),
    ("correlation_id", str(uuid4())),
    ("ended_at", NOW),
    ("closed_at", NOW),
    ("session_status", "closed"),
    ("verification_state", "unverified"),
    ("identity_resolution_state", "unresolved"),
    ("expires_at", NOW),
    ("session_expires_at", NOW),
    ("effective_from", NOW+timedelta(seconds=1)),
])
def test_invalid_or_unverified_sender_bound_ia0_denied(field, value):
    db = StubDB()
    db.ia0[0][field] = value
    expect_deny(db)
    assert len(db.calls) == 3


@pytest.mark.parametrize("field,value", [
    ("branch_id", 0),
    ("organization_unit_id", 0),
    ("location_id", 2),
    ("currency", "USD"),
])
def test_wrong_canonical_location_currency_or_structure_denied(field, value):
    db = StubDB()
    db.structure[0][field] = value
    expect_deny(db)
    assert len(db.calls) == 4


def test_no_ia0_creation_payment_checkout_or_route_publication():
    src = Path(__file__).resolve().parents[2]
    source = (src / "restaurant/customer_channel/swes_track_a_registered_order_scope.py").read_text(encoding="utf-8")
    startup = (src / "startup.py").read_text(encoding="utf-8")
    public_api = (src / "restaurant/customer_channel/router.py").read_text(encoding="utf-8")
    assert "swes_track_a_registered_order_scope" not in startup
    assert "swes_track_a_registered_order_scope" not in public_api
    assert "create_external_identity(" not in source
    assert "persist_verified_event(" not in source
    assert "db.commit()" not in source
    assert "checkout:create" not in source
    assert "administration_state='registered'" in source
    assert "ia0_interaction_context_bindings" in source
    assert "ia0_interaction_sessions" in source
    assert "p.permission_code=:permission" in source
    assert "XAFPAY_SWES_TRACK_A_REGISTERED_ORDER_ENABLED" in source
    assert "swes_r48_pg_release_fence" not in source
