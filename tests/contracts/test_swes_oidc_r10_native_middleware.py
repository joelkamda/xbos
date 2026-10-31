"""R10: real three-middleware and startup OIDC exact-path gates, no DB server."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from platform_admin.swes_oidc_route_admission_r10 import is_public_oidc_handshake


@pytest.fixture
def env(monkeypatch):
    # These are syntactically valid TEST FIXTURES only. No database is running
    # on this loopback port and none may be connected by the handshake routes.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://swes_local_fixture@127.0.0.1:55478/no_database",
    )
    monkeypatch.setenv("JWT_SECRET", "test-only-not-secret")
    monkeypatch.setenv("GATEWAY_API_KEY", "test-only-not-secret")
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SWES_OIDC_ENABLED", "false")
    monkeypatch.delenv("SWES_OIDC_ROUTE_REGISTERED", raising=False)


def app_client():
    # Full source startup, all three real middlewares, and actual PA router.
    # No app DB or schema creation.
    from startup import create_app
    return TestClient(
        create_app(),
        base_url="https://wnd-xafpay-demo-austin-backend.onrender.com",
        raise_server_exceptions=True,
    )


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/internal/swes/pa/oidc/start/", "GET"),
        ("/internal/swes/pa/oidc/start/extra", "GET"),
        ("/internal/swes/pa/oidc/privileged", "GET"),
        ("/internal/swes/pa/oidc/callback/extra", "GET"),
        ("/internal/swes/pa/oidc/start", "POST"),
        ("/internal/swes/pa/oidc/callback", "POST"),
        ("/internal/swes/pa/oidc/callback", "HEAD"),
        ("/internal/swes/pa/oidc/start", "PATCH"),
        ("/internal/swes/pa/oidc/owner-binding", "GET"),
        ("/internal/swes/pa/oidc/merchant-admin", "GET"),
    ],
)
def test_no_broader_handshake_bypass(monkeypatch, path, method):
    monkeypatch.setenv("SWES_OIDC_ROUTE_REGISTERED", "true")
    assert not is_public_oidc_handshake(path, method)


@pytest.mark.parametrize(
    "path", (
        "/internal/swes/pa/oidc/start",
        "/internal/swes/pa/oidc/callback",
    ),
)
def test_only_two_get_routes_admit_when_mounted(monkeypatch, path):
    monkeypatch.setenv("SWES_OIDC_ROUTE_REGISTERED", "true")
    assert is_public_oidc_handshake(path, "GET")
    assert not is_public_oidc_handshake(path, "POST")


def test_unmounted_routes_still_require_legacy_jwt(env):
    c = app_client()
    assert not any(
        r.path.startswith("/internal/swes/pa/oidc")
        for r in c.app.routes
    )
    for path in (
        "/internal/swes/pa/oidc/start",
        "/internal/swes/pa/oidc/callback",
    ):
        response = c.get(path)
        assert response.status_code == 401


def test_registered_default_off_flow_admitted_but_never_enrolled(env, monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ROUTE_REGISTERED", "true")
    c = app_client()
    actual = {r.path for r in c.app.routes if r.path.startswith("/internal/swes/pa/oidc/")}
    assert actual == {
        "/internal/swes/pa/oidc/start",
        "/internal/swes/pa/oidc/callback",
    }
    start = c.get("/internal/swes/pa/oidc/start")
    assert start.status_code == 503
    assert start.json() == {"detail": "HOLD_OIDC_NOT_ADMITTED"}
    assert "set-cookie" not in start.headers
    callback = c.get("/internal/swes/pa/oidc/callback?code=masked&state=missing")
    assert callback.status_code == 403
    assert callback.json() == {
        "status": "HOLD",
        "code": "HOLD_OIDC_NOT_ADMITTED",
    }
    assert "masked" not in callback.text
    for path in (
        "/internal/swes/pa/oidc/start/extra",
        "/internal/swes/pa/oidc/privileged",
        "/internal/swes/pa/oidc/owner-binding",
        "/internal/swes/pa/oidc/merchant-admin",
    ):
        result = c.get(path)
        assert result.status_code == 401, (path, result.status_code)
    for path in actual:
        result = c.post(path)
        assert result.status_code == 401


def test_source_registration_flag_is_not_login_enabled(env, monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ROUTE_REGISTERED", "true")
    monkeypatch.delenv("SWES_OIDC_ENABLED", raising=False)
    c = app_client()
    assert c.get("/internal/swes/pa/oidc/start").status_code == 503


def test_activation_env_without_mounted_router_denies(env, monkeypatch):
    monkeypatch.setenv("SWES_OIDC_ENABLED", "true")
    monkeypatch.setenv("SWES_OIDC_ROUTE_REGISTERED", "false")
    c = app_client()
    assert c.get("/internal/swes/pa/oidc/start").status_code == 401
