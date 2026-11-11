"""Composition tests mock only the external browser authority, never spoof PC5 output."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import xcomp_d1_browser_sql_bridge as composer
from platform_admin.neutral_d1_pc5_binding_verifier import PC5BindingDenied

NOW = datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)
SID = uuid4()


def context(monkeypatch, *, overrides=None):
    values = {
        "sid": str(SID), "sub": "42", "tenant_id": 7,
        "branch_id": 11, "exp": int((NOW + timedelta(minutes=8)).timestamp()),
    }
    values.update(overrides or {})
    authority = SimpleNamespace(
        decode_token=lambda token, type: dict(values),
        validate_browser_access=lambda db, token: {
            "user_id": 42, "tenant_id": 7, "branch_id": 11},
        live_session=lambda db, sid: SimpleNamespace(
            user_id=42, tenant_id=7, branch_id=11,
            expires_at=NOW + timedelta(hours=1), revoked_at=None),
        aware=lambda dt: dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt,
    )
    return authority


def test_browser_reader_clamps_registry_expiry_to_signed_jwt(monkeypatch):
    authority = context(monkeypatch)
    obj = composer._verify_browser_session_with_authority(object(), "signed-token", authority)
    assert obj.session_id == SID and obj.user_id == 42
    assert obj.expires_at == NOW + timedelta(minutes=8)


@pytest.mark.parametrize("bad", [
    {"sub": "43"}, {"tenant_id": 8}, {"branch_id": 12},
    {"sid": "not-a-uuid"}, {"exp": "bad-time"},
])
def test_mismatched_signed_token_claims_fail_closed(monkeypatch, bad):
    authority = context(monkeypatch, overrides=bad)
    with pytest.raises(PC5BindingDenied):
        composer._verify_browser_session_with_authority(object(), "signed-token", authority)


def test_browser_authority_failure_denied(monkeypatch):
    authority = context(monkeypatch)
    def fail(db, token):
        raise RuntimeError("registry offline")
    authority.validate_browser_access = fail
    with pytest.raises(PC5BindingDenied, match="BROWSER_SESSION_UNVERIFIED"):
        composer._verify_browser_session_with_authority(object(), "signed-token", authority)
