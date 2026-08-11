from __future__ import annotations

import json
from pathlib import Path

from core.domain.finance.m6_acceptance import EXPECTED_HEAD, EXPECTED_LINEAGE
from core.domain.finance.m7_acceptance import (
    EXPECTED_TAG,
    validate_authority_boundaries,
    validate_public_artifacts,
    validate_release_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def test_contract_freezes_schema_neutral_m7_boundary():
    contract = json.loads(
        (ROOT / "contracts/finance/v1/m75_finance_migration_support_acceptance_and_freeze.json")
        .read_text(encoding="utf-8")
    )
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["writer_routing"] == "unchanged"
    assert contract["cutover_authorized"] is False
    assert contract["retirement_execution_allowed"] is False
    assert contract["live_cutover_owner"] == "R6"
    assert contract["release_tag"] == EXPECTED_TAG


def test_release_manifest_freezes_all_five_m7_components():
    checked = validate_release_manifest(ROOT)
    assert checked.checked_components == 5
    assert checked.canonical_head == EXPECTED_HEAD
    assert checked.lineage == EXPECTED_LINEAGE


def test_release_manifest_uses_accepted_m74_parent():
    manifest = json.loads(
        (ROOT / "contracts/finance/v1/m7_release_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["approved_commit_parent"] == "5eea325"
    assert [item["milestone"] for item in manifest["components"]] == [
        "M7.0", "M7.1", "M7.2", "M7.3", "M7.4",
    ]


def test_no_m7_migration_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m7*.py"))


def test_authority_boundaries_remain_fail_closed():
    validate_authority_boundaries(ROOT)


def test_all_accepted_m7_public_artifacts_exist():
    validate_public_artifacts(ROOT)


def test_exit_marker_cannot_route_or_cut_over():
    source = (ROOT / "core/persistence/m75_finance_migration_support_exit.py").read_text(encoding="utf-8")
    for marker in (
        "SCHEMA_NEUTRAL = True",
        "WRITES_NEW_TABLES = False",
        "REROUTES_LEGACY_WRITERS = False",
        "CUTOVER_AUTHORIZED = False",
        "RETIREMENT_EXECUTION_ALLOWED = False",
        'LIVE_CUTOVER_OWNER = "R6"',
    ):
        assert marker in source


def test_aggregate_verifier_replays_every_m7_capability():
    source = (ROOT / "scripts/verify_m75_m7_acceptance.py").read_text(encoding="utf-8")
    for marker in (
        "verify_m70_legacy_financial_authority.py",
        "verify_m71_wnd_financial_mapping.py",
        "verify_m72_wnd_inventory_document_mapping.py",
        "verify_m73_wnd_shadow_rehearsal.py",
        "verify_m74_wnd_cutover_support.py",
    ):
        assert marker in source
    for marker in (
        "manifest=PASS",
        "m70_m74=PASS",
        "writer_routing=UNCHANGED",
        "cutover=NOT_AUTHORIZED",
        "retirement=NOT_EXECUTED",
        "migration=NONE",
    ):
        assert marker in source


def test_m75_public_package_and_gate_artifacts_exist():
    assert (ROOT / "XBOS_M7_5_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M7_5_INSTALL_AND_VERIFY.txt").is_file()
