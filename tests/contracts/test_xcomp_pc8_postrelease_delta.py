"""XCOMP Wave1 N: historical PC8 and five-path candidate successor negatives.

All tests inspect only Git source or synthetic dictionary copies. No schemas,
protected manifests, remote services, keys, or financial effects are modified.
"""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from core.platform.release_integrity import ReleaseIntegrityError, verify_latest_release
from scripts.verify_xcomp_pc8_postrelease_delta import (
    ACCEPTED_LATER_SEALS,
    CandidateIntegrityDenied,
    HISTORIC,
    PC8_PATH,
    ROOT,
    _blob,
    _seal_digest,
    _sha,
    evaluate_pairs,
    inspect,
)


@pytest.fixture(scope="module")
def real_source_result():
    return inspect()


@pytest.fixture()
def candidate_inputs():
    manifest = json.loads((ROOT / PC8_PATH).read_text(encoding="utf-8"))
    expected = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    current = dict(expected)
    current.update({k: v[1] for k, v in ACCEPTED_LATER_SEALS.items()})
    later = {k: v[1] for k, v in ACCEPTED_LATER_SEALS.items()}
    return expected, dict(expected), current, later


def test_actual_historic_frozen_snapshot_40_of_40(real_source_result):
    assert real_source_result["historical_pc8_count"] == 40
    assert real_source_result["historical_pc8_match"] == 40
    assert real_source_result["historical_pc8_snapshot"] == "MATCH"
    assert real_source_result["historic_release_commit"] == HISTORIC


def test_current_exact_five_registered_descendants_without_minting_release(
    real_source_result,
):
    assert real_source_result["current_pc8_unchanged"] == 35
    assert real_source_result["current_descendant_count"] == 5
    assert set(real_source_result["descendant_paths"]) == set(ACCEPTED_LATER_SEALS)
    assert real_source_result["cumulative_release_registered"] is False
    assert real_source_result["owner_admission"].startswith("PENDING_")
    assert real_source_result["effective_authority"] == (
        "SOURCE_ONLY_NO_HOSTED_OR_RUNTIME_EFFECT"
    )


def test_old_pc8_validator_still_fails_and_is_not_silently_skipped():
    with pytest.raises(ReleaseIntegrityError, match="PC8 release manifest mismatch"):
        verify_latest_release(ROOT)


def test_candidate_is_not_a_frozen_pc8_artifact():
    manifest = json.loads((ROOT / PC8_PATH).read_text(encoding="utf-8"))
    protected = {entry["path"] for entry in manifest["artifacts"]}
    assert "scripts/verify_xcomp_pc8_postrelease_delta.py" not in protected
    assert "tests/contracts/test_xcomp_pc8_postrelease_delta.py" not in protected
    assert _sha(_blob(HISTORIC, PC8_PATH), PC8_PATH) == _sha(
        (ROOT / PC8_PATH).read_bytes(), PC8_PATH
    )


def test_positive_pure_lineage_validator(candidate_inputs):
    result = evaluate_pairs(*candidate_inputs)
    assert result["historical_pc8_match"] == 40
    assert result["current_descendant_count"] == 5


def test_denies_altered_historical_bytes(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    historic["core/platform/architecture_contract.py"] = "f" * 64
    with pytest.raises(CandidateIntegrityDenied, match="FROZEN_SNAPSHOT_MISMATCH"):
        evaluate_pairs(frozen, historic, current, seal)


def test_denies_sixth_unauthorized_descendant(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    other = next(path for path in frozen if path not in ACCEPTED_LATER_SEALS)
    current[other] = "f" * 64
    with pytest.raises(CandidateIntegrityDenied, match="FIVE_PATH_SCOPE_MISMATCH"):
        evaluate_pairs(frozen, historic, current, seal)


def test_denies_missing_proof_for_one_descendant(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    seal.pop("core/middleware/tenant_middleware.py")
    with pytest.raises(CandidateIntegrityDenied, match="SUCCESSOR_SEAL_SET_MISMATCH"):
        evaluate_pairs(frozen, historic, current, seal)


def test_denies_unregistered_changed_digest(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    seal["core/middleware/auth_middleware.py"] = "0" * 64
    with pytest.raises(CandidateIntegrityDenied, match="UNAUTHORIZED_DESCENDANT"):
        evaluate_pairs(frozen, historic, current, seal)


def test_denies_current_bytes_not_matching_registered_digest(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    current["core/middleware/branch_middleware.py"] = "e" * 64
    with pytest.raises(CandidateIntegrityDenied, match="UNAUTHORIZED_DESCENDANT"):
        evaluate_pairs(frozen, historic, current, seal)


def test_denies_missing_snapshot_artifact(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    historic.pop(next(iter(historic)))
    with pytest.raises(CandidateIntegrityDenied, match="ARTIFACT_SET_CHANGED"):
        evaluate_pairs(frozen, historic, current, seal)


def test_denies_relabelled_or_unrecorded_successor_seal(candidate_inputs):
    frozen, historic, current, seal = deepcopy(candidate_inputs)
    with pytest.raises(CandidateIntegrityDenied, match="UNRECOGNIZED_SEAL"):
        _seal_digest("core/middleware/auth_middleware.py", {}, "not-a-seal.json")


def test_denies_duplicated_specific_file_in_seal():
    seal = {"files": [
        {"path": "core/platform/architecture_contract.py", "successor_sha256": "a" * 64},
        {"path": "core/platform/architecture_contract.py", "successor_sha256": "a" * 64},
    ]}
    with pytest.raises(CandidateIntegrityDenied, match="SEAL_NOT_UNIQUE"):
        _seal_digest(
            "core/platform/architecture_contract.py",
            seal,
            "pc0_validator_successor_seal_r8.json",
        )
