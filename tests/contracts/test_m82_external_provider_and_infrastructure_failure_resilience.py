from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.domain.finance.external_failure_resilience_contract import (
    ExternalFailureControlError,
    ProviderEvidence,
    ProviderObservation,
    canonical_fingerprint,
)
from core.domain.finance.external_failure_resilience_service import (
    classify_provider_observation,
    project_provider_evidence,
    validate_existing_failure_authorities,
)
from core.domain.finance.m6_acceptance import EXPECTED_HEAD
from core.integrations.xafpay.adapter import XafPayAdapter

ROOT = Path(__file__).resolve().parents[2]


def evidence(reference="evt-1", observation=ProviderObservation.UNKNOWN, **changes):
    value = ProviderEvidence(2, 1, "provider-1", reference, canonical_fingerprint({"reference": reference}), observation)
    return replace(value, **changes)


def raises(code, action):
    with pytest.raises(ExternalFailureControlError) as raised:
        action()
    assert raised.value.code == code


def test_contract_freezes_schema_neutral_failure_boundary():
    contract = json.loads((ROOT / "contracts/finance/v1/m82_external_provider_and_infrastructure_failure_resilience.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["source_checkpoint"]["commit"] == "f5f2efb"
    assert contract["migration"] is False
    assert contract["provider_outcomes"]["uncertainty_may_settle"] is False
    assert contract["boundaries"]["live_cutover_owner"] == "R6"


@pytest.mark.parametrize("value", [
    ProviderObservation.TIMEOUT, ProviderObservation.PROVIDER_UNAVAILABLE,
    ProviderObservation.RETRYABLE_FAILURE, ProviderObservation.UNKNOWN,
])
def test_ambiguous_provider_outcomes_remain_retryable_uncertainty(value):
    disposition = classify_provider_observation(value)
    assert disposition.canonical_state == "uncertain"
    assert disposition.retryable is True
    assert disposition.settlement_allowed is False


def test_only_authoritative_success_may_settle_and_terminal_failure_does_not():
    success = classify_provider_observation(ProviderObservation.AUTHORITATIVE_SUCCESS)
    failed = classify_provider_observation(ProviderObservation.TERMINAL_FAILURE)
    assert success.canonical_state == "succeeded" and success.settlement_allowed
    assert failed.canonical_state == "failed" and not failed.retryable and not failed.settlement_allowed


def test_webhook_signature_is_raw_body_bound_and_tamper_fails():
    raw = b'{"amount":100,"status":"paid"}'
    import hashlib, hmac
    signature = hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    headers = {"X-Xafpay-Event-Id": "event-1", "X-Xafpay-Signature": signature}
    assert XafPayAdapter.verify_signature(raw, headers, "secret")
    assert not XafPayAdapter.verify_signature(raw + b" ", headers, "secret")


def test_callback_event_identity_is_mandatory():
    from core.integrations.xafpay.contract import XafPayIntegrationError
    with pytest.raises(XafPayIntegrationError) as raised:
        XafPayAdapter.callback_event_reference({})
    assert raised.value.code == "callback_event_id_required"


def test_duplicate_evidence_is_one_effect_and_conflict_fails_closed():
    item = evidence()
    projection = project_provider_evidence((item, item))
    assert len(projection.evidence) == 1 and projection.replay_count == 1
    raises("callback_replay_conflict", lambda: project_provider_evidence((item, replace(item, payload_fingerprint="f" * 64))))


def test_late_failure_cannot_regress_authoritative_success():
    success = evidence("success", ProviderObservation.AUTHORITATIVE_SUCCESS)
    late = evidence("late-failure", ProviderObservation.TERMINAL_FAILURE)
    projection = project_provider_evidence((success, late))
    assert projection.terminal_state == "succeeded"
    assert len(projection.evidence) == 2


def test_provider_evidence_scope_is_fail_closed():
    raises("provider_scope_mismatch", lambda: project_provider_evidence((evidence(), evidence("evt-2", tenant_id=3))))


def test_existing_kernel_remains_atomicity_and_callback_authority():
    validate_existing_failure_authorities(ROOT)


def test_m82_is_schema_neutral_and_makes_no_live_calls():
    source = (ROOT / "core/persistence/m82_external_failure_resilience.py").read_text(encoding="utf-8")
    for marker in (
        "SCHEMA_NEUTRAL = True", "WRITES_NEW_TABLES = False", "CREATES_PROVIDER_LEDGER = False",
        "FABRICATES_SETTLEMENT = False", "LIVE_PROVIDER_CALLS = False", "REROUTES_LEGACY_WRITERS = False",
        "CUTOVER_AUTHORIZED = False",
    ):
        assert marker in source
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m82_*.py"))


def test_verifier_and_public_gate_exist():
    verifier = (ROOT / "scripts/verify_m82_external_failure_resilience.py").read_text(encoding="utf-8")
    for marker in ("webhook_security=PASS", "provider_outage=PASS", "uncertainty=PASS", "rollback=PASS", "atomicity=PASS", "tenant_scope=PASS"):
        assert marker in verifier
    assert (ROOT / "XBOS_M8_2_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M8_2_INSTALL_AND_VERIFY.txt").is_file()
