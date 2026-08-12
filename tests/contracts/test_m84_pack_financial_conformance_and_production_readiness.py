from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from core.domain.finance.m6_acceptance import EXPECTED_HEAD
from core.domain.finance.pack_conformance_contract import (
    ControlTotalSet, PackConformanceError, PackConformanceProfile, PackFlowEvidence,
    assert_profile_replay,
)
from core.domain.finance.pack_conformance_service import (
    evaluate_pack, find_hidden_financial_writers, validate_generic_harness_neutrality,
)
from core.domain.finance.wnd_pack_conformance_profile import build_wnd_conformance_profile

ROOT = Path(__file__).resolve().parents[2]


def _flow(**changes):
    selected = PackFlowEvidence(
        flow_code="example_flow", source_identity="source:1", tenant_id=2, organization_unit_id=1,
        mapping_fingerprint="a" * 64, effect_bundle_fingerprint="b" * 64,
        canonical_effect_ids=("effect-1",),
        expected=ControlTotalSet("XAF", {"gross": Decimal("10")}),
        observed=ControlTotalSet("XAF", {"gross": Decimal("10")}),
    )
    return replace(selected, **changes)


def test_contract_freezes_schema_neutral_readiness_boundary():
    contract = json.loads((ROOT / "contracts/finance/v1/m84_pack_financial_conformance_and_production_readiness.json").read_text(encoding="utf-8"))
    assert contract["source_checkpoint"]["commit"] == "f049a26"
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["first_specimen"]["cutover"] == "NOT_AUTHORIZED"
    assert contract["first_specimen"]["writer_retirement"] == "NOT_EXECUTED"


def test_generic_contract_requires_exact_once_and_matching_economic_totals():
    with pytest.raises(PackConformanceError) as raised:
        _flow(accepted_deliveries=2)
    assert raised.value.code == "exact_once_violation"
    with pytest.raises(PackConformanceError) as raised:
        _flow(observed=ControlTotalSet("XAF", {"gross": Decimal("9")}))
    assert raised.value.code == "control_total_mismatch"


def test_duplicate_effect_identity_and_scope_leaks_fail_closed():
    with pytest.raises(PackConformanceError):
        _flow(canonical_effect_ids=("effect-1", "effect-1"))
    with pytest.raises(PackConformanceError):
        _flow(organization_unit_id=0)


def test_hidden_writer_profile_cannot_pass():
    with pytest.raises(PackConformanceError) as raised:
        PackConformanceProfile("example.pack", "1", ("source",), (_flow(),), hidden_writers=("direct_journal_writer",))
    assert raised.value.code == "hidden_financial_writer"


def test_wnd_is_a_specimen_of_generic_harness_without_cutover_authority():
    profile = build_wnd_conformance_profile()
    report = evaluate_pack(profile)
    assert profile.pack_code == "wnd.restaurant"
    assert len(profile.flows) == 6
    assert {item.flow_code for item in profile.flows} == {
        "commercial_sale", "payment_collection", "receivable_repayment", "refund_reversal",
        "inventory_cogs", "document_receipt_handoff",
    }
    assert report.readiness_verdict == "PASS"
    assert report.cutover == "NOT_AUTHORIZED"
    assert report.writer_retirement == "NOT_EXECUTED"
    assert report.migration == "NONE"


def test_specimen_replay_is_stable_and_conflict_fails_closed():
    first = build_wnd_conformance_profile()
    same = build_wnd_conformance_profile()
    assert assert_profile_replay(first, same) is first
    changed = replace(first, known_exclusions=first.known_exclusions + ("new_exclusion",))
    with pytest.raises(PackConformanceError) as raised:
        assert_profile_replay(first, changed)
    assert raised.value.code == "pack_conformance_conflict"


def test_generic_harness_has_no_industry_semantic_leakage():
    validate_generic_harness_neutrality(ROOT)


def test_frozen_m7_and_specimen_sources_contain_no_direct_financial_table_writer():
    paths = (
        "core/domain/finance/wnd_financial_mapping_service.py",
        "core/domain/finance/wnd_inventory_document_service.py",
        "core/domain/finance/wnd_shadow_rehearsal_service.py",
        "core/domain/finance/wnd_cutover_support_service.py",
        "core/domain/finance/wnd_pack_conformance_profile.py",
    )
    assert find_hidden_financial_writers(ROOT, paths) == ()


def test_persistence_marker_and_schema_remain_neutral():
    source = (ROOT / "core/persistence/m84_pack_financial_conformance.py").read_text(encoding="utf-8")
    for marker in (
        "SCHEMA_NEUTRAL = True", "MIGRATION = None", "CREATES_PACK_FINANCIAL_AUTHORITY = False",
        "DIRECT_FINANCIAL_MUTATION_ALLOWED = False", "REROUTES_LEGACY_WRITERS = False",
        "CUTOVER_AUTHORIZED = False", "WRITER_RETIREMENT_EXECUTED = False", 'LIVE_CUTOVER_OWNER = "R6"',
    ):
        assert marker in source
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m84_*.py"))


def test_verifier_proves_runtime_authority_replay_scope_recovery_and_control_totals():
    source = (ROOT / "scripts/verify_m84_pack_financial_conformance.py").read_text(encoding="utf-8")
    for marker in (
        "TransactionalCanonicalFinancialEventEngine.emit", "FinancialEventIdempotencyConflict",
        "organization_unit_not_active", "find_hidden_financial_writers", "control_totals=PASS",
        "cutover=NOT_AUTHORIZED", "writer_retirement=NOT_EXECUTED", "dropped=true",
    ):
        assert marker in source


def test_public_package_and_gate_artifacts_exist():
    assert (ROOT / "XBOS_M8_4_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M8_4_INSTALL_AND_VERIFY.txt").is_file()
