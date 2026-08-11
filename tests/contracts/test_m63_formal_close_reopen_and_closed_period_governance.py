from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.reconciliation_close_contract import (
    CloseReconciliationWindowCommand,
    ReconciliationCloseValidationError,
    ReopenReconciliationWindowCommand,
)

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "alembic_neutral/sql/m63_reconciliation_close_governance_up.sql"
DOWN = ROOT / "alembic_neutral/sql/m63_reconciliation_close_governance_down.sql"
REVISION = ROOT / "alembic_neutral/versions/m63_reconciliation_close_019_formal_close_reopen_and_period_protection.py"
CONTRACT = ROOT / "contracts/finance/v1/m63_formal_close_reopen_and_closed_period_governance.json"
BASE = datetime(2026, 8, 11, 9, tzinfo=timezone.utc)


def close(**changes):
    values = dict(
        public_id=UUID("63000000-0000-0000-0000-000000000001"), tenant_id=2,
        organization_unit_id=1, reconciliation_window_public_id=UUID("63000000-0000-0000-0000-000000000002"),
        governed_revision_number=2, accounting_period_code="2026-08", close_disposition="balanced",
        transition_reason="shift_reconciled", evidence_payload={"count_sheet": "sha256:approved"},
        occurred_at=BASE, business_date=date(2026, 8, 10), calendar_policy_version=1,
        correlation_id=UUID("63000000-0000-0000-0000-000000000099"), actor_service="m63.verifier",
        source_component="m63.verifier", source_record_id="close-1", idempotency_scope="m63.close",
        idempotency_key="close-1",
    )
    values.update(changes)
    return CloseReconciliationWindowCommand(**values)


def reopen(**changes):
    values = dict(
        public_id=UUID("63000000-0000-0000-0000-000000000003"), tenant_id=2,
        organization_unit_id=1,
        reconciliation_window_public_id=UUID("63000000-0000-0000-0000-000000000002"),
        governed_revision_number=2, accounting_period_code="2026-08", causation_id=None,
        correlation_id=UUID("63000000-0000-0000-0000-000000000099"),
        prior_close_public_id=close().public_id, transition_reason="approved_late_evidence",
        evidence_payload={"approval": "signed"}, approved_by_user_id=7,
        approved_at=BASE + timedelta(minutes=1), occurred_at=BASE + timedelta(minutes=2),
        business_date=date(2026, 8, 10), calendar_policy_version=1, actor_service="m63.verifier",
        source_component="m63.verifier",
        source_record_id="reopen-1", idempotency_scope="m63.reopen", idempotency_key="reopen-1",
        metadata={}, actor_user_id=None,
    )
    values.update(changes)
    return ReopenReconciliationWindowCommand(**values)


def test_contract_json_is_valid_and_scoped():
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert value["contract_code"].startswith("XBOS_M63_")
    assert "bank_reconciliation" in value["explicit_exclusions"]
    assert value["authority"]["relationship"] == "separate_but_coordinated"


def test_revision_is_linear_and_uses_raw_dbapi_for_percent_rowtype():
    source = REVISION.read_text(encoding="utf-8")
    assert 'revision = "m63_reconciliation_close_019"' in source
    assert 'down_revision = "m62_reconciliation_windows_018"' in source
    assert ".connection.cursor()" in source
    assert "exec_driver_sql" not in source


def test_up_sql_establishes_append_only_governance_and_closed_boundary():
    source = UP.read_text(encoding="utf-8")
    for token in (
        "reconciliation_window_governance_events", "current_reconciliation_window_governance",
        "xbos_validate_reconciliation_governance_transition", "xbos_reject_reconciliation_governance_mutation",
        "tr_closed_window_financial_event_protection", "tr_closed_window_cascade_protection",
        "tr_closed_window_revision_protection", "accounting_periods%ROWTYPE",
    ):
        assert token in source


def test_down_sql_removes_only_m63_authority():
    source = DOWN.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS public.reconciliation_window_governance_events" in source
    assert "DROP TABLE IF EXISTS public.reconciliation_windows" not in source
    assert "DROP TABLE IF EXISTS public.accounting_periods" not in source


def test_close_normalizes_and_fingerprints():
    command = close(close_disposition=" BALANCED ", accounting_period_code=" 2026-08 ")
    assert command.close_disposition == "balanced"
    assert command.accounting_period_code == "2026-08"
    assert len(command.request_fingerprint) == len(command.evidence_hash) == 64


@pytest.mark.parametrize("disposition", ["", "write_off", "closed"])
def test_unknown_close_disposition_fails(disposition):
    with pytest.raises(ReconciliationCloseValidationError) as raised:
        close(close_disposition=disposition)
    assert raised.value.code == "invalid_close_disposition"


def test_reopen_requires_positive_approver():
    with pytest.raises(ReconciliationCloseValidationError) as raised:
        reopen(approved_by_user_id=0)
    assert raised.value.code == "approval_required"


def test_reopen_approval_cannot_follow_transition():
    with pytest.raises(ReconciliationCloseValidationError) as raised:
        reopen(approved_at=BASE + timedelta(hours=2))
    assert raised.value.code == "approval_after_transition"


def test_reopen_payload_preserves_prior_close_approval_and_evidence():
    command = reopen()
    payload = command.canonical_payload()
    assert payload["prior_close_public_id"] == str(close().public_id)
    assert payload["approved_by_user_id"] == 7
    assert payload["evidence_payload"] == {"approval": "signed"}


def test_public_package_and_gate_artifacts_exist():
    assert (ROOT / "scripts/verify_m63_reconciliation_close_governance.py").is_file()
    assert (ROOT / "XBOS_M6_3_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "docs/track_b/M6_3_FORMAL_CLOSE_REOPEN_AND_CLOSED_PERIOD_GOVERNANCE.md").is_file()


def test_m64_authority_is_not_absorbed():
    source = "\n".join((UP.read_text(encoding="utf-8"), (ROOT / "core/domain/finance/reconciliation_close_engine.py").read_text(encoding="utf-8")))
    for forbidden in ("bank_reconciliation_report", "accounts_receivable_reconciliation", "accounts_payable_reconciliation"):
        assert forbidden not in source
