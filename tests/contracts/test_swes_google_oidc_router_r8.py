"""HTTP boundary regression for dormant Google login candidate. No network, no grants."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_admin import swes_google_oidc_router_r7 as router_mod
from platform_admin.swes_google_oidc_r7 import ISSUER, OIDCHold, VerifiedIdentity

CLIENT_ID = "123456789-swesaustin.apps.googleusercontent.com"
CALLBACK = "https://wnd-xafpay-demo-austin-backend.onrender.com/internal/swes/pa/oidc/callback"
ROOT = "https://wnd-xafpay-demo-austin-backend.onrender.com"
STABLE_SUB_HASH = "d" * 64


def client():
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app, base_url=ROOT)


def test_default_off_cannot_begin_google_login(monkeypatch):
    monkeypatch.delenv("SWES_OIDC_ENABLED", raising=False)
    resp = client().get("/internal/swes/pa/oidc/start", follow_redirects=False)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "HOLD_OIDC_NOT_ADMITTED"}
    assert "set-cookie" not in resp.headers


def test_default_off_callback_cannot_exchange_token(monkeypatch):
    monkeypatch.delenv("SWES_OIDC_ENABLED", raising=False)
    resp = client().get(
        "/internal/swes/pa/oidc/callback?code=secret-code-goes-here&state=notreal"
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "HOLD_OIDC_NOT_ADMITTED"
    assert "secret-code-goes-here" not in resp.text


def test_login_begin_sets_host_only_secure_lax_cookie(monkeypatch):
    monkeypatch.setattr(router_mod, "_config", lambda: object())
    monkeypatch.setattr(router_mod, "_store", lambda: object())
    monkeypatch.setattr(router_mod, "begin", lambda config, store, now: (
        "https://accounts.google.com/o/oauth2/v2/auth?state=opaque-once",
        "opaque-once",
    ))
    resp = client().get("/internal/swes/pa/oidc/start", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("https://accounts.google.com/")
    cookie = resp.headers["set-cookie"]
    assert "__Host-swes-pa-oidc-state=opaque-once" in cookie
    assert "secure" in cookie.lower()
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert "domain=" not in cookie.lower()


def test_callback_verified_google_claim_yields_no_pc5_grant(monkeypatch):
    monkeypatch.setattr(router_mod, "_config", lambda: object())
    monkeypatch.setattr(router_mod, "_store", lambda: object())
    class FakeHttpClient:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(router_mod.httpx, "Client", FakeHttpClient)
    def verified(config, store, *, state, browser_state, code, now, http):
        assert code == "opaque-google-code"
        assert state == browser_state == "opaque-browser-state"
        return VerifiedIdentity(
            ISSUER, STABLE_SUB_HASH, CLIENT_ID,
            datetime.now(timezone.utc), "a"*64, 910001, assurance_level=1,
        )
    monkeypatch.setattr(router_mod, "finish", verified)
    # Even an operator-written env flag cannot self-certify CEO ownership.
    monkeypatch.setenv("SWES_OIDC_CEO_BINDING_APPROVED", "true")
    c = client()
    c.cookies.set("__Host-swes-pa-oidc-state","opaque-browser-state")
    response = c.get("/internal/swes/pa/oidc/callback?code=opaque-google-code&state=opaque-browser-state")
    assert response.status_code == 200
    result = response.json()
    assert result["owner_binding_verified"] is False
    assert result["pc5_session_created"] is False
    assert result["administrative_permission_granted"] is False
    assert result["assurance_level"] == 1
    assert result["subject_sha256"] == STABLE_SUB_HASH
    assert result["tenant_id"] == 910001
    assert "no-store" in response.headers["cache-control"]


def test_callback_error_fails_closed_without_token_echo(monkeypatch):
    monkeypatch.setattr(router_mod, "_config", lambda: object())
    monkeypatch.setattr(router_mod, "_store", lambda: object())
    class FakeHttpClient:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(router_mod.httpx, "Client", FakeHttpClient)
    monkeypatch.setattr(router_mod, "finish", lambda *args,**kwargs: (
        (_ for _ in ()).throw(OIDCHold("HOLD_NONCE_MISMATCH"))
    ))
    c = client()
    c.cookies.set("__Host-swes-pa-oidc-state","test")
    resp=c.get("/internal/swes/pa/oidc/callback?code=do-not-echo&state=wrong")
    assert resp.status_code == 403
    assert resp.json() == {"status": "HOLD", "code": "HOLD_NONCE_MISMATCH"}
    assert "do-not-echo" not in resp.text
    assert "no-store" in resp.headers["cache-control"]


def test_missing_sql_store_key_yields_bounded_no_secret_error(monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "true")
    monkeypatch.setenv("SWES_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SWES_OIDC_CLIENT_SECRET", "test-only-not-real-secret")
    monkeypatch.setenv("SWES_OIDC_REDIRECT_URI", CALLBACK)
    monkeypatch.delenv("SWES_OIDC_CHALLENGE_FERNET_KEY", raising=False)
    resp=client().get("/internal/swes/pa/oidc/start",follow_redirects=False)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "HOLD_CHALLENGE_SEAL_KEY_ABSENT"



def test_invalid_challenge_key_is_rejected_before_engine_import(monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "true")
    monkeypatch.setenv("SWES_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SWES_OIDC_CLIENT_SECRET", "test-only-not-real-secret")
    monkeypatch.setenv("SWES_OIDC_REDIRECT_URI", CALLBACK)
    monkeypatch.setenv("SWES_OIDC_CHALLENGE_FERNET_KEY", "invalid-key")
    resp=client().get("/internal/swes/pa/oidc/start",follow_redirects=False)
    assert resp.status_code==503
    assert resp.json()=={"detail":"HOLD_CHALLENGE_SEAL_KEY_INVALID"}
    assert "invalid-key" not in resp.text


def test_unexpected_login_start_dependency_error_never_leaks_internal_detail(monkeypatch):
    monkeypatch.setattr(router_mod,"_config",lambda:object())
    monkeypatch.setattr(router_mod,"_store",lambda:(_ for _ in ()).throw(
        RuntimeError("sensitive internal diagnostic must not be returned")
    ))
    resp=client().get("/internal/swes/pa/oidc/start",follow_redirects=False)
    assert resp.status_code==503
    assert resp.json()=={"detail":"HOLD_OIDC_RUNTIME_UNAVAILABLE"}
    assert "sensitive internal diagnostic" not in resp.text



def test_missing_dedicated_writer_fails_with_owner_database_url_present(monkeypatch):
    """A valid-seeming shared database cannot substitute for OIDC-only LOGIN."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SWES_OIDC_ENABLED", "true")
    monkeypatch.setenv("SWES_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SWES_OIDC_CLIENT_SECRET", "local-fake-client-secret")
    monkeypatch.setenv("SWES_OIDC_REDIRECT_URI", CALLBACK)
    monkeypatch.setenv(
        "SWES_OIDC_CHALLENGE_FERNET_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://wnd_xafpay_demo_austin_db_user:"
        "local-owner-fixture@127.0.0.1:55479/wnd_xafpay_demo_austin_db",
    )
    monkeypatch.delenv("SWES_OIDC_WRITER_DATABASE_URL", raising=False)
    response=client().get("/internal/swes/pa/oidc/start",follow_redirects=False)
    assert response.status_code==503
    assert response.json()=={"detail":"HOLD_OIDC_DEDICATED_WRITER_URL_ABSENT"}
    assert "local-owner-fixture" not in response.text


def test_oidc_db_url_rejects_general_owner_before_connection(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SWES_OIDC_ENABLED", "true")
    monkeypatch.setenv("SWES_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SWES_OIDC_CLIENT_SECRET", "local-fake-client-secret")
    monkeypatch.setenv("SWES_OIDC_REDIRECT_URI", CALLBACK)
    monkeypatch.setenv(
        "SWES_OIDC_CHALLENGE_FERNET_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setenv(
        "SWES_OIDC_WRITER_DATABASE_URL",
        "postgresql+psycopg2://wnd_xafpay_demo_austin_db_user:"
        "local-owner-fixture@127.0.0.1:55479/wnd_xafpay_demo_austin_db",
    )
    response=client().get("/internal/swes/pa/oidc/start",follow_redirects=False)
    assert response.status_code==503
    assert response.json()=={"detail":"HOLD_OIDC_WRITER_URL_UNTRUSTED"}
    assert "local-owner-fixture" not in response.text
