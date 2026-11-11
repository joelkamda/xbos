"""N D1/D2 additive postmerge PC8 candidate-only integrity and negatives."""
from __future__ import annotations

from pathlib import Path
import pytest

from scripts import verify_xcomp_n_d1d2_pc8_merged_bridge_r0 as bridge
from scripts.verify_xcomp_pc8_postrelease_delta import CandidateIntegrityDenied


@pytest.fixture(scope="module")
def actual_pinned_integrity():
    return bridge.inspect()


def test_actual_merged_pc8_lineage_forty_historical_and_exact_five(actual_pinned_integrity):
    result = actual_pinned_integrity
    assert result["historical_pc8_count"] == 40
    assert result["historical_pc8_match"] == 40
    assert result["current_pc8_unchanged"] == 35
    assert result["current_descendant_count"] == 5
    # The exact accepted merge is the immutable ancestor, not the candidate HEAD.
    from scripts.verify_xcomp_pc8_postrelease_delta import _git
    assert result["postmerge_source_head"] == _git(
        "rev-parse", "HEAD", root=Path(__file__).resolve().parents[2]
    ).decode().strip()
    assert result["isolated_lane_branch"] == bridge.INTEGRATION_BRANCH


def test_actual_integrity_does_not_promote_operative_release(actual_pinned_integrity):
    result = actual_pinned_integrity
    assert result["source_integrity_candidate"] == "PASS_LOCAL_PINNED_MERGED_SOURCE"
    assert result["operative_release"] is False
    assert result["cumulative_release_registered"] is False
    assert result["D1_hosted"] == "HOLD"
    assert result["D2_activation"] == "HOLD"
    assert result["independent_operative_issuer_proven"] is False
    assert result["github_required_checks_proven"] is False


def test_existing_frozen_pc8_source_verifier_still_byte_identical():
    import hashlib
    root = Path(__file__).resolve().parents[2]
    assert hashlib.sha256((root / "core/platform/release_integrity.py").read_bytes()).hexdigest() == bridge.FROZEN_VERIFIER_RAW_SHA


def test_rejects_other_merged_source_head(monkeypatch):
    monkeypatch.setattr(bridge, "MERGED_HEAD", "0" * 40)
    with pytest.raises(CandidateIntegrityDenied, match="WRONG_MERGED_SOURCE_HEAD"):
        bridge.inspect()


def test_rejects_other_isolated_source_branch(monkeypatch):
    monkeypatch.setattr(bridge, "INTEGRATION_BRANCH", "attacker/review")
    with pytest.raises(CandidateIntegrityDenied, match="WRONG_MERGED_SOURCE_BRANCH"):
        bridge.inspect()


def test_rejects_tampered_original_verifier_digest(monkeypatch):
    monkeypatch.setattr(bridge, "FROZEN_VERIFIER_RAW_SHA", "0" * 64)
    with pytest.raises(CandidateIntegrityDenied, match="FROZEN_PC8_VERIFIER_TAMPERED"):
        bridge.inspect()


def event(**overrides):
    body = {
        "commit_sha": bridge.MERGED_HEAD,
        "checked_out_sha": bridge.MERGED_HEAD,
        "branch": bridge.MERGED_BRANCH,
        "repository": "joelkamda/xbos",
        "event_name": "source_candidate",
        "proof_nonce": "N-test-nonce-001",
        "previously_seen": frozenset(),
    }
    body.update(overrides)
    return body


def test_pure_event_binding_is_only_nonoperative_test_proof():
    result = bridge.validate_proposed_source_event(**event())
    assert result["source_head"] == bridge.MERGED_HEAD
    assert result["source_only"] is True
    assert result["operative_release"] is False
    assert result["nonce_is_local_test_only"] is True


@pytest.mark.parametrize("invalid,reason", [
    ({"commit_sha": "0" * 40}, "WRONG_MERGED_SOURCE_SHA"),
    ({"checked_out_sha": "0" * 40}, "WRONG_MERGED_SOURCE_SHA"),
    ({"commit_sha": ""}, "INVALID_EVENT_SHA"),
    ({"checked_out_sha": "fake"}, "INVALID_CHECKOUT_SHA"),
    ({"branch": "main"}, "WRONG_MERGED_SOURCE_BRANCH"),
    ({"branch": "review/other"}, "WRONG_MERGED_SOURCE_BRANCH"),
    ({"repository": "someone-else/xbos"}, "WRONG_SOURCE_REPOSITORY"),
    ({"repository": ""}, "WRONG_SOURCE_REPOSITORY"),
    ({"event_name": "pull_request_target"}, "UNTRUSTED_GITHUB_EVENT_OR_RELEASE_MODE"),
    ({"event_name": "operative_release"}, "UNTRUSTED_GITHUB_EVENT_OR_RELEASE_MODE"),
    ({"proof_nonce": ""}, "INVALID_SOURCE_PROOF_NONCE"),
    ({"proof_nonce": "bad"}, "INVALID_SOURCE_PROOF_NONCE"),
    ({"previously_seen": frozenset({"N-test-nonce-001"})}, "REPLAYED_SOURCE_PROOF_NONCE"),
])
def test_pure_negative_event_identity_replay_or_untrusted_claim(invalid, reason):
    with pytest.raises(CandidateIntegrityDenied, match=reason):
        bridge.validate_proposed_source_event(**event(**invalid))
