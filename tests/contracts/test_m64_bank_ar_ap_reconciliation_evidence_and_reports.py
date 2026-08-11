from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.domain.finance.reconciliation_control_contract import (
    RecordReconciliationControlCommand, ReconciliationControlError,
    ReconciliationEvidenceReference, ReconciliationExplanation,
)
from core.domain.finance.reconciliation_report_service import _canonical_report_payload

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "alembic_neutral/sql/m64_reconciliation_controls_up.sql"
DOWN = ROOT / "alembic_neutral/sql/m64_reconciliation_controls_down.sql"
REVISION = ROOT / "alembic_neutral/versions/m64_reconciliation_controls_020_bank_ar_ap_evidence_and_reports.py"
CONTRACT = ROOT / "contracts/finance/v1/m64_bank_ar_ap_reconciliation_evidence_and_reports.json"
BASE = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)


def evidence(number=1, kind="bank_statement"):
    return ReconciliationEvidenceReference(
        UUID(f"64000000-0000-0000-0001-{number:012d}"), kind, f"statement-{number}", "external-control",
        BASE+timedelta(hours=2), {"sha_source": f"statement-{number}"},
    )


def explanation(amount="5"):
    return ReconciliationExplanation(UUID("64000000-0000-0000-0002-000000000001"), "timing_item",
        Decimal(amount), "Deposit in transit", evidence_reference="statement-1")


def command(kind="bank", **changes):
    values = dict(public_id=UUID("64000000-0000-0000-0000-000000000001"), tenant_id=2,
        organization_unit_id=1, control_type=kind, currency_code="XAF", period_start=BASE,
        period_end=BASE+timedelta(hours=8), as_of=BASE+timedelta(hours=8), control_position="105",
        occurred_at=BASE+timedelta(hours=9), business_date=date(2026,8,11), calendar_policy_version=1,
        correlation_id=UUID("64000000-0000-0000-0000-000000000099"), actor_service="m64.verifier",
        source_component="m64.verifier", source_record_id="control-1", idempotency_scope="m64.control",
        idempotency_key="control-1", evidence=(evidence(),), explanations=(explanation(),),
        operational_account_public_id=UUID("64000000-0000-0000-0000-000000000002"),
        reconciliation_window_public_id=UUID("64000000-0000-0000-0000-000000000003"))
    if kind != "bank":
        values.update(operational_account_public_id=None,reconciliation_window_public_id=None,
                      party_id=UUID("64000000-0000-0000-0000-000000000004"))
    values.update(changes)
    return RecordReconciliationControlCommand(**values)


def test_contract_is_shared_control_not_financial_authority():
    value=json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert value["authority"]["kind"] == "control_and_explanation"
    assert value["authority"]["shared_primitive"] is True
    assert value["control_types"] == ["bank","accounts_receivable","accounts_payable"]


def test_revision_linear_and_raw_dbapi():
    source=REVISION.read_text(encoding="utf-8")
    assert 'revision = "m64_reconciliation_controls_020"' in source
    assert 'down_revision = "m63_reconciliation_close_019"' in source
    assert ".connection.cursor()" in source and "exec_driver_sql" not in source


def test_sql_establishes_shared_immutable_authority():
    source=UP.read_text(encoding="utf-8")
    for token in ("reconciliation_controls","reconciliation_control_items","reconciliation_evidence_references",
                  "current_reconciliation_controls","xbos_validate_reconciliation_control",
                  "xbos_reject_reconciliation_control_mutation","canonical_closing=canonical_opening"):
        assert token in source


def test_down_removes_only_m64_objects():
    source=DOWN.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS public.reconciliation_controls" in source
    assert "DROP TABLE IF EXISTS public.reconciliation_windows" not in source
    assert "DROP TABLE IF EXISTS public.financial_obligations" not in source


@pytest.mark.parametrize("kind", ["bank","accounts_receivable","accounts_payable"])
def test_all_control_types_have_one_command_shape(kind):
    value=command(kind)
    assert value.control_type==kind and len(value.request_fingerprint)==64


def test_bank_requires_account_and_window():
    with pytest.raises(ReconciliationControlError) as raised:
        command(operational_account_public_id=None)
    assert raised.value.code=="invalid_bank_scope"


def test_party_control_rejects_bank_scope():
    with pytest.raises(ReconciliationControlError) as raised:
        command("accounts_receivable", operational_account_public_id=UUID(int=9))
    assert raised.value.code=="invalid_party_scope"


def test_evidence_is_required_and_hashed():
    assert len(evidence().evidence_hash)==64
    with pytest.raises(ReconciliationControlError) as raised:
        command(evidence=())
    assert raised.value.code=="evidence_required"


def test_evidence_type_is_governed():
    with pytest.raises(ReconciliationControlError) as raised:
        evidence(kind="uploaded_file_blob")
    assert raised.value.code=="invalid_evidence_type"


def test_fingerprint_changes_with_control_position():
    assert command().request_fingerprint != command(control_position="106").request_fingerprint


def test_engine_uses_type_specific_canonical_adapters_and_no_posting():
    engine=(ROOT/"core/domain/finance/reconciliation_control_engine.py").read_text(encoding="utf-8")
    repository=(ROOT/"core/domain/finance/reconciliation_control_repository.py").read_text(encoding="utf-8")
    assert "bank_position" in engine and "party_position" in engine
    assert "financial_obligations" in repository and "operational_account_balance_anchors" in repository
    assert "PostingEngine" not in engine and "financial_events(" not in engine


def test_reports_are_read_only_and_deterministically_fingerprinted():
    source=(ROOT/"core/domain/finance/reconciliation_report_service.py").read_text(encoding="utf-8")
    assert "report_fingerprint" in source and "ORDER BY sequence_number,id" in (ROOT/"core/domain/finance/reconciliation_control_repository.py").read_text(encoding="utf-8")
    assert "INSERT INTO" not in source and "UPDATE " not in source


def test_report_fingerprint_payload_normalizes_database_native_values():
    record=SimpleNamespace(public_id=UUID(int=64),control_type="bank",tenant_id=2,organization_unit_id=1,
        currency_code="XAF",canonical_opening=Decimal("100.00000000"),canonical_increases=Decimal("5.50000000"),
        canonical_decreases=Decimal("0.00000000"),canonical_adjustments=Decimal("0.00000000"),
        canonical_closing=Decimal("105.50000000"),control_position=Decimal("105.50000000"),
        explained_amount=Decimal("0.00000000"),unexplained_variance=Decimal("0.00000000"),
        reconciliation_status="balanced",revision_number=1,semantic_fingerprint="a"*64)
    payload=_canonical_report_payload(record,
        ({"amount":Decimal("5.50000000"),"reference":UUID(int=65),"on":date(2026,8,11)},),
        ({"observed_at":BASE,"evidence_hash":"b"*64},))
    assert payload["canonical_opening"]=="100"
    assert payload["explanations"][0]["amount"]=="5.5"
    assert payload["explanations"][0]["reference"]==str(UUID(int=65))
    assert payload["explanations"][0]["on"]=="2026-08-11"
    assert payload["evidence"][0]["observed_at"]=="2026-08-11T08:00:00Z"


def test_m65_freeze_is_not_absorbed():
    source="\n".join((UP.read_text(encoding="utf-8"),(ROOT/"core/domain/finance/reconciliation_control_engine.py").read_text(encoding="utf-8")))
    for forbidden in ("m6_release_manifest","M6_SINGLE_GATE","track-b-m6-treasury"):
        assert forbidden not in source


def test_verifier_and_document_exist():
    assert (ROOT/"scripts/verify_m64_reconciliation_controls.py").is_file()
    assert (ROOT/"docs/track_b/M6_4_BANK_AR_AP_RECONCILIATION_EVIDENCE_AND_REPORTS.md").is_file()
