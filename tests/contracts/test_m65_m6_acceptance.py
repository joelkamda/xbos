from __future__ import annotations

import json
from pathlib import Path

from core.domain.finance.m6_acceptance import EXPECTED_HEAD, EXPECTED_LINEAGE, EXPECTED_TAG, validate_concurrency_guards, validate_frozen_m4_manifest, validate_release_manifest

ROOT = Path(__file__).resolve().parents[2]


def test_contract_is_schema_neutral_and_freezes_head():
    contract = json.loads((ROOT / "contracts/finance/v1/m65_m6_acceptance_and_freeze.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["release_tag"] == EXPECTED_TAG


def test_release_manifest_freezes_all_five_m6_components():
    checked = validate_release_manifest(ROOT)
    assert checked.checked_components == 5
    assert checked.canonical_head == EXPECTED_HEAD
    assert checked.lineage == EXPECTED_LINEAGE


def test_release_manifest_uses_accepted_m64_parent():
    manifest = json.loads((ROOT / "contracts/finance/v1/m6_release_manifest.json").read_text(encoding="utf-8"))
    assert manifest["approved_commit_parent"] == "521dab7"
    assert [item["milestone"] for item in manifest["components"]] == ["M6.0", "M6.1", "M6.2", "M6.3", "M6.4"]


def test_frozen_m4_manifest_is_validated_without_requiring_m4_to_remain_repository_head():
    assert validate_frozen_m4_manifest(ROOT) == 7


def test_no_m65_migration_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m65_*.py"))


def test_concurrency_guards_are_frozen():
    validate_concurrency_guards(ROOT)


def test_exit_marker_is_schema_neutral():
    source = (ROOT / "core/persistence/m65_m6_exit.py").read_text(encoding="utf-8")
    assert "SCHEMA_NEUTRAL = True" in source
    assert "WRITES_NEW_TABLES = False" in source


def test_aggregate_verifier_rehearses_every_m6_capability():
    source = (ROOT / "scripts/verify_m65_m6_acceptance.py").read_text(encoding="utf-8")
    for marker in ("m60._exercise", "m61._exercise", "m62._exercise", "m63._exercise", "m64._exercise"):
        assert marker in source
    for marker in ("manifest=PASS", "development=PASS", "recovery=PASS", "concurrency=PASS", "dropped=true"):
        assert marker in source


def test_acceptance_gate_and_install_instructions_exist():
    assert (ROOT / "XBOS_M6_5_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M6_5_INSTALL_AND_VERIFY.txt").is_file()
