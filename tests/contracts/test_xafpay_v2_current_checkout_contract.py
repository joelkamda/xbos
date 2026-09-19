from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.integrations.xafpay_v2.client import XafPayV2Client
from core.integrations.xafpay_v2.contract import (
    XafPayV2CheckoutRequest,
    XafPayV2IntegrationError,
)

ROOT = Path(__file__).resolve().parents[2]
ATTEMPT = UUID("11111111-1111-5111-8111-111111111111")
CHECKOUT_ID = "chk_018d6f5a-3333-7333-8333-333333333333"


class Response:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def request(amount: int = 10000) -> XafPayV2CheckoutRequest:
    return XafPayV2CheckoutRequest(
        payment_attempt_public_id=ATTEMPT,
        amount=Decimal(amount),
        currency_code="XAF",
        payment_method_code="mobile_money",
        payment_rail_code="mtn_momo",
        channel="xbos",
    )


def response_for(req: XafPayV2CheckoutRequest, *, status: str = "CREATED") -> dict:
    return {
        "checkout_session_id": CHECKOUT_ID,
        "revision": 1,
        "external_reference": req.external_reference,
        "status": status,
        "amount": {"minor": int(req.amount), "currency": "XAF"},
        "permitted_options": [{"method": "MOBILE_MONEY", "rail": "MTN_MOMO"}],
        "merchant": {"display_name": "WND"},
        "language": "en",
        "branding": {"profile": "default"},
        "channel": "xbos",
        "method_policy": {"key": "wnd", "version": 1},
        "expires_at": "2026-09-18T13:00:00.000Z",
        "public_token": "chkpub_current_contract_token",
    }


def test_a_one_attempt_creates_one_checkoutsession_request(monkeypatch):
    seen = []
    req = request()

    def post(url, **kwargs):
        seen.append((url, kwargs))
        return Response(201, response_for(req))

    monkeypatch.setattr("core.integrations.xafpay_v2.client.httpx.post", post)
    result = XafPayV2Client("https://gateway.example", "xps_staging_abcdefghijkl.secret").create_checkout(req)

    assert len(seen) == 1
    url, call = seen[0]
    assert url.endswith("/v2/checkout-sessions")
    assert call["headers"]["Idempotency-Key"] == f"xbos-checkout-{ATTEMPT}"
    assert call["json"]["external_reference"] == f"xbos:pay:{ATTEMPT}"
    assert call["json"]["amount"] == {"minor": 10000, "currency": "XAF"}
    assert call["json"]["permitted_options"] == [{"method": "MOBILE_MONEY", "rail": "MTN_MOMO"}]
    assert "provider" not in call["json"]
    assert result.checkout_session_id == CHECKOUT_ID
    assert result.public_token == "chkpub_current_contract_token"


def test_b_same_attempt_has_stable_external_reference_and_idempotency():
    first = request()
    second = request()
    assert first.external_reference == second.external_reference == f"xbos:pay:{ATTEMPT}"
    assert first.idempotency_key == second.idempotency_key == f"xbos-checkout-{ATTEMPT}"
    assert first.body() == second.body()


def test_c_different_payload_under_same_attempt_idempotency_fails_closed(monkeypatch):
    memory = {}

    def post(url, **kwargs):
        key = kwargs["headers"]["Idempotency-Key"]
        body = kwargs["json"]
        if key in memory and memory[key] != body:
            return Response(409, {"error": "IDEMPOTENCY_CONFLICT"})
        memory[key] = body
        req = request(body["amount"]["minor"])
        return Response(201, response_for(req))

    monkeypatch.setattr("core.integrations.xafpay_v2.client.httpx.post", post)
    client = XafPayV2Client("https://gateway.example", "xps_staging_abcdefghijkl.secret")
    client.create_checkout(request(10000))
    with pytest.raises(XafPayV2IntegrationError) as exc:
        client.create_checkout(request(9000))
    assert exc.value.code == "gateway_checkout_rejected"


def test_expired_checkout_replay_is_typed_and_does_not_invent_revision(monkeypatch):
    req = request()
    monkeypatch.setattr(
        "core.integrations.xafpay_v2.client.httpx.post",
        lambda *args, **kwargs: Response(200, response_for(req, status="EXPIRED")),
    )
    result = XafPayV2Client("https://gateway.example", "xps_staging_abcdefghijkl.secret").create_checkout(req)
    assert result.presentation_state == "PRESENTATION_EXPIRED"
    assert result.public_token is None


def test_forward_seam_contains_only_current_checkout_transport():
    seam = "\n".join(
        (ROOT / "core/integrations/xafpay_v2" / name).read_text(encoding="utf-8")
        for name in ("client.py", "contract.py", "repository.py", "router.py", "service.py", "wnd_service.py")
    )
    assert "/v2/checkout-sessions" in seam
    for forbidden in (
        "/v2/payments",
        "/execution-status",
        "OperatorRepairService",
        "QUERY_PROVIDER_STATUS",
        "tranzak",
        "uuid4()",
    ):
        assert forbidden not in seam


def test_legacy_paths_are_present_but_not_forward_authority():
    legacy = (ROOT / "core/integrations/xafpay/adapter.py").read_text(encoding="utf-8")
    webhook = (ROOT / "core/api/xafpay_webhook.py").read_text(encoding="utf-8")
    kernel = (ROOT / "core/api/kernel_router.py").read_text(encoding="utf-8")
    duplicate = ROOT / "core/api/payments/payments_xafpay.py"

    assert "/v1/payment-intents" in legacy
    assert "webhook" in webhook.lower()
    assert duplicate.exists()
    assert "payments_xafpay" not in kernel
    assert "xafpay_v2_router" in kernel
    assert 'prefix="/integrations/xafpay-v2"' in kernel

def test_signed_event_route_has_exact_global_middleware_bypass_only():
    exact = 'path == "/kernel/integrations/xafpay-v2/events"'
    for rel in (
        "core/middleware/auth_middleware.py",
        "core/middleware/tenant_middleware.py",
        "core/middleware/branch_middleware.py",
    ):
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert exact in source
        assert 'path.startswith("/kernel/integrations/xafpay-v2")' not in source
        assert 'path.startswith("/integrations/xafpay-v2")' not in source

    kernel = (ROOT / "core/api/kernel_router.py").read_text(encoding="utf-8")
    assert "xafpay_v2_router" in kernel
    assert 'prefix="/integrations/xafpay-v2"' in kernel

def test_signed_event_bypass_preserves_normal_auth_tenant_branch_behavior(monkeypatch):
    import asyncio

    monkeypatch.setenv("JWT_SECRET", "xgi1-test-jwt-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://xgi1:xgi1@127.0.0.1:1/xgi1")
    monkeypatch.setenv("GATEWAY_API_KEY", "xgi1-test-gateway-key")

    from fastapi import HTTPException
    from starlette.requests import Request
    from starlette.responses import Response as StarletteResponse

    from core.middleware.auth_middleware import AuthMiddleware
    from core.middleware.branch_middleware import BranchMiddleware
    from core.middleware.tenant_middleware import TenantMiddleware

    signed = "/kernel/integrations/xafpay-v2/events"
    near_miss = signed + "/extra"

    async def next_ok(request):
        return StarletteResponse(status_code=204)

    def req(path):
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
            }
        )

    async def exercise():
        monkeypatch.setenv("ENV", "production")

        auth = AuthMiddleware(lambda scope, receive, send: None)
        assert (await auth.dispatch(req(signed), next_ok)).status_code == 204
        assert (await auth.dispatch(req("/kernel/health"), next_ok)).status_code == 204
        assert (await auth.dispatch(req("/kernel/auth/login"), next_ok)).status_code == 204
        assert (await auth.dispatch(req("/kernel/protected"), next_ok)).status_code == 401
        assert (await auth.dispatch(req(near_miss), next_ok)).status_code == 401

        tenant = TenantMiddleware(lambda scope, receive, send: None)
        assert (await tenant.dispatch(req(signed), next_ok)).status_code == 204
        assert (await tenant.dispatch(req("/kernel/health"), next_ok)).status_code == 204
        assert (await tenant.dispatch(req("/kernel/auth/login"), next_ok)).status_code == 204
        try:
            await tenant.dispatch(req("/kernel/protected"), next_ok)
            raise AssertionError("tenant middleware should deny missing production context")
        except HTTPException as exc:
            assert exc.status_code == 400 and exc.detail == "MISSING_TENANT_HEADER"
        try:
            await tenant.dispatch(req(near_miss), next_ok)
            raise AssertionError("tenant near-miss path must not bypass")
        except HTTPException as exc:
            assert exc.status_code == 400 and exc.detail == "MISSING_TENANT_HEADER"

        branch = BranchMiddleware(lambda scope, receive, send: None)
        assert (await branch.dispatch(req(signed), next_ok)).status_code == 204
        assert (await branch.dispatch(req("/kernel/health"), next_ok)).status_code == 204
        assert (await branch.dispatch(req("/kernel/auth/login"), next_ok)).status_code == 204
        try:
            await branch.dispatch(req("/kernel/protected"), next_ok)
            raise AssertionError("branch middleware should deny missing context")
        except HTTPException as exc:
            assert exc.status_code == 400 and exc.detail == "TENANT_CONTEXT_MISSING"
        try:
            await branch.dispatch(req(near_miss), next_ok)
            raise AssertionError("branch near-miss path must not bypass")
        except HTTPException as exc:
            assert exc.status_code == 400 and exc.detail == "TENANT_CONTEXT_MISSING"

    asyncio.run(exercise())
