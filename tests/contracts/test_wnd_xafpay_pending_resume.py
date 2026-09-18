from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from core.integrations.xafpay_v2.contract import XafPayV2CheckoutResponse
from core.integrations.xafpay_v2.repository import AttemptAuthority
from core.integrations.xafpay_v2.service import XafPayV2Service
from core.integrations.xafpay_v2.wnd_service import WndXafPayV2Service

ATTEMPT_ID = UUID("11111111-1111-5111-8111-111111111111")
CHECKOUT_ID = "chk_018d6f5a-3333-7333-8333-333333333333"


def pending_attempt(checkout_status="CREATED"):
    return AttemptAuthority(
        id=1,
        public_id=ATTEMPT_ID,
        tenant_id=2,
        organization_unit_id=1,
        payment_intent_public_id=UUID("33333333-3333-5333-8333-333333333333"),
        payment_tender_public_id=UUID("55555555-5555-5555-8555-555555555555"),
        attempt_state="pending",
        attempted_amount=Decimal("10000"),
        currency_code="XAF",
        payment_method_code="mobile_money",
        payment_rail_code="mtn_momo",
        orchestrator_code="xafpay",
        provider_account_id=None,
        underlying_provider_code=None,
        external_attempt_reference=None,
        occurred_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        business_date=date(2026, 9, 18),
        calendar_policy_version=1,
        correlation_id=UUID("44444444-4444-5444-8444-444444444444"),
        row_version=2,
        metadata={
            "order_id": 101,
            "sale_id": 202,
            "checkout_session_id": CHECKOUT_ID,
            "checkout_status": checkout_status,
        },
    )


class FakeRepository:
    def __init__(self, attempt):
        self.attempt = attempt
        self.bind_calls = []

    def latest_attempt_for_order(self, session, tenant_id, order_id):
        return self.attempt

    def bind_checkout_session(self, session, attempt, *, checkout_session_id, checkout_status):
        self.bind_calls.append((checkout_session_id, checkout_status))
        assert checkout_session_id == self.attempt.metadata["checkout_session_id"]
        return self.attempt

    def settlement_count_for_attempt(self, session, *, tenant_id, attempt_public_id):
        return 0


class FakeClient:
    def __init__(self, status="CREATED"):
        self.status = status
        self.requests = []

    def create_checkout(self, request):
        self.requests.append(request)
        return XafPayV2CheckoutResponse(
            checkout_session_id=CHECKOUT_ID,
            external_reference=request.external_reference,
            status=self.status,
            amount_minor=int(request.amount),
            currency_code="XAF",
            public_token=None if self.status == "EXPIRED" else "chkpub_resume_token",
            presentation_state=(
                "PRESENTATION_EXPIRED" if self.status == "EXPIRED" else "PRESENTABLE"
            ),
            evidence={},
        )


def test_r_check_status_and_order_recovery_make_zero_gateway_or_provider_calls():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    controller = (root / "core/api/payments/payments_controller.py").read_text(encoding="utf-8")
    status_block = controller.split("async def xafpay_attempt_status", 1)[1].split(
        "async def xafpay_order_recovery", 1
    )[0]
    recovery_block = controller.split("async def xafpay_order_recovery", 1)[1].split(
        "# =====================================================\n    # POS SETTLEMENT", 1
    )[0]
    for block in (status_block, recovery_block):
        assert "XafPayV2Client" not in block
        assert "httpx" not in block
        assert "/v2/" not in block
        assert "create_checkout" not in block
        assert "provider" not in block.lower()


def test_s_t_resume_reuses_same_attempt_and_same_idempotent_checkout(monkeypatch):
    repo = FakeRepository(pending_attempt())
    client = FakeClient()
    monkeypatch.setattr(XafPayV2Service, "repository", repo)

    first = WndXafPayV2Service.initiate_order(
        object(),
        tenant_id=2,
        organization_unit_id=1,
        order_id=101,
        sale_id=202,
        amount=Decimal("10000"),
        rail="MTN",
        client=client,
    )
    second = WndXafPayV2Service.initiate_order(
        object(),
        tenant_id=2,
        organization_unit_id=1,
        order_id=101,
        sale_id=202,
        amount=Decimal("10000"),
        rail="MTN",
        client=client,
    )

    assert first["attempt_public_id"] == second["attempt_public_id"] == str(ATTEMPT_ID)
    assert first["checkout_session_id"] == second["checkout_session_id"] == CHECKOUT_ID
    assert len(client.requests) == 2
    assert client.requests[0].idempotency_key == client.requests[1].idempotency_key
    assert client.requests[0].external_reference == client.requests[1].external_reference
    assert repo.bind_calls == [(CHECKOUT_ID, "CREATED"), (CHECKOUT_ID, "CREATED")]


def test_resume_payload_change_fails_before_checkout_replay(monkeypatch):
    repo = FakeRepository(pending_attempt())
    client = FakeClient()
    monkeypatch.setattr(XafPayV2Service, "repository", repo)

    with pytest.raises(RuntimeError, match="XAFPAY_WND_ATTEMPT_IDEMPOTENCY_CONFLICT"):
        WndXafPayV2Service.initiate_order(
            object(),
            tenant_id=2,
            organization_unit_id=1,
            order_id=101,
            sale_id=202,
            amount=Decimal("9000"),
            rail="MTN",
            client=client,
        )
    assert client.requests == []


def test_expired_presentation_returns_typed_state_without_new_revision(monkeypatch):
    repo = FakeRepository(pending_attempt("EXPIRED"))
    client = FakeClient(status="EXPIRED")
    monkeypatch.setattr(XafPayV2Service, "repository", repo)

    result = WndXafPayV2Service.initiate_order(
        object(),
        tenant_id=2,
        organization_unit_id=1,
        order_id=101,
        sale_id=202,
        amount=Decimal("10000"),
        rail="MTN",
        client=client,
    )
    assert result["status"] == "PRESENTATION_EXPIRED"
    assert result["presentation_state"] == "PRESENTATION_EXPIRED"
    assert result["checkout_token"] is None
    assert result["checkout_session_id"] == CHECKOUT_ID
