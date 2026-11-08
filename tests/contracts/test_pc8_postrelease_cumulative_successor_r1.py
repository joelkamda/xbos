"""Source-only PC8 cumulative successor candidate R1: historical/current negatives.

Tests operate on proposal dictionaries and synthetic raw byte copies, never
mutating historical manifests, middleware, PC8 validators or live services.
"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from core.platform.release_integrity import ReleaseIntegrityError, verify_latest_release
from scripts.verify_pc8_postrelease_cumulative_successor_r1 import (
    CANDIDATE_REL,
    ROOT,
    check_clean_tracked,
    check_frozen_manifest,
    validate_record,
    verify,
)
from scripts.verify_xcomp_pc8_postrelease_delta import (
    ACCEPTED_LATER_SEALS,
    CANDIDATE_HEAD,
    CandidateIntegrityDenied,
    HISTORIC,
    PC8_PATH,
    _blob,
)


@pytest.fixture(scope="module")
def frozen_expected():
    source = json.loads(_blob(HISTORIC, PC8_PATH, ROOT))
    return {row["path"]: row["sha256"] for row in source["artifacts"]}


@pytest.fixture
def candidate():
    return json.loads((ROOT / CANDIDATE_REL).read_text(encoding="utf8"))


def deny(candidate, expected, code, **overrides):
    with pytest.raises(CandidateIntegrityDenied, match=code):
        validate_record(candidate, expected, **overrides)


def test_actual_final_cumulative_source_proof():
    receipt = verify(ROOT)
    assert receipt["historical_pc8_artifacts_matched"] == 40
    assert receipt["manifests_pc1_pc8_unchanged"] == 8
    assert receipt["current_pc8_artifacts_unchanged"] == 35
    assert receipt["current_sealed_descendants"] == 5
    assert set(receipt["descendant_paths"]) == set(ACCEPTED_LATER_SEALS)
    assert receipt["source_git_head"] == CANDIDATE_HEAD
    assert receipt["registered_release"] is False
    assert receipt["operative_authority"] is False
    assert receipt["hosted_or_db_effect"] is False


def test_pure_exact_record_acceptance(candidate, frozen_expected):
    found = validate_record(candidate, frozen_expected)
    assert set(found) == set(ACCEPTED_LATER_SEALS)


def test_legacy_latest_release_integrity_still_expected_fail():
    with pytest.raises(ReleaseIntegrityError, match="PC8 release manifest mismatch="):
        verify_latest_release(ROOT)


def test_frozen_snapshot_bytes_mutation_denied():
    with pytest.raises(CandidateIntegrityDenied, match="HISTORICAL_MANIFEST_MUTATED"):
        check_frozen_manifest(b"a\r\nb", b"a\r\nc", "pc8_release_manifest.json")


def test_crlf_only_historical_snapshot_normalization_accepted():
    check_frozen_manifest(b"a\r\nb\r\n", b"a\nb\n", "pc8_release_manifest.json")


def test_dirty_protected_source_denied():
    with pytest.raises(CandidateIntegrityDenied, match="DIRTY_PROTECTED_SOURCE"):
        check_clean_tracked(b"authorization=disabled", b"authorization=enabled",
                            "core/middleware/auth_middleware.py")


def test_protected_source_crlf_only_is_not_dirty():
    check_clean_tracked(b"stable\r\nsource\r\n", b"stable\nsource\n",
                        "core/middleware/tenant_middleware.py")


def test_denies_pretend_operative_registration(candidate, frozen_expected):
    for key in ("registered", "active", "successor_promoted", "operative_authority"):
        bad = deepcopy(candidate)
        bad[key] = True
        deny(bad, frozen_expected, "FALSE_OPERATIVE_RELEASE")


def test_denies_invented_pc9_number(candidate, frozen_expected):
    candidate["declared_release_number"] = 9
    deny(candidate, frozen_expected, "PREMATURE_NEW_RELEASE_NUMBER")


def test_denies_nonpending_candidate(candidate, frozen_expected):
    candidate["record_state"] = "ACTIVE_RELEASE"
    deny(candidate, frozen_expected, "STATE_NOT_PENDING")


def test_denies_wrong_pcr_root(candidate, frozen_expected):
    candidate["pcr_parent_root_sha256"] = "f" * 64
    deny(candidate, frozen_expected, "PCR_ROOT_MISMATCH")


def test_denies_wrong_producer_grant(candidate, frozen_expected):
    candidate["exact_source_grant_sha256"] = "e" * 64
    deny(candidate, frozen_expected, "GRANT_MISMATCH")


def test_denies_tampered_predecessor_evidence_pointer(candidate, frozen_expected):
    candidate["predecessor_candidate_sha256"] = "b" * 64
    deny(candidate, frozen_expected, "PREDECESSOR_PROOF_MISMATCH")


def test_denies_historical_manifest_digest_change(candidate, frozen_expected):
    candidate["historical"]["manifest_sha256_canonical"] = "a" * 64
    deny(candidate, frozen_expected, "FROZEN_DIGEST_CHANGED")


def test_denies_historical_commit_or_count_drift(candidate, frozen_expected):
    bad = deepcopy(candidate)
    bad["historical"]["git_commit"] = CANDIDATE_HEAD
    deny(bad, frozen_expected, "HISTORICAL_COMMIT_CHANGED")
    bad = deepcopy(candidate)
    bad["historical"]["historical_pc8_artifact_count"] = 39
    deny(bad, frozen_expected, "HISTORICAL_COUNT_CHANGED")


def test_denies_current_source_head_or_branch_drift(candidate, frozen_expected):
    deny(candidate, frozen_expected, "UNPINNED_CURRENT_SOURCE", current_head="f" * 40)
    deny(candidate, frozen_expected, "UNPINNED_SOURCE_BRANCH", current_branch="other-branch")


def test_denies_sixth_descendant(candidate, frozen_expected):
    extra = next(k for k in frozen_expected if k not in ACCEPTED_LATER_SEALS)
    candidate["cumulative_current"]["exact_descendants"].append({
        "path": extra, "pc8_historical_sha256": frozen_expected[extra],
        "current_descendant_sha256": "f" * 64,
        "source_successor_seal": "contracts/platform/v1/invalid.json",
        "admission": "PROPOSED_NONOPERATIVE",
    })
    deny(candidate, frozen_expected, "FIVE_PATH_SCOPE_MISMATCH")


def test_denies_missing_descendant(candidate, frozen_expected):
    candidate["cumulative_current"]["exact_descendants"].pop()
    deny(candidate, frozen_expected, "FIVE_PATH_SCOPE_MISMATCH")


def test_denies_duplicate_descendant(candidate, frozen_expected):
    rows = candidate["cumulative_current"]["exact_descendants"]
    rows[-1] = deepcopy(rows[0])
    deny(candidate, frozen_expected, "DUPLICATE_OR_MALFORMED_DESCENDANT")


def test_denies_wrong_descendant_path(candidate, frozen_expected):
    candidate["cumulative_current"]["exact_descendants"][0]["path"] = (
        "core/middleware/incorrect_middleware.py"
    )
    deny(candidate, frozen_expected, "UNAUTHORIZED_DESCENDANT_SET")


def test_denies_wrong_historical_pair_sha(candidate, frozen_expected):
    candidate["cumulative_current"]["exact_descendants"][0]["pc8_historical_sha256"] = "f" * 64
    deny(candidate, frozen_expected, "HISTORICAL_DESCENDANT_HASH_MISMATCH")


def test_denies_changed_current_descendant_sha(candidate, frozen_expected):
    candidate["cumulative_current"]["exact_descendants"][0]["current_descendant_sha256"] = "e" * 64
    deny(candidate, frozen_expected, "CURRENT_DESCENDANT_HASH_MISMATCH")


def test_denies_mismatched_seal(candidate, frozen_expected):
    candidate["cumulative_current"]["exact_descendants"][0]["source_successor_seal"] = (
        "contracts/platform/v1/pc0_validator_successor_seal_r8.json"
    )
    deny(candidate, frozen_expected, "UNAUTHORIZED_SOURCE_SEAL")


def test_denies_fake_descendant_activation(candidate, frozen_expected):
    candidate["cumulative_current"]["exact_descendants"][0]["admission"] = "ACTIVE"
    deny(candidate, frozen_expected, "UNAPPROVED_DESCENDANT_ADMISSION")


def test_denies_silent_disable_of_legacy_validator(candidate, frozen_expected):
    candidate["verification_protocol"]["current_legacy_pc8_validator"] = "SKIP"
    deny(candidate, frozen_expected, "OLD_VALIDATOR_BYPASS")


def test_denies_fingerprint_policy_drift(candidate, frozen_expected):
    candidate["historical"]["historical_artifact_digest_mode"] = "raw_bytes_only"
    deny(candidate, frozen_expected, "FINGERPRINT_MODE_CHANGED")
