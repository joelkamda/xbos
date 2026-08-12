from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.domain.finance.m6_acceptance import EXPECTED_HEAD, EXPECTED_LINEAGE
from core.domain.finance.track_b_acceptance import validate_authority_exit, validate_release_manifest
from core.domain.finance.track_b_exit_contract import TrackBExitError, TrackBExitEvidence

ROOT = Path(__file__).resolve().parents[2]


def _evidence(**changes):
    values = {
        "canonical_head": EXPECTED_HEAD,
        "release_components": 12,
        "clean_replay": True,
        "cross_milestone": True,
        "financial_invariants": True,
        "adversarial_suites": ("M8.0", "M8.1", "M8.2", "M8.3", "M8.4"),
        "development_empty": True,
        "hidden_writers": (),
        "cutover": "NOT_AUTHORIZED",
        "writer_retirement": "NOT_EXECUTED",
    }
    values.update(changes)
    return TrackBExitEvidence(**values)


def test_exit_contract_freezes_checkpoint_head_and_R6_boundary():
    contract = json.loads((ROOT / "contracts/finance/v1/m85_track_b_aggregate_conformance_freeze_and_approved_exit.json").read_text(encoding="utf-8"))
    assert contract["source_checkpoint"] == {"branch": "track-b/m8-financial-hardening-and-exit", "commit": "ab43fbd"}
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["boundaries"]["cutover"] == "NOT_AUTHORIZED"
    assert contract["boundaries"]["writer_retirement"] == "NOT_EXECUTED"
    assert contract["boundaries"]["live_cutover_owner"] == "R6"


def test_final_manifest_covers_every_release_and_hardening_package():
    manifest = json.loads((ROOT / "contracts/finance/v1/track_b_financial_approved_exit_manifest.json").read_text(encoding="utf-8"))
    assert [item["milestone"] for item in manifest["components"]] == [
        "M2", "M3", "M4", "M5", "M6", "M7", "M8.0", "M8.1", "M8.2", "M8.3", "M8.4", "M8.5",
    ]
    assert tuple(manifest["canonical_migration_lineage"]) == EXPECTED_LINEAGE
    assert manifest["cutover"] == "NOT_AUTHORIZED"
    assert manifest["writer_retirement"] == "NOT_EXECUTED"


def test_manifest_semantics_and_historical_release_validators_converge():
    result = validate_release_manifest(ROOT)
    assert result.checked_components == 12
    assert result.canonical_head == EXPECTED_HEAD
    assert result.lineage == EXPECTED_LINEAGE
    assert result.historical_release_counts == (20, 6, 7, 6, 5, 5)


def test_schema_neutral_exit_guards_and_hidden_writer_proof_hold():
    validate_authority_exit(ROOT)
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m8*.py"))


def test_exit_evidence_requires_all_selected_adversarial_suites():
    assert _evidence().canonical_head == EXPECTED_HEAD
    with pytest.raises(TrackBExitError) as raised:
        _evidence(adversarial_suites=("M8.0", "M8.1", "M8.2", "M8.4"))
    assert raised.value.code == "incomplete_adversarial_evidence"


def test_exit_evidence_rejects_hidden_writers_or_cutover_authority():
    with pytest.raises(TrackBExitError) as raised:
        _evidence(hidden_writers=("direct_journal_writer",))
    assert raised.value.code == "hidden_financial_writers"
    with pytest.raises(TrackBExitError) as raised:
        _evidence(cutover="AUTHORIZED")
    assert raised.value.code == "R6_boundary_exceeded"


def test_verifier_uses_template0_real_lineage_composition_and_selected_suites():
    source = (ROOT / "scripts/verify_m85_track_b_approved_exit.py").read_text(encoding="utf-8")
    for marker in (
        "TEMPLATE template0", "alembic_command.upgrade", "alembic_command.downgrade",
        "AtomicPostedFinancialEventEngine.emit_and_post", "TransactionalObligationEngine.create",
        "first.obligation.public_id", "replay.obligation.public_id",
        "_install_governed_actor_fixture", "m85-approval-actor",
        "TransactionalPaymentSettlementEngine.transition", "journal_entry_event_links",
        "accounting_period_not_open", "verify_m80_global_financial_invariants.py",
        "verify_m83_performance_recovery.py", "verify_m84_pack_financial_conformance.py",
        "cutover=NOT_AUTHORIZED", "writer_retirement=NOT_EXECUTED", "dropped=true",
    ):
        assert marker in source


def test_public_M85_package_and_gate_artifacts_exist():
    assert (ROOT / "XBOS_M8_5_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M8_5_INSTALL_AND_VERIFY.txt").is_file()
