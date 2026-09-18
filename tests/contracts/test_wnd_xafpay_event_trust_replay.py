from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

import core.integrations.xafpay_v2.service as service_module
from core.integrations.xafpay_v2.contract import (
    XafPayV2IntegrationError,
    parse_gateway_event,
)
from core.integrations.xafpay_v2.repository import AttemptAuthority, EventReservation
from core.integrations.xafpay_v2.service import XafPayV2Service

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
SECRET = "r1-offline-signing-secret"
ATTEMPT_ID = UUID("11111111-1111-5111-8111-111111111111")
PAYMENT_ID = "pay_018d6f5a-3333-7333-8333-333333333333"
MERCHANT_ID = "mch_018d6f5a-1111-7111-8111-111111111111"
ACCOUNT_ID = UUID("22222222-2222-5222-8222-222222222222")


def attempt() -> AttemptAuthority:
    return AttemptAuthority(
        id=1,
        public_id=ATTEMPT_ID,
        tenant_id=2,
        organization_unit_id=1,
        payment_intent_public_id=UUID("33333333-3333-5333-8333-333333333333"),
        payment_tender_public_id=None,
        attempt_state="pending",
        attempted_amount=Decimal("10000"),
        currency_code="XAF",
        payment_method_code="mobile_money",
        payment_rail_code="mtn_momo",
        orchestrator_code="xafpay",
        provider_account_id=None,
        underlying_provider_code=None,
        external_attempt_reference=None,
        occurred_at=NOW,
        business_date=date(2026, 9, 18),
        calendar_policy_version=1,
        correlation_id=UUID("44444444-4444-5444-8444-444444444444"),
        row_version=1,
        metadata={"order_id": 101, "sale_id": 202},
    )


class FakeRepository:
    def __init__(self):
        self.current = attempt()
        self.events = {}
        self.settlements = 0
        self.balance_due = Decimal("10000")
        self.wnd_cleared = False

    def attempt_authority(self, session, attempt_public_id, *, lock=False):
        return self.current

    def attempt_by_gateway_payment_id(self, session, payment_id, *, lock=False):
        return self.current if self.current.external_attempt_reference == payment_id else None

    def reserve_event(self, session, *, tenant_id, event_id, fingerprint):
        previous = self.events.get(event_id)
        if previous is None:
            self.events[event_id] = [fingerprint, "processing", None]
            return EventReservation(len(self.events), fingerprint, "processing", None, True)
        return EventReservation(1, previous[0], previous[1], previous[2], False)

    def complete_event(self, session, reservation, response):
        for event_id, value in self.events.items():
            if value[0] == reservation.fingerprint and value[1] == "processing":
                self.events[event_id] = [value[0], "completed", dict(response)]
                return
        raise AssertionError("reservation not found")

    def settlement_count_for_attempt(self, session, *, tenant_id, attempt_public_id):
        return self.settlements

    def finalize_wnd_projection(self, session, current, *, confirmed_at):
        self.balance_due = max(Decimal("0"), self.balance_due - current.attempted_amount)
        self.wnd_cleared = self.balance_due == 0
        return self.wnd_cleared

    def reversal_count_for_attempt(self, session, *, tenant_id, attempt_public_id):
        return 0


def payload(
    event_type: str,
    *,
    event_id: str = "evt_018d6f5a-6000-7600-8600-000000000001",
    merchant_id: str = MERCHANT_ID,
    attempt_id: UUID = ATTEMPT_ID,
    payment_id: str = PAYMENT_ID,
    amount: int = 10000,
    currency: str = "XAF",
    provider_event_id: str = "provider-event-1",
):
    status = {
        "payment.created": "CREATED",
        "payment.requires_action": "REQUIRES_ACTION",
        "payment.pending": "PENDING",
        "payment.succeeded": "SUCCEEDED",
        "payment.failed": "FAILED",
        "payment.canceled": "CANCELED",
        "payment.expired": "EXPIRED",
    }[event_type]
    return {
        "id": event_id,
        "type": event_type,
        "version": 1,
        "occurred_at": "2026-09-18T12:00:00.000Z",
        "aggregate_type": "Payment",
        "aggregate_id": payment_id,
        "merchant_id": merchant_id,
        "correlation_id": "cor_018d6f5a-2222-7222-8222-222222222222",
        "causation_id": None,
        "data": {
            "payment_id": payment_id,
            "external_reference": f"xbos:pay:{attempt_id}",
            "amount": {"minor": amount, "currency": currency},
            "status": status,
            "requested_method": "MOBILE_MONEY",
            "requested_rail": "MTN_MOMO",
            "attempt_id": "pat_018d6f5a-4444-7444-8444-444444444444",
            "provider": "sandbox_provider",
            "provider_account_id": "pva_018d6f5a-5555-7555-8555-555555555555",
            "provider_reference": "provider-ref-1" if event_type == "payment.succeeded" else None,
            "provider_event_id": provider_event_id,
            "provider_occurred_at": "2026-09-18T12:00:00.000Z",
        },
    }


def signed(value: dict):
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    timestamp = int(NOW.timestamp())
    message = f"v1.{timestamp}.{value['id']}.{hashlib.sha256(raw).hexdigest()}".encode()
    signature = hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()
    return raw, {
        "x-xafpay-event-id": value["id"],
        "x-xafpay-timestamp": str(timestamp),
        "x-xafpay-signature": f"v1={signature}",
        "x-xafpay-signature-version": "1",
    }


def install_fakes(monkeypatch, repo: FakeRepository):
    monkeypatch.setattr(XafPayV2Service, "repository", repo)

    def transition(cls, session, command):
        current = repo.current
        repo.current = replace(
            current,
            attempt_state=command.target_state,
            external_attempt_reference=(
                command.external_attempt_reference or current.external_attempt_reference
            ),
            row_version=current.row_version + 1,
        )
        return SimpleNamespace(
            payment_attempt=SimpleNamespace(public_id=repo.current.public_id)
        )

    def settle(cls, session, current, event, operational_account_public_id):
        repo.settlements += 1

    monkeypatch.setattr(
        service_module.TransactionalPaymentAttemptEngine,
        "transition",
        classmethod(transition),
    )
    monkeypatch.setattr(XafPayV2Service, "_settle", classmethod(settle))


def consume(repo, monkeypatch, value):
    install_fakes(monkeypatch, repo)
    raw, headers = signed(value)
    return XafPayV2Service.consume_event(
        object(),
        raw_body=raw,
        headers=headers,
        signing_secret=SECRET,
        expected_gateway_merchant_id=MERCHANT_ID,
        operational_account_public_id=ACCOUNT_ID,
        now=NOW,
    )


def test_signature_event_identity_and_current_payment_contract_pass(monkeypatch):
    repo = FakeRepository()
    result = consume(repo, monkeypatch, payload("payment.pending"))
    assert result["accepted"] is True
    assert repo.current.external_attempt_reference == PAYMENT_ID
    assert repo.current.attempt_state == "processing"
    assert repo.settlements == 0


def test_g_i_signed_success_settles_exactly_once_and_replay_is_idempotent(monkeypatch):
    repo = FakeRepository()
    value = payload("payment.succeeded")
    first = consume(repo, monkeypatch, value)
    second = consume(repo, monkeypatch, value)
    assert first["effect"] == "SETTLED_ONCE"
    assert second["replayed"] is True
    assert repo.settlements == 1
    assert repo.current.attempt_state == "succeeded"
    assert repo.wnd_cleared is True


def test_j_failure_creates_no_success_settlement(monkeypatch):
    repo = FakeRepository()
    result = consume(repo, monkeypatch, payload("payment.failed"))
    assert result["confirmed_settlements"] == 0
    assert repo.settlements == 0
    assert repo.current.attempt_state == "failed"
    assert repo.wnd_cleared is False


def test_expired_event_is_evidence_only_until_xbos_timeout_authority(monkeypatch):
    repo = FakeRepository()
    result = consume(repo, monkeypatch, payload("payment.expired"))
    assert result["confirmed_settlements"] == 0
    assert result["anomaly"] == "GATEWAY_EXPIRED_NO_XBOS_TIMEOUT_AUTHORITY"
    assert repo.settlements == 0
    assert repo.current.attempt_state == "processing"
    assert repo.wnd_cleared is False


def test_l_same_event_id_with_different_canonical_bytes_conflicts(monkeypatch):
    repo = FakeRepository()
    first = payload("payment.pending")
    consume(repo, monkeypatch, first)
    second = payload("payment.pending", provider_event_id="provider-event-2")
    with pytest.raises(XafPayV2IntegrationError) as exc:
        consume(repo, monkeypatch, second)
    assert exc.value.code == "event_identity_conflict"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"amount": 9999}, "gateway_amount_mismatch"),
        ({"currency": "USD"}, "event_amount_invalid"),
        ({"merchant_id": "mch_018d6f5a-9999-7999-8999-999999999999"}, "gateway_merchant_mismatch"),
        ({"attempt_id": UUID("99999999-9999-5999-8999-999999999999")}, "external_reference_mismatch"),
    ],
)
def test_m_n_o_p_identity_amount_currency_merchant_mismatches_fail_closed(
    monkeypatch, change, expected
):
    repo = FakeRepository()
    kwargs = {}
    merchant = change.get("merchant_id")
    if merchant:
        kwargs["merchant_id"] = merchant
    if "attempt_id" in change:
        kwargs["attempt_id"] = change["attempt_id"]
    if "amount" in change:
        kwargs["amount"] = change["amount"]
    if "currency" in change:
        kwargs["currency"] = change["currency"]
    with pytest.raises(XafPayV2IntegrationError) as exc:
        consume(repo, monkeypatch, payload("payment.pending", **kwargs))
    assert exc.value.code == expected
    assert repo.settlements == 0


def test_q_late_failure_after_success_does_not_roll_back(monkeypatch):
    repo = FakeRepository()
    consume(repo, monkeypatch, payload("payment.succeeded"))
    late = payload(
        "payment.failed",
        event_id="evt_018d6f5a-6000-7600-8600-000000000002",
    )
    result = consume(repo, monkeypatch, late)
    assert result["anomaly"] == "LATE_NON_SUCCESS_AFTER_SUCCESS"
    assert repo.current.attempt_state == "succeeded"
    assert repo.settlements == 1


def test_current_payment_reversal_schema_does_not_require_external_reference():
    value = {
        "id": "evt_018d6f5a-6000-7600-8600-000000000003",
        "type": "payment.reversed",
        "version": 1,
        "occurred_at": "2026-09-18T12:00:00.000Z",
        "aggregate_type": "Reversal",
        "aggregate_id": "rev_018d6f5a-7777-7777-8777-777777777777",
        "merchant_id": MERCHANT_ID,
        "correlation_id": "cor_018d6f5a-2222-7222-8222-222222222222",
        "causation_id": None,
        "data": {
            "reversal_id": "rev_018d6f5a-7777-7777-8777-777777777777",
            "payment_id": PAYMENT_ID,
            "amount": {"minor": 2500, "currency": "XAF"},
            "provider": "sandbox_provider",
            "provider_account_id": "pva_018d6f5a-5555-7555-8555-555555555555",
            "provider_reference": "provider-ref-1",
            "reason": "provider_reversal",
        },
    }
    raw, headers = signed(value)
    event = parse_gateway_event(raw, headers)
    assert event.event_type == "payment.reversed"
    assert event.payment_attempt_public_id is None
    assert event.external_reference is None
    assert event.correction_id.startswith("rev_")
