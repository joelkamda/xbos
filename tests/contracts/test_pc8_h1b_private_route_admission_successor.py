from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.platform.release_integrity import (
    canonical_sha256,
    release_chain,
    verify_historical_release,
    verify_latest_release,
)
from scripts.verify_pc8_h1b_private_route_admission_successor import (
    require_full_regression_replacement,
    verify,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/platform/v1"
PRIVATE_PREFIX = "/internal/customer-channel/v1"


def _json(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_pc8_release_chain_is_exactly_1_through_8():
    chain = release_chain(ROOT)
    assert [number for number, _ in chain] == list(range(1, 9))
    assert verify_latest_release(ROOT) == {"latest": 8, "artifact_count": 40}


def test_pc1_through_pc7_manifests_are_immutable():
    contract = _json("pc8_h1b_private_route_admission_successor.json")
    for number in range(1, 8):
        path = CONTRACTS / f"pc{number}_release_manifest.json"
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(raw).hexdigest() == contract["historical_manifest_sha256"][f"pc{number}"]


def test_pc8_is_posthoc_successor_only_without_new_schema_head():
    contract = _json("pc8_h1b_private_route_admission_successor.json")
    manifest = _json("pc8_release_manifest.json")
    assert contract["release_class"] == "POSTHOC_RELEASE_INTEGRITY_SUCCESSOR_ONLY"
    assert manifest["previous_head"] == manifest["accepted_head"] == "ia0_neutral_interaction_authority_045"
    assert manifest["migration_count"] == 0
    assert contract["new_platform_business_authority"] is False
    assert contract["new_platform_schema_authority"] is False
    succession = contract["candidate_path_succession"]
    assert succession["historical_h1_authorized_path_count"] == 26
    assert succession["successor_addition_count"] == 6
    assert succession["current_candidate_path_count"] == 32
    assert set(succession["successor_additions"]) == {
        "contracts/platform/v1/pc0_h1b_composition_successor.json",
        "core/platform/architecture_contract.py",
        "core/platform/neutral_proof/dependency_authority.py",
        "tests/characterization/test_reconciliation_continuity.py",
        "tests/contracts/test_pc0_kernel_boundaries.py",
        "tests/contracts/test_pc6_neutral_platform_proof.py",
    }
    r2 = contract["full_regression_successor"]
    assert r2["authority"] == "XBOS-G02-C3-H1B-R2-R1-R2-R1-FULL-REGRESSION-SUCCESSOR-MATERIALIZATION-AND-REEXECUTION"
    assert r2["prior_candidate_path_count"] == 32
    assert r2["successor_addition_count"] == 7
    assert r2["current_candidate_path_count"] == 39
    assert (r2["main_collection"], r2["ia0_collection"], r2["combined_collection"]) == (2295, 15, 2310)
    assert r2["historical_manifest_rewrites"] == 0


def test_pc8_artifact_set_is_exact_40_without_manifest_self_hash():
    pc7 = _json("pc7_release_manifest.json")
    pc8 = _json("pc8_release_manifest.json")
    extra = {
        "startup.py",
        "core/middleware/auth_middleware.py",
        "core/middleware/tenant_middleware.py",
        "core/middleware/branch_middleware.py",
        "contracts/platform/v1/pc8_h1b_private_route_admission_successor.json",
        "scripts/verify_pc8_h1b_private_route_admission_successor.py",
        "tests/contracts/test_pc8_h1b_private_route_admission_successor.py",
    }
    expected = {item["path"] for item in pc7["artifacts"]} | extra
    actual = [item["path"] for item in pc8["artifacts"]]
    assert len(actual) == len(set(actual)) == 40
    assert set(actual) == expected
    assert "contracts/platform/v1/pc8_release_manifest.json" not in actual


def test_every_historical_release_resolves_exactly_through_pc8():
    pc8 = _json("pc8_release_manifest.json")
    reports = {number: verify_historical_release(ROOT, number) for number in range(1, 8)}
    assert all(report["latest"] == 8 for report in reports.values())
    assert {
        number: report["replacement_count"] for number, report in reports.items()
    } == {
        number: len(pc8[f"historical_pc{number}_replacements"])
        for number in range(1, 8)
    }


def test_private_prefix_bypasses_human_tenant_and_branch_admission_only():
    contract = _json("pc8_h1b_private_route_admission_successor.json")
    needle = f'            or path.startswith("{PRIVATE_PREFIX}")\n'
    for relative in (
        "core/middleware/auth_middleware.py",
        "core/middleware/tenant_middleware.py",
        "core/middleware/branch_middleware.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert text.count(needle) == 1
        restored = text.replace(needle, "", 1).encode("utf-8")
        assert hashlib.sha256(restored).hexdigest() == contract["accepted_base_canonical_sha256"][relative]
    assert contract["request_state_tenant_id_preset"] is False
    assert contract["request_state_branch_id_preset"] is False
    assert contract["caller_x_tenant_code_authority"] is False
    assert contract["caller_x_branch_code_authority"] is False


def test_pc7_is_immutable_historical_milestone_under_pc8():
    pc7 = _json("pc7_release_manifest.json")
    report = verify_historical_release(ROOT, 7)
    assert pc7["accepted_head"] == "ia0_neutral_interaction_authority_045"
    assert pc7["migration_count"] == 1
    assert report["latest"] == 8
    assert report["replacement_count"] == len(_json("pc8_release_manifest.json")["historical_pc7_replacements"])


def test_pc8_successor_verifier_proves_all_required_boundaries():
    result = verify()
    assert result["status"] == "PASS"
    assert result["release_sequence"] == 8
    assert result["artifact_count"] == 40
    assert result["historical_authorized_path_count"] == 26
    assert result["successor_addition_count"] == 6
    assert result["r2_successor_addition_count"] == 7
    assert result["current_candidate_path_count"] == 39
    assert result["full_regression_replacement_count"] == 9
    assert (result["main_collection"], result["ia0_collection"], result["combined_collection"]) == (2295, 15, 2310)
    assert result["private_auth_bypass"] == "PASS"
    assert result["private_tenant_bypass"] == "PASS"
    assert result["private_branch_bypass"] == "PASS"
    assert result["pc1_to_pc7_manifest_mutation"] is False
    assert result["migration_count"] == 0
    assert result["finance_authority_change"] is False
    assert result["inventory_authority_change"] is False

    contract = _json("pc8_h1b_private_route_admission_successor.json")
    arch = next(
        item for item in contract["full_regression_successor"]["replacements"]
        if item["path"] == "core/platform/architecture_contract.py"
    )
    require_full_regression_replacement(
        arch["path"], arch["historical_sha256"], arch["descendant_sha256"],
        "scripts/verify_pk_aggregate_conformance_freeze.py",
    )
    with pytest.raises(RuntimeError, match="HISTORICAL_HASH_MISMATCH"):
        require_full_regression_replacement(
            arch["path"], "0" * 64, arch["descendant_sha256"],
            "scripts/verify_pk_aggregate_conformance_freeze.py",
        )
    with pytest.raises(RuntimeError, match="DESCENDANT_HASH_MISMATCH"):
        require_full_regression_replacement(
            arch["path"], arch["historical_sha256"], "f" * 64,
            "scripts/verify_pk_aggregate_conformance_freeze.py",
        )
    with pytest.raises(RuntimeError, match="UNAUTHORIZED_CONSUMER"):
        require_full_regression_replacement(
            arch["path"], arch["historical_sha256"], arch["descendant_sha256"],
            "scripts/not_authorized.py",
        )
    with pytest.raises(RuntimeError, match="UNLISTED"):
        require_full_regression_replacement(
            "scripts/not_listed.py", "0" * 64, "f" * 64,
            "scripts/not_authorized.py",
        )
