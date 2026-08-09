import hashlib
import json
from pathlib import Path

import pytest

from core.domain.finance.m3_acceptance import (
    EXPECTED_HEAD,
    EXPECTED_LINEAGE,
    M3AcceptanceError,
    canonical_json_bytes,
    repository_migration_lineage,
    semantic_sha256,
    validate_release_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/finance/v1/m36_m3_acceptance_and_freeze.json"
MANIFEST_PATH = ROOT / "contracts/finance/v1/m3_release_manifest.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_acceptance_contract_identity():
    assert CONTRACT["contract_code"] == "XBOS_M36_M3_ACCEPTANCE_AND_FREEZE"
    assert CONTRACT["milestone"] == "M3.6"
    assert CONTRACT["starting_commit"] == "443b897"


def test_closure_is_schema_neutral():
    assert CONTRACT["schema_change"] is False
    assert EXPECTED_HEAD == CONTRACT["canonical_head"] == "m34_obligation_aging_010"
    assert not list((ROOT / "alembic_neutral/versions").glob("m36_*.py"))


def test_acceptance_mode_is_fail_fast():
    acceptance = CONTRACT["acceptance"]
    assert acceptance["mode"] == "single_fail_fast_gate"
    assert acceptance["segmented_diagnostics_only_after_failure"] is True


def test_release_tag_is_frozen():
    assert CONTRACT["release_tag"] == "track-b-m3-obligations-balances-allocations-20260809"


def test_manifest_identity():
    assert MANIFEST["baseline_code"] == "XBOS_M3_OBLIGATIONS_BALANCES_ALLOCATIONS_RELEASE"
    assert MANIFEST["approved_commit_parent"] == "443b897"
    assert MANIFEST["canonical_head"] == EXPECTED_HEAD


def test_manifest_has_six_ordered_components():
    components = MANIFEST["components"]
    assert len(components) == 6
    assert [item["sequence"] for item in components] == list(range(1, 7))
    assert [item["milestone"] for item in components] == [f"M3.{number}" for number in range(6)]


@pytest.mark.parametrize("component", MANIFEST["components"])
def test_component_semantic_digest(component):
    assert semantic_sha256(ROOT / component["path"]) == component["semantic_sha256"]


def test_canonical_json_ignores_formatting():
    left = {"b": [2, 1], "a": True}
    right = json.loads('{\n  "a": true,\n  "b": [2, 1]\n}')
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert hashlib.sha256(canonical_json_bytes(left)).hexdigest() == hashlib.sha256(canonical_json_bytes(right)).hexdigest()


def test_repository_lineage_is_single_and_exact():
    assert repository_migration_lineage(ROOT) == EXPECTED_LINEAGE
    assert tuple(MANIFEST["canonical_migration_lineage"]) == EXPECTED_LINEAGE


def test_manifest_full_validation():
    result = validate_release_manifest(ROOT)
    assert result.checked_components == 6
    assert result.canonical_head == EXPECTED_HEAD
    assert result.lineage == EXPECTED_LINEAGE


def test_manifest_detects_semantic_drift(tmp_path):
    changed = {"meaning": "different"}
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert semantic_sha256(path) != MANIFEST["components"][0]["semantic_sha256"]


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(M3AcceptanceError) as error:
        semantic_sha256(path)
    assert error.value.code == "invalid_contract_json"


@pytest.mark.parametrize("number,name", [
    (30, "obligation_foundation"),
    (31, "typed_obligation_lifecycle_balances"),
    (32, "allocation_engine"),
    (33, "value_application_workflows"),
    (34, "obligation_aging"),
    (35, "obligation_settlement_trace"),
])
def test_each_capability_verifier_exists(number, name):
    assert (ROOT / f"scripts/verify_m{number}_{name}.py").is_file()


@pytest.mark.parametrize("number", [30, 31, 32, 33])
def test_earlier_verifiers_accept_approved_descendant_head(number):
    path = next((ROOT / "scripts").glob(f"verify_m{number}_*.py"))
    source = path.read_text(encoding="utf-8")
    assert "m34_obligation_aging_010" in source
    assert "DEVELOPMENT_REVISIONS" in source


def test_consolidated_verifier_runs_capabilities_in_order():
    source = (ROOT / "scripts/verify_m36_m3_acceptance.py").read_text(encoding="utf-8")
    positions = [source.index(f'(\"m3{number}\",') for number in range(6)]
    assert positions == sorted(positions)
    assert "subprocess.run" in source and "check=True" in source


def test_consolidated_verifier_checks_before_and_after():
    source = (ROOT / "scripts/verify_m36_m3_acceptance.py").read_text(encoding="utf-8")
    body = source[source.index("def _create_and_verify") :]
    assert body.count("_development_acceptance()") >= 2
    assert body.count("_status()") >= 2


def test_development_acceptance_is_read_only():
    source = (ROOT / "scripts/verify_m36_m3_acceptance.py").read_text(encoding="utf-8").upper()
    section = source[source.index("DEF _DEVELOPMENT_ACCEPTANCE") : source.index("DEF _RUN_CAPABILITY")]
    assert "SELECT " in section
    assert not any(token in section for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "CREATE DATABASE", "DROP DATABASE"))


def test_all_disposable_database_names_are_frozen():
    source = (ROOT / "scripts/verify_m36_m3_acceptance.py").read_text(encoding="utf-8")
    expected = {
        "xbos_track_b_m30_foundation_test",
        "xbos_track_b_m31_obligation_test",
        "xbos_track_b_m32_allocation_test",
        "xbos_track_b_m33_value_application_test",
        "xbos_track_b_m34_aging_test",
        "xbos_track_b_m35_obligation_trace_test",
    }
    assert all(name in source for name in expected)


def test_forbidden_release_surface_is_explicit():
    forbidden = set(CONTRACT["forbidden"])
    assert {"migration", "development_financial_fact_creation", "public_route", "wnd_writer_switch"} <= forbidden
