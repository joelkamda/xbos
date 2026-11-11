"""Synthetic guard tests; these do not claim hosted D1 admission."""
from fastapi.testclient import TestClient

from xcomp_neutral_d1_isolated_candidate import app, EXPECTED


def test_d1_app_contains_only_exact_neutral_routes():
    routes = {(method, route.path) for route in app.routes
              for method in (getattr(route, "methods", ()) or ())}
    assert routes == EXPECTED | {("GET", "/health/process"), ("GET", "/health/ready")}


def test_no_legacy_or_payments_or_customer_channel_routes():
    client = TestClient(app)
    for path in ("/", "/health", "/browser-session/v1/login",
                 "/api/orders", "/payments", "/kernel/neutral/v1/tenants/7/activate"):
        for method in (client.get, client.post):
            assert method(path).status_code == 404, (method.__name__, path)


def test_liveness_is_not_authenticated_readiness():
    client = TestClient(app)
    assert client.get("/health/process").json() == {
        "process": "alive", "d1_authenticated": False, "admitted": False}
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "D1_HOSTED_ADMISSION_NOT_ESTABLISHED"


def test_neutral_reads_have_no_unauthenticated_success():
    client = TestClient(app)
    for path in (
        "/kernel/neutral/v1/tenants/7/branches/7/context",
        "/kernel/neutral/v1/tenants/7/commercial-entitlements",
        "/kernel/neutral/v1/tenants/7/packs/restaurant/state",
        "/platform/xcomp/d1d2/readiness",
    ):
        assert client.get(path).status_code == 401, path
        resp = client.get(path, headers={"Authorization": "Bearer synthetic-not-a-session"})
        assert resp.status_code == 503, path


def test_no_write_allowed():
    client = TestClient(app)
    assert client.post("/kernel/neutral/v1/tenants/7/commercial-entitlements",
                       headers={"Authorization": "Bearer bogus"}).status_code == 405
