"""M4.5 contract checks: XafPay is a strict external adapter, not kernel policy."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from core.integrations.xafpay.adapter import XafPayAdapter
from core.integrations.xafpay.contract import (
    ProcessXafPayCallbackCommand,
    XafPayInitiationRequest,
    XafPayIntegrationError,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m45_xafpay_orchestration.json"
INTEGRATION = ROOT / "core/integrations/xafpay"


def _request(**changes):
    values = dict(
        payment_attempt_public_id=UUID("45000000-0000-0000-0000-000000000001"),
        amount="100",
        currency_code="XAF",
        payment_rail_code="mtn_momo",
        customer_phone="+237670000000",
        return_url="https://merchant.example/paid",
        cancel_url="https://merchant.example/cancelled",
        idempotency_key="m45-attempt-1",
        description="XBOS payment",
    )
    values.update(changes)
    return XafPayInitiationRequest(**values)


def _callback_body(status="succeeded"):
    return json.dumps(
        {
            "callback_reference": "cb-1",
            "payment_id": "45000000-0000-0000-0000-000000000001",
            "gateway_intent_id": "45000000-0000-0000-0000-000000000002",
            "status": status,
            "amount": 100,
            "currency": "XAF",
            "provider": "tranzak",
            "provider_ref": "provider-transaction-1",
            "occurred_at": "2026-08-09T14:00:00Z",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_contract_is_valid_and_declares_no_migration():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["canonical_head"] == "m44_payment_patterns_014"
    assert contract["migration"] is None
    assert contract["boundary"]["finance_kernel_provider_logic"] is False


def test_initiation_maps_mobile_money_to_current_xafpay_wire_shape():
    headers, body = XafPayAdapter.initiation_envelope(_request(), api_key="secret-api-key")
    assert body == {
        "amount": 100,
        "currency": "XAF",
        "provider": "tranzak",
        "requestedRail": "mtn",
        "customer": {"phone": "+237670000000"},
        "externalId": "45000000-0000-0000-0000-000000000001",
        "returnUrl": "https://merchant.example/paid",
        "cancelUrl": "https://merchant.example/cancelled",
        "description": "XBOS payment",
    }
    assert headers["Idempotency-Key"] == "m45-attempt-1"
    assert headers["X-API-Key"] == "secret-api-key"


def test_orange_money_mapping_is_explicit():
    _, body = XafPayAdapter.initiation_envelope(_request(payment_rail_code="orange_money"), api_key="k")
    assert body["requestedRail"] == "orange"


@pytest.mark.parametrize("amount", ["10.5", "0", "-1", "NaN"])
def test_xafpay_amount_requires_positive_whole_xaf(amount):
    with pytest.raises(XafPayIntegrationError) as caught:
        _request(amount=amount)
    assert caught.value.code in {"invalid_xaf_amount", "invalid_amount"}


def test_non_xaf_currency_is_rejected():
    with pytest.raises(XafPayIntegrationError) as caught:
        _request(currency_code="USD")
    assert caught.value.code == "unsupported_currency"


def test_unknown_rail_is_rejected():
    with pytest.raises(XafPayIntegrationError) as caught:
        _request(payment_rail_code="card")
    assert caught.value.code == "unsupported_rail"


def test_signature_is_exact_raw_body_hmac_sha256():
    raw = _callback_body()
    signature = hmac.new(b"callback-secret", raw, hashlib.sha256).hexdigest()
    assert XafPayAdapter.verify_signature(raw, {"X-Xafpay-Signature": signature}, "callback-secret")
    assert not XafPayAdapter.verify_signature(raw + b" ", {"X-Xafpay-Signature": signature}, "callback-secret")


@pytest.mark.parametrize("headers,secret", [({}, "secret"), ({"X-Xafpay-Signature": ""}, "secret"), ({"X-Xafpay-Signature": "0" * 64}, "")])
def test_signature_verification_fails_closed(headers, secret):
    assert not XafPayAdapter.verify_signature(_callback_body(), headers, secret)


def test_callback_normalization_preserves_gateway_authority():
    raw = _callback_body()
    callback = XafPayAdapter.normalize_callback(raw, {"X-Xafpay-Event-Id": "event-1"})
    assert callback.provider_event_reference == "event-1"
    assert callback.payment_attempt_public_id == UUID("45000000-0000-0000-0000-000000000001")
    assert callback.gateway_intent_id == UUID("45000000-0000-0000-0000-000000000002")
    assert callback.payload_hash == hashlib.sha256(raw).hexdigest()
    assert callback.status == "succeeded"


def test_event_identity_is_required():
    with pytest.raises(XafPayIntegrationError) as caught:
        XafPayAdapter.normalize_callback(_callback_body(), {})
    assert caught.value.code == "callback_event_id_required"


def test_unknown_callback_status_is_rejected():
    with pytest.raises(XafPayIntegrationError) as caught:
        XafPayAdapter.normalize_callback(_callback_body("mystery"), {"X-Xafpay-Event-Id": "event-1"})
    assert caught.value.code == "unknown_callback_status"


def test_process_command_requires_raw_bytes_and_a_secret():
    common = dict(
        tenant_id=1,
        organization_unit_id=1,
        provider_account_public_id=UUID(int=1),
        operational_account_public_id=UUID(int=2),
        headers={"X-Xafpay-Event-Id": "event-1"},
        callback_secret="secret",
        received_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        business_date=date(2026, 8, 9),
        calendar_policy_version=1,
        correlation_id=UUID(int=3),
    )
    with pytest.raises(XafPayIntegrationError):
        ProcessXafPayCallbackCommand(raw_body=b"", **common)
    with pytest.raises(XafPayIntegrationError):
        ProcessXafPayCallbackCommand(raw_body=b"{}", **{**common, "callback_secret": ""})


def test_integration_source_does_not_implement_network_transport_or_routes():
    source = "\n".join(path.read_text(encoding="utf-8") for path in INTEGRATION.glob("*.py"))
    assert "import requests" not in source
    assert "import httpx" not in source
    assert "APIRouter" not in source
    assert "FastAPI" not in source
    assert "XafPayTransport" in source


def test_xafpay_logic_is_not_added_to_finance_kernel():
    finance = ROOT / "core/domain/finance"
    if finance.exists():
        assert all("xafpay" not in path.name.lower() for path in finance.glob("*.py"))


def test_callback_repository_uses_frozen_immutable_evidence_table():
    source = (INTEGRATION / "repository.py").read_text(encoding="utf-8")
    assert "INSERT INTO public.provider_callback_events" in source
    assert "UPDATE public.provider_callback_events" not in source
    assert "DELETE FROM public.provider_callback_events" not in source


def test_attempt_lock_targets_only_the_non_nullable_authority_row():
    source = (INTEGRATION / "repository.py").read_text(encoding="utf-8")
    assert 'locking = "FOR UPDATE OF a" if lock else ""' in source
    assert 'locking = "FOR UPDATE" if lock else ""' not in source


def test_orchestration_delegates_financial_truth_to_existing_engines():
    source = (INTEGRATION / "orchestration_service.py").read_text(encoding="utf-8")
    assert "TransactionalPaymentAttemptEngine.transition" in source
    assert "TransactionalPaymentSettlementEngine.create" in source
    assert "TransactionalPaymentSettlementEngine.transition" in source
    assert "callback_replay_conflict" in source
    assert 'processing_state = "ignored"' in source


def test_orchestration_reads_the_frozen_m42_result_attribute():
    source = (INTEGRATION / "orchestration_service.py").read_text(encoding="utf-8")
    assert "result.payment_attempt" in source
    assert "result.attempt" not in source


def test_secrets_are_not_members_of_normalized_callback_or_result_contracts():
    source = (INTEGRATION / "contract.py").read_text(encoding="utf-8")
    normalized = source.split("class NormalizedXafPayCallback", 1)[1]
    assert "callback_secret" not in normalized
    assert "api_key" not in normalized


def test_acceptance_verifier_has_required_safety_markers():
    source = (ROOT / "scripts/verify_m45_xafpay_orchestration.py").read_text(encoding="utf-8")
    for token in (
        'DEVELOPMENT_DATABASE_NAME="xbos_track_b_dev"',
        'TEST_DATABASE_NAME="xbos_track_b_m45_xafpay_test"',
        'TARGET_REVISION="m44_payment_patterns_014"',
        "callback_replay_conflict",
        "out_of_order",
        "dropped=true",
    ):
        assert token in source


def test_acceptance_counts_the_triggered_and_commanded_settlement_transitions():
    source = (ROOT / "scripts/verify_m45_xafpay_orchestration.py").read_text(encoding="utf-8")
    assert '"payment_settlement_transitions":2' in source
    assert '[(1,None,"pending"),(2,"pending","confirmed")]' in source
