from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.domain.finance.legacy_authority_contract import AuthorityMode
from core.domain.finance.legacy_authority_inventory import load_inventory
from core.domain.finance.wnd_cutover_support_contract import (
    REQUIRED_READINESS_EVIDENCE, DualReadProjection, FinancialCutoverReadinessAssessment,
    LegacyWriterRetirementPlan, ReadinessEvidence, WndCutoverSupportError,
    WriterRetirementCandidate, assert_assessment_replay,
)
from core.domain.finance.wnd_cutover_support_service import WndCutoverSupportService
from core.domain.finance.wnd_shadow_rehearsal_contract import FinancialControlTotals

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc)


def projection(reader="legacy", values=None, **changes):
    data = dict(
        reader=reader, tenant_id=2, organization_unit_id=1,
        subject_type="commercial", subject_identity="sale:7301", as_of=BASE,
        totals=FinancialControlTotals("XAF", values or {"commercial_revenue": "100"}),
        provenance_hash=("a" if reader == "legacy" else "b") * 64,
    )
    data.update(changes)
    return DualReadProjection(**data)


def evidence(*, failed=None, observed_at=BASE):
    hash_chars = "abcdef012"
    return tuple(ReadinessEvidence(
        code=code, passed=code != failed, evidence_hash=hash_chars[index] * 64,
        observed_at=observed_at, detail=f"verified {code}",
    ) for index, code in enumerate(REQUIRED_READINESS_EVIDENCE))


def assessment(*, failed=None, assessment_id="m74-assessment"):
    return WndCutoverSupportService.assess(assessment_id, "f" * 64, evidence(failed=failed))


def rollback_map():
    inventory = load_inventory(ROOT)
    return {surface.code: f"runbook://rollback/{surface.code}" for surface in inventory.surfaces
            if surface.authority_mode in {AuthorityMode.WRITER, AuthorityMode.READER_WRITER}}


def test_contract_freezes_schema_neutral_r6_boundary():
    value = json.loads((ROOT / "contracts/finance/v1/m74_wnd_dual_read_cutover_readiness_and_writer_retirement_support.json").read_text())
    assert value["canonical_head"] == "m64_reconciliation_controls_020"
    assert value["migration"] is False
    assert value["dual_read_mode"] == "legacy_primary_canonical_shadow"
    assert value["writer_routing"] == "unchanged"
    assert value["cutover_authorized"] is False
    assert value["retirement_execution_allowed"] is False
    assert value["live_cutover_owner"] == "R6"


def test_matching_dual_read_is_deterministic():
    legacy = projection()
    canonical = projection("canonical")
    first = WndCutoverSupportService.compare(legacy, canonical)
    second = WndCutoverSupportService.compare(legacy, canonical)
    assert first.status == "matched"
    assert not any(first.deltas.values())
    assert first.comparison_fingerprint == second.comparison_fingerprint


def test_variance_remains_visible_without_forced_agreement():
    result = WndCutoverSupportService.compare(
        projection(), projection("canonical", {"commercial_revenue": "99"})
    )
    assert result.status == "variance"
    assert result.deltas["commercial_revenue"] == Decimal("-1")
    assert result.read_mode == "legacy_primary_canonical_shadow"
    assert result.fallback_authorized is False


@pytest.mark.parametrize("changes,code", [
    ({"tenant_id": 3}, "dual_read_scope_mismatch"),
    ({"organization_unit_id": 2}, "dual_read_scope_mismatch"),
    ({"subject_identity": "sale:other"}, "dual_read_scope_mismatch"),
    ({"subject_type": "payment"}, "dual_read_scope_mismatch"),
    ({"as_of": datetime(2026, 8, 11, 19, 1, tzinfo=timezone.utc)}, "dual_read_scope_mismatch"),
])
def test_cross_scope_dual_read_fails_closed(changes, code):
    with pytest.raises(WndCutoverSupportError) as raised:
        WndCutoverSupportService.compare(projection(), projection("canonical", **changes))
    assert raised.value.code == code


def test_cross_currency_dual_read_fails_closed():
    with pytest.raises(WndCutoverSupportError) as raised:
        WndCutoverSupportService.compare(
            projection(), projection("canonical", totals=FinancialControlTotals("USD", {}))
        )
    assert raised.value.code == "dual_read_currency_mismatch"


@pytest.mark.parametrize("reader", ["", "primary", "fallback"])
def test_unknown_reader_fails_closed(reader):
    with pytest.raises(WndCutoverSupportError):
        projection(reader)


def test_projection_requires_timezone_and_sha256_provenance():
    with pytest.raises(WndCutoverSupportError):
        projection(as_of=datetime(2026, 8, 11, 19, 0))
    with pytest.raises(WndCutoverSupportError) as raised:
        projection(provenance_hash="invalid")
    assert raised.value.code == "invalid_evidence_hash"


def test_authority_switch_and_fallback_are_forbidden():
    with pytest.raises(WndCutoverSupportError) as raised:
        projection(authority_switch_executed=True)
    assert raised.value.code == "authority_switch_forbidden"
    with pytest.raises(WndCutoverSupportError) as raised:
        WndCutoverSupportService.compare(
            projection(), projection("canonical"),
        ).__class__(projection(), projection("canonical"), fallback_authorized=True)
    assert raised.value.code == "unsafe_read_routing"


def test_complete_passing_evidence_is_only_ready_for_r6_review():
    selected = assessment()
    assert selected.status == "ready_for_r6_review"
    assert selected.blockers == ()
    assert selected.advisory_only is True
    assert selected.cutover_authorized is False
    assert selected.decision_authority == "R6"


def test_failed_evidence_blocks_readiness():
    selected = assessment(failed="control_total_parity")
    assert selected.status == "not_ready"
    assert selected.blockers == ("control_total_parity",)


def test_incomplete_or_duplicate_evidence_fails_closed():
    items = evidence()
    with pytest.raises(WndCutoverSupportError) as raised:
        FinancialCutoverReadinessAssessment("a", "f" * 64, items[:-1])
    assert raised.value.code == "readiness_evidence_incomplete"
    with pytest.raises(WndCutoverSupportError):
        FinancialCutoverReadinessAssessment("a", "f" * 64, items + (items[0],))


def test_unknown_evidence_and_naive_time_fail_closed():
    with pytest.raises(WndCutoverSupportError) as raised:
        ReadinessEvidence("operator_guess", True, "a" * 64, BASE, "guess")
    assert raised.value.code == "unsupported_readiness_evidence"
    with pytest.raises(WndCutoverSupportError):
        ReadinessEvidence(REQUIRED_READINESS_EVIDENCE[0], True, "a" * 64,
                          datetime(2026, 8, 11, 19, 0), "verified")


def test_readiness_cannot_self_authorize_cutover():
    with pytest.raises(WndCutoverSupportError) as raised:
        FinancialCutoverReadinessAssessment("a", "f" * 64, evidence(), cutover_authorized=True)
    assert raised.value.code == "unsafe_readiness_authority"
    with pytest.raises(WndCutoverSupportError):
        FinancialCutoverReadinessAssessment("a", "f" * 64, evidence(), decision_authority="M7")


def test_assessment_replay_returns_existing_and_conflict_fails():
    first = assessment()
    same = assessment()
    assert assert_assessment_replay(first, same) is first
    changed = assessment(failed="control_total_parity")
    with pytest.raises(WndCutoverSupportError) as raised:
        assert_assessment_replay(first, changed)
    assert raised.value.code == "readiness_idempotency_conflict"


def test_retirement_plan_is_inventory_derived_reversible_and_disabled():
    inventory = load_inventory(ROOT)
    plan = WndCutoverSupportService.retirement_plan("m74-retirement", assessment(), inventory, rollback_map())
    writer_codes = {surface.code for surface in inventory.surfaces
                    if surface.authority_mode in {AuthorityMode.WRITER, AuthorityMode.READER_WRITER}}
    assert {item.surface_code for item in plan.candidates} == writer_codes
    assert plan.status == "prepared_for_r6_review"
    assert all(item.eligible_for_r6_review for item in plan.candidates)
    assert all(not item.retirement_executed for item in plan.candidates)
    assert plan.execution_allowed is False and plan.reversible is True
    assert plan.decision_authority == "R6"


def test_failed_readiness_blocks_every_retirement_candidate():
    plan = WndCutoverSupportService.retirement_plan(
        "blocked", assessment(failed="rollback_runbook"), load_inventory(ROOT), rollback_map()
    )
    assert plan.status == "blocked"
    assert not any(item.eligible_for_r6_review for item in plan.candidates)


def test_missing_rollback_reference_fails_closed():
    with pytest.raises(WndCutoverSupportError) as raised:
        WndCutoverSupportService.retirement_plan("missing", assessment(), load_inventory(ROOT), {})
    assert raised.value.code == "incomplete_retirement_candidate"


def test_retirement_candidate_cannot_claim_execution():
    with pytest.raises(WndCutoverSupportError) as raised:
        WriterRetirementCandidate("writer", "core/writer.py", ("financial_events",),
                                  "runbook://writer", True, retirement_executed=True)
    assert raised.value.code == "writer_retirement_forbidden"
    candidate = WriterRetirementCandidate("writer", "core/writer.py", ("financial_events",),
                                          "runbook://writer", True)
    with pytest.raises(WndCutoverSupportError):
        LegacyWriterRetirementPlan("plan", "a" * 64, (candidate,),
                                   "prepared_for_r6_review", execution_allowed=True)


def test_no_schema_rerouting_disablement_or_cutover_authority_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m74_*.py"))
    marker = (ROOT / "core/persistence/m74_wnd_cutover_support.py").read_text()
    assert "SCHEMA_NEUTRAL = True" in marker
    assert "CUTOVER_AUTHORIZED = False" in marker
    assert "RETIREMENT_EXECUTION_ALLOWED = False" in marker
    assert "REROUTES_LEGACY_WRITERS = False" in marker
    assert "DISABLES_LEGACY_WRITERS = False" in marker
    assert "LIVE_CUTOVER_OWNER = \"R6\"" in marker


def test_package_and_gate_artifacts_exist():
    assert (ROOT / "XBOS_M7_4_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M7_4_INSTALL_AND_VERIFY.txt").is_file()
