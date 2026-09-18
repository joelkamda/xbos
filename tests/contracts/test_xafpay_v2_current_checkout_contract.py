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
