from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.correction_contract import (
    ClassifyLifecycleDispositionCommand,
    CorrectionContext,
    CorrectionDocumentReference,
    CorrectionLifecycleError,
    RecognizeChargebackCommand,
    RecognizeCommercialReturnCommand,
    RecognizeRefundCommand,
    ReverseFinancialFactCommand,
    WriteOffObligationCommand,
)
from core.domain.finance.correction_engine import TransactionalCorrectionLifecycleEngine
from core.domain.finance.correction_service import LifecycleDispositionService
from core.domain.finance.obligation_contract import TransitionObligationCommand
from core.domain.finance.provider_financial_contract import CreateProviderSettlementComponentCommand


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m54_refunds_corrections_and_loss_events.json"
BASE = datetime(2026, 8, 10, 14, tzinfo=timezone.utc)
HASH = "a" * 64


def document(kind="correction_note", number="M54-1", evidence=HASH):
    return CorrectionDocumentReference(kind, number, evidence)


def context(kind="correction_note", amount="10", number=1):
    return CorrectionContext(UUID(f"54000000-0000-0000-0001-{number:012d}"), 1, 2, number, amount, "xaf", BASE, date(2026, 8, 10), 1, UUID(int=54), "m54.correction", "tests", document(kind))


def transition(public_id=UUID(int=81), target="written_off"):
    return TransitionObligationCommand(1, public_id, target, 1, "approved_loss", "m54.writeoff.transition", "writeoff-1", actor_service="tests")


def component(kind="chargeback_loss", evidence=None):
    payload = evidence or {"document_type": "chargeback_notice", "document_number": "CB-1"}
    return CreateProviderSettlementComponentCommand(UUID(int=71), 1, 2, UUID(int=72), UUID(int=73), kind, kind, "10", "XAF", "provider-cb-1", date(2026, 8, 10), payload, BASE, date(2026, 8, 10), 1, UUID(int=54), "tests", "cb-1", "m54.chargeback", "cb-1", actor_service="tests")


def test_contract_is_valid_schema_neutral_and_at_frozen_head():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["contract_code"] == "XBOS_M54_REFUNDS_CORRECTIONS_AND_LOSS_EVENTS"
    assert data["canonical_head"] == "m46_provider_financials_015"
    assert data["migration"] is False


def test_contract_groups_all_corrective_lifecycles():
    assert set(json.loads(CONTRACT.read_text())["scope"]) == {"refunds", "commercial_returns", "financial_reversals", "chargebacks", "receivable_writeoffs", "payable_forgiveness", "correction_documents"}


@pytest.mark.parametrize("kind", ["credit_note", "correction_note", "refund_notice", "cancellation_notice", "void_notice", "reversal_notice", "chargeback_notice", "writeoff_notice"])
def test_approved_document_types(kind):
    assert document(kind).document_type == kind


def test_unknown_document_type_rejected():
    with pytest.raises(CorrectionLifecycleError) as raised: document("memo")
    assert raised.value.code == "document_type_invalid"


@pytest.mark.parametrize("evidence", ["A" * 64, "a" * 63, "x" * 64])
def test_invalid_evidence_hash_rejected(evidence):
    with pytest.raises(CorrectionLifecycleError) as raised: document(evidence=evidence)
    assert raised.value.code == "evidence_hash_invalid"


def test_cancel_before_financial_truth_is_nonfinancial():
    result = LifecycleDispositionService.classify(ClassifyLifecycleDispositionCommand("cancel", False, False, False))
    assert result.creates_financial_event is False and result.action == "cancel"


def test_cancel_after_posting_is_rejected():
    with pytest.raises(CorrectionLifecycleError) as raised: ClassifyLifecycleDispositionCommand("cancel", True, False, False)
    assert raised.value.code == "cancellation_too_late"


def test_void_before_external_finality_is_nonfinancial():
    result = LifecycleDispositionService.classify(ClassifyLifecycleDispositionCommand("void", False, False, False))
    assert result.creates_financial_event is False and result.action == "void"


@pytest.mark.parametrize("posted,settled,external", [(True, False, False), (False, True, False), (False, False, True)])
def test_void_after_authoritative_effect_is_rejected(posted, settled, external):
    with pytest.raises(CorrectionLifecycleError) as raised: ClassifyLifecycleDispositionCommand("void", posted, settled, external)
    assert raised.value.code == "void_too_late"


def test_reverse_requires_original_financial_event():
    with pytest.raises(CorrectionLifecycleError) as raised: ClassifyLifecycleDispositionCommand("reverse", False, False, False)
    assert raised.value.code == "reversal_original_required"


def test_reverse_classification_requires_financial_event():
    result = LifecycleDispositionService.classify(ClassifyLifecycleDispositionCommand("reverse", True, False, False))
    assert result.creates_financial_event is True and result.action == "reverse"


def test_refund_requires_refund_or_credit_document():
    with pytest.raises(CorrectionLifecycleError) as raised: RecognizeRefundCommand(context("correction_note"), UUID(int=4), UUID(int=5), "customer_request")
    assert raised.value.code == "refund_document_required"


def test_refund_event_uses_outgoing_settlement_profile_and_links_evidence():
    command = RecognizeRefundCommand(context("refund_notice"), UUID(int=4), UUID(int=5), "customer_request")
    event = TransactionalCorrectionLifecycleEngine._event(command.context, "REFUND_SETTLED", "settlement_out", {"refund_reason": {"code": command.refund_reason}}, "customer_refund", metadata={"original_settlement_public_id": str(command.original_settlement_public_id)})
    assert event.event_type_code == "REFUND_SETTLED"
    assert event.posting_context["posting_profile_code"] == "customer_refund"
    assert event.evidence_hash == HASH


def test_commercial_return_requires_credit_or_correction_note():
    with pytest.raises(CorrectionLifecycleError) as raised: RecognizeCommercialReturnCommand(context("refund_notice"), UUID(int=6), "returned")
    assert raised.value.code == "return_document_required"


def test_generic_reversal_requires_reversal_or_correction_notice():
    with pytest.raises(CorrectionLifecycleError) as raised: ReverseFinancialFactCommand(context("credit_note"), UUID(int=6), "error")
    assert raised.value.code == "reversal_document_required"


@pytest.mark.parametrize("role,profile", [("receivable", "receivable_writeoff"), ("payable", "payable_forgiveness")])
def test_writeoff_selects_role_specific_profile(role, profile):
    ctx = context("writeoff_notice")
    command = WriteOffObligationCommand(ctx, UUID(int=81), role, "approved_loss", transition())
    event = TransactionalCorrectionLifecycleEngine._event(ctx, "OBLIGATION_WRITTEN_OFF", "correction", {"obligation_role": {"code": role}}, profile)
    assert command.obligation_role == role and event.posting_context["posting_profile_code"] == profile


def test_writeoff_transition_must_target_same_obligation():
    with pytest.raises(CorrectionLifecycleError) as raised: WriteOffObligationCommand(context("writeoff_notice"), UUID(int=81), "receivable", "loss", transition(UUID(int=82)))
    assert raised.value.code == "writeoff_transition_mismatch"


def test_writeoff_requires_writeoff_notice():
    with pytest.raises(CorrectionLifecycleError) as raised: WriteOffObligationCommand(context("correction_note"), UUID(int=81), "receivable", "loss", transition())
    assert raised.value.code == "writeoff_document_required"


def test_chargeback_must_delegate_provider_loss_component():
    command = RecognizeChargebackCommand(component(), document("chargeback_notice", "CB-1", component().evidence_hash))
    assert command.component.component_type == "chargeback_loss"


def test_non_chargeback_provider_component_rejected():
    with pytest.raises(CorrectionLifecycleError) as raised: RecognizeChargebackCommand(component("provider_fee"), document("chargeback_notice", "CB-1", component("provider_fee").evidence_hash))
    assert raised.value.code == "chargeback_component_required"


def test_context_normalizes_currency_and_amount():
    selected = context(amount="10.5")
    assert selected.currency_code == "XAF" and str(selected.amount) == "10.5"


def test_context_requires_timezone():
    with pytest.raises(CorrectionLifecycleError) as raised: replace(context(), occurred_at=BASE.replace(tzinfo=None))
    assert raised.value.code == "timezone_required"


def test_persistence_marker_declares_schema_neutrality():
    source = (ROOT / "core/persistence/m54_correction_lifecycles.py").read_text(encoding="utf-8")
    assert "SCHEMA_NEUTRAL = True" in source and "WRITES_NEW_TABLES = False" in source


def test_verifier_has_durable_acceptance_markers():
    source = (ROOT / "scripts/verify_m54_correction_lifecycles.py").read_text(encoding="utf-8")
    for marker in ("disposition=PASS", "refunds=PASS", "reversals=PASS", "chargebacks=PASS", "writeoffs=PASS", "documents=PASS", "dropped=true"):
        assert marker in source
