import json
import shutil
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m27_m2_acceptance_and_freeze.json"
MANIFEST_PATH = ROOT / "contracts" / "finance" / "v1" / "m2_release_manifest.json"
ACCEPTANCE_PATH = ROOT / "core" / "domain" / "finance" / "m2_acceptance.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m27_m2_acceptance.py"
DOC_PATH = ROOT / "docs" / "track_b" / "M2_7_HARDENING_ACCEPTANCE_BASELINE_AND_M2_FREEZE.md"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M27_M2_ACCEPTANCE_AND_FREEZE"
    assert contract["contract_version"] == 1
    assert contract["package_revision"] == 3
    assert contract["status"] == "approved_release_candidate"


def test_contract_is_anchored_to_committed_m26(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "1038db5",
        "migration_revision": "m25_financial_dimensions_007",
    }


def test_m27_is_schema_neutral(contract):
    assert contract["schema_change"] is False
    assert contract["target_revision"] == "m25_financial_dimensions_007"
    versions = ROOT / "alembic_neutral" / "versions"
    assert not list(versions.glob("m26_*.py"))
    assert not list(versions.glob("m27_*.py"))


def test_release_scope_is_complete_and_ordered(contract):
    assert [item.split("_", 1)[0] for item in contract["release_scope"]] == [
        "M2.0",
        "M2.1",
        "M2.2",
        "M2.3",
        "M2.4",
        "M2.5",
        "M2.6",
    ]


def test_acceptance_gates_cover_every_release_boundary(contract):
    assert set(contract["acceptance_gates"]) == {
        "contract_authority",
        "migration_authority",
        "static_hardening",
        "development_target",
        "disposable_rehearsals",
        "regression",
        "source_control",
    }


def test_frozen_invariants_cover_the_event_to_explanation_chain(contract):
    joined = " ".join(contract["frozen_invariants"])
    for concept in (
        "tenant",
        "immutable",
        "idempotency",
        "correction",
        "balanced",
        "dimension",
        "trace",
        "industry",
        "development",
    ):
        assert concept in joined


def test_no_integration_boundary_is_accidentally_activated(contract):
    assert all(value is False for value in contract["hardening_boundaries"].values())


def test_freeze_policy_names_the_annotated_release_tag(contract):
    assert contract["freeze_policy"]["tag"] == "track-b-m2-canonical-event-engine-20260808"


def test_next_phase_does_not_start_before_the_pushed_tag(contract):
    assert contract["next_phase"]["code"] == "M3"
    assert "pushed_M2_tag" in contract["next_phase"]["entry_rule"]


def test_deferred_scope_retains_writer_dispatch_and_reporting_boundaries(contract):
    assert {
        "wnd_writer_cutover",
        "outbox_dispatch_worker",
        "public_financial_trace_route_and_rbac",
        "formal_period_close_workflow",
        "external_reporting_and_ai_consumers",
    }.issubset(contract["deferred"])


def test_release_manifest_identity(manifest):
    assert manifest["baseline_code"] == "XBOS_M2_CANONICAL_EVENT_ENGINE_RELEASE"
    assert manifest["baseline_version"] == 1
    assert manifest["status"] == "approved_release_candidate"


def test_manifest_is_anchored_to_the_m26_commit(manifest):
    assert manifest["source_checkpoint"]["branch"] == "track-b/m2-canonical-event-engine"
    assert manifest["source_checkpoint"]["parent_commit"] == "1038db5"


def test_manifest_canonicalization_is_semantic_and_cross_platform(manifest):
    policy = manifest["semantic_fingerprint"]
    assert policy["algorithm"] == "sha256"
    assert policy["line_ending_independent"] is True
    assert "json_sorted_keys" in policy["canonicalization"]


def test_manifest_has_twenty_ordered_unique_components(manifest):
    components = manifest["components"]
    assert len(components) == 20
    assert [item["sequence"] for item in components] == list(range(1, 21))
    assert len({item["path"] for item in components}) == 20


def test_manifest_covers_m0_m1_and_every_m2_slice(manifest):
    phases = {item["phase"] for item in manifest["components"]}
    assert {"M0", "M1.0", "M1.1", "M1.2", "M1.3", "M1.4"}.issubset(phases)
    assert {f"M2.{number}" for number in range(7)}.issubset(phases)


def test_every_manifest_fingerprint_is_sha256(manifest):
    for component in manifest["components"]:
        fingerprint = component["semantic_sha256"]
        assert len(fingerprint) == 64
        int(fingerprint, 16)


def test_every_manifest_component_exists_and_matches(manifest):
    from core.domain.finance.m2_acceptance import semantic_sha256

    for component in manifest["components"]:
        path = ROOT / component["path"]
        assert path.is_file()
        assert semantic_sha256(path) == component["semantic_sha256"]


def test_m0_component_hashes_still_match_the_original_baseline(manifest):
    m0 = json.loads(
        (ROOT / "contracts" / "finance" / "v1" / "contract_baseline_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frozen = {item["path"]: item["semantic_sha256"] for item in manifest["components"]}
    for component in m0["components"]:
        assert frozen[component["path"]] == component["semantic_sha256"]


def test_canonical_migration_lineage_is_exact(manifest):
    assert manifest["canonical_migration_lineage"] == [
        "m13_source_state_001",
        "m13_financial_foundation_002",
        "m20_event_catalog_003",
        "m22_transactional_delivery_004",
        "m23_reversal_capacity_005",
        "m24_balanced_posting_006",
        "m25_financial_dimensions_007",
    ]


def test_manifest_has_one_expected_head(manifest):
    assert manifest["canonical_head"] == "m25_financial_dimensions_007"


def test_development_acceptance_counts_preserve_empty_financial_truth(manifest):
    counts = manifest["development_acceptance_counts"]
    assert counts["financial_event_type_versions"] == 20
    assert all(value == 0 for name, value in counts.items() if name != "financial_event_type_versions")


def test_manifest_has_one_verifier_for_every_m2_slice(manifest):
    verifiers = manifest["capability_verifiers"]
    assert [item["phase"] for item in verifiers] == [f"M2.{number}" for number in range(7)]


def test_historical_verifiers_declare_fixed_milestone_revisions(manifest):
    assert [item["target_revision"] for item in manifest["capability_verifiers"]] == [
        "m20_event_catalog_003",
        "m20_event_catalog_003",
        "m22_transactional_delivery_004",
        "m23_reversal_capacity_005",
        "m24_balanced_posting_006",
        "m25_financial_dimensions_007",
        "m25_financial_dimensions_007",
    ]
    assert "immutable_git_checkpoint" in manifest["capability_revision_policy"]


def test_historical_verifiers_are_bound_to_their_approved_commits(manifest):
    assert [item["checkpoint_commit"] for item in manifest["capability_verifiers"]] == [
        "49315ae",
        "6acd76c",
        "8056fbb",
        "59f3747",
        "c6e3b6d",
        "d57bd05",
        "1038db5",
    ]


def test_disposable_database_names_are_unique_and_explicit(manifest):
    names = [item["database"] for item in manifest["capability_verifiers"]]
    assert len(names) == len(set(names)) == 7
    assert all(name.startswith("xbos_track_b_m2") and name.endswith("_test") for name in names)


def test_every_capability_verifier_exists_and_has_a_pass_token(manifest):
    for verifier in manifest["capability_verifiers"]:
        assert (ROOT / verifier["script"]).is_file()
        assert verifier["pass_token"].endswith("=PASS")


def test_aggregate_runner_materializes_immutable_git_snapshots():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert '"git",' in source
    assert '"archive",' in source
    assert 'checkpoint = capability["checkpoint_commit"]' in source
    assert "zipfile.ZipFile(archive)" in source
    assert "cwd=snapshot" in source
    assert 'child_environment["DATABASE_URL"]' in source


def test_release_tag_matches_the_freeze_contract(contract, manifest):
    assert manifest["release_tag"] == contract["freeze_policy"]["tag"]


def test_acceptance_helper_validates_the_current_tree():
    from core.domain.finance.m2_acceptance import EXPECTED_LINEAGE, validate_release_manifest

    result = validate_release_manifest(ROOT)
    assert result.checked_components == 20
    assert result.canonical_head == "m25_financial_dimensions_007"
    assert result.lineage == EXPECTED_LINEAGE


def test_canonical_json_hash_ignores_key_order_and_formatting(tmp_path):
    from core.domain.finance.m2_acceptance import semantic_sha256

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"a":1,"b":{"x":2}}\n', encoding="utf-8")
    second.write_text('{\r\n  "b": {"x": 2},\r\n  "a": 1\r\n}', encoding="utf-8")
    assert semantic_sha256(first) == semantic_sha256(second)


def _copy_acceptance_tree(destination: Path) -> Path:
    for relative in (
        Path("contracts"),
        Path("alembic_neutral"),
        Path("core/domain/finance"),
    ):
        shutil.copytree(ROOT / relative, destination / relative)
    return destination


def test_acceptance_fails_closed_on_semantic_contract_drift(tmp_path):
    from core.domain.finance.m2_acceptance import M2AcceptanceError, validate_release_manifest

    root = _copy_acceptance_tree(tmp_path / "tree")
    path = root / "contracts" / "finance" / "v1" / "m26_financial_trace_and_explanation.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["purpose"] = "silently changed"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(M2AcceptanceError) as exc:
        validate_release_manifest(root)
    assert exc.value.code == "semantic_fingerprint_mismatch"


def test_acceptance_fails_closed_when_a_component_is_missing(tmp_path):
    from core.domain.finance.m2_acceptance import M2AcceptanceError, validate_release_manifest

    root = _copy_acceptance_tree(tmp_path / "tree")
    (root / "contracts" / "finance" / "v1" / "workflow_contracts.json").unlink()
    with pytest.raises(M2AcceptanceError) as exc:
        validate_release_manifest(root)
    assert exc.value.code == "missing_contract_component"


def test_acceptance_fails_closed_on_a_second_migration_head(tmp_path):
    from core.domain.finance.m2_acceptance import M2AcceptanceError, validate_release_manifest

    root = _copy_acceptance_tree(tmp_path / "tree")
    path = root / "alembic_neutral" / "versions" / "rogue.py"
    path.write_text('revision = "rogue"\ndown_revision = None\n', encoding="utf-8")
    with pytest.raises(M2AcceptanceError) as exc:
        validate_release_manifest(root)
    assert exc.value.code == "unexpected_migration_heads"


def test_acceptance_fails_closed_on_framework_coupling(tmp_path):
    from core.domain.finance.m2_acceptance import M2AcceptanceError, validate_release_manifest

    root = _copy_acceptance_tree(tmp_path / "tree")
    path = root / "core" / "domain" / "finance" / "bad_route.py"
    path.write_text("from fastapi import APIRouter\n", encoding="utf-8")
    with pytest.raises(M2AcceptanceError) as exc:
        validate_release_manifest(root)
    assert exc.value.code == "framework_coupling_detected"


def test_verifier_uses_no_shell_subprocess():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "[sys.executable, str(script), \"create-and-verify\"]" in source


def test_verifier_refuses_the_wrong_development_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"' in source
    assert "refusing development verification" in source


def test_verifier_refuses_preexisting_disposable_databases():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "unexpected disposable databases exist" in source
    assert "disposable database already exists" in source


def test_verifier_rechecks_static_and_development_state_after_rehearsals():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    body = source.split("def _create_and_verify()", 1)[1].split("def main()", 1)[0]
    assert body.count("validate_release_manifest(ROOT)") == 2
    assert body.count("_verify_development()") == 2


def test_verifier_requires_every_child_pass_token():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'capability["pass_token"] not in completed.stdout' in source


def test_verifier_reports_one_final_acceptance_summary():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "m27_m2_acceptance=PASS" in source
    for phase in range(7):
        assert f"m2{phase}=PASS" in source


def test_documentation_records_the_release_tag_and_no_cutover():
    source = DOC_PATH.read_text(encoding="utf-8")
    assert "track-b-m2-canonical-event-engine-20260808" in source
    assert "does not authorize WND writer cutover" in source


def test_acceptance_module_is_framework_independent():
    source = ACCEPTANCE_PATH.read_text(encoding="utf-8")
    assert "from fastapi" not in source
    assert "import fastapi" not in source
