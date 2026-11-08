"""Route A five-file local source acceptance and fail-closed negative suite.

No provider, GitHub, registration, source mutation or private-key operations.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_pc8_registered_current_source_r1 import (
    COMPANION_ID, REGISTRY_REL, REQUIRED_CHECK, ROOT,
    CurrentReleaseDenied, EXPECTED_STATUS, OLD_SIX, EXACT_FIVE,
    CANDIDATE_HEAD, HISTORIC, SOURCE_BRANCH,
    check_source_prestate, compare_artifact_sets, digest,
    require_attestation_bindings, require_frozen, validate_registry,
    verify_local_candidate, verify_operative,
    validate_committed_checkout_binding, verify_committed_preflight,
    GITHUB_REPOSITORY, SOURCE_BRANCH, EXACT_REVIEW_BRANCH,
    validate_pr_event_payload,
)
from scripts.verify_xcomp_pc8_postrelease_delta import (
    ACCEPTED_LATER_SEALS, _blob, _sha,
)


@pytest.fixture
def registry():
    return json.loads((ROOT / REGISTRY_REL).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshots():
    manifest = json.loads(_blob(HISTORIC, "contracts/platform/v1/pc8_release_manifest.json"))
    historical = {row["path"]: row["sha256"] for row in manifest["artifacts"]}
    old = {rel: _sha(_blob(HISTORIC, rel), rel) for rel in historical}
    current = {rel: _sha((ROOT / rel).read_bytes(), rel) for rel in historical}
    sealed = {rel: item[1] for rel, item in ACCEPTED_LATER_SEALS.items()}
    return historical, old, current, sealed


def denies(code, callback, *args, **kwargs):
    with pytest.raises(CurrentReleaseDenied, match=code):
        callback(*args, **kwargs)


def structural_external_proof():
    # A syntactically valid sample is NEVER a trusted operative proof.
    return {
        "companion_id": COMPANION_ID,
        "registered_git_head": CANDIDATE_HEAD,
        "required_ci_status": REQUIRED_CHECK,
        "ci_verified_source_head": CANDIDATE_HEAD,
        "deploy_verified_source_head": CANDIDATE_HEAD,
        "branch_protection_required": True,
        "signature_revoked": False,
        "issuance_nonce": "SYNTHETIC-NONOPERATIVE-000001",
    }


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="precommit-only source state")
def test_positive_exact_nonoperative_source_and_historical_40():
    result = verify_local_candidate(ROOT)
    assert result["status"] == "PASS_LOCAL_CURRENT_SOURCE_CANDIDATE_ONLY"
    assert result["historical_pc8_artifacts"] == 40
    assert result["frozen_manifests"] == 8
    assert result["current_pc8_unchanged"] == 35
    assert result["sealed_descendants"] == 5
    assert result["legacy_verify_latest_release"] == "EXPECTED_FAIL_UNCHANGED"
    assert result["operative_release"] is False


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="precommit-only source state")
def test_cli_local_candidate_real_process_pass():
    proc = subprocess.run(
        [sys.executable, "scripts/verify_pc8_registered_current_source_r1.py",
         "--local-candidate"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=90,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert json.loads(proc.stdout)["operative_release"] is False


def test_default_cli_has_no_implicit_operative_or_local_fallback():
    p = subprocess.run(
        [sys.executable, "scripts/verify_pc8_registered_current_source_r1.py"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=20,
    )
    assert p.returncode != 0


def test_positive_registry_structural_candidate_only(registry):
    validate_registry(registry)
    assert registry["status"] == "PROPOSED_NONOPERATIVE"
    assert registry["registered"] is False and registry["active"] is False
    assert registry["issuer"]["operative_issuer_trust_anchor"] is None


def test_positive_historical_current_five_exact(snapshots):
    baseline, old, current, sealed = snapshots
    assert compare_artifact_sets(baseline, old, current, sealed) == {
        "historical": 40, "unchanged": 35, "sealed_descendants": 5,
    }


def test_frozen_pc8_verifier_byte_equality(snapshots):
    rel = "core/platform/release_integrity.py"
    require_frozen((ROOT / rel).read_bytes(), _blob(HISTORIC, rel), rel)


def test_stale_or_missing_registry_identity_denied(registry):
    registry["companion_id"] = "XCOMP_PLATFORM_CORE_PC9"
    denies("BAD_COMPANION_IDENTITY", validate_registry, registry)


def test_local_registered_flag_cannot_activate(registry):
    registry["registered"] = True
    denies("UNAUTHORIZED_LOCAL_SELF_ACTIVATION", validate_registry, registry)


def test_local_active_flag_cannot_activate(registry):
    registry["active"] = True
    denies("UNAUTHORIZED_LOCAL_SELF_ACTIVATION", validate_registry, registry)


def test_changed_state_cannot_promote(registry):
    registry["status"] = "OPERATIVE"
    denies("UNAUTHORIZED_STATUS_PROMOTION", validate_registry, registry)


def test_local_pc9_invention_rejected(registry):
    registry["release_sequence"] = 9
    denies("INVENTED_RELEASE_SEQUENCE", validate_registry, registry)


def test_forged_pcr_scope_grant_denied(registry):
    registry["authority"]["pcr_source_grant_sha256"] = "0" * 64
    denies("GRANT_NOT_PINNED", validate_registry, registry)


def test_forged_source_owner_denied(registry):
    registry["issuer"]["proposed_source_owner"] = "wrong-principal"
    denies("SOURCE_OWNER_IDENTITY_MISMATCH", validate_registry, registry)


def test_forged_public_key_fingerprint_denied(registry):
    registry["issuer"]["verified_source_owner_public_key_fingerprint"] = "SHA256:fake"
    denies("SOURCE_OWNER_IDENTITY_MISMATCH", validate_registry, registry)


def test_forged_operational_issuer_denied(registry):
    registry["issuer"]["operative_issuer_trust_anchor"] = "/fake/owner-key"
    denies("FORGED_OPERATIVE_ISSUER", validate_registry, registry)


def test_forged_local_release_signature_denied(registry):
    registry["current_operative"]["pcr_independent_release_signature"] = "forged"
    denies("FORGED_OPERATIVE_EVIDENCE", validate_registry, registry)


def test_self_accepted_registry_digest_denied(registry):
    registry["current_operative"]["accepted_registry_sha256"] = "f" * 64
    denies("FORGED_OPERATIVE_EVIDENCE", validate_registry, registry)


def test_wrong_required_ci_name_denied(registry):
    registry["current_operative"]["required_github_check_name"] = "optional-ci"
    denies("WRONG_REQUIRED_CI_CHECK", validate_registry, registry)


def test_changed_historical_head_denied(registry):
    registry["historical"]["git_commit"] = CANDIDATE_HEAD
    denies("HISTORICAL_COMMIT_DRIFT", validate_registry, registry)


def test_historical_manifest_corruption_denied():
    denies(
        "FROZEN_MANIFEST_OR_VERIFIER_MUTATION", require_frozen,
        b"{\"modified\":true}", b"{\"original\":true}",
        "contracts/platform/v1/pc8_release_manifest.json",
    )


def test_historical_corrupted_artifact_denied(snapshots):
    historical, old, current, sealed = snapshots
    old = copy.deepcopy(old)
    old["core/platform/release_integrity.py"] = "f" * 64
    denies("HISTORICAL_ARTIFACT_CORRUPT",
           compare_artifact_sets, historical, old, current, sealed)


def test_sixth_modified_artifact_denied(snapshots):
    historical, old, current, sealed = snapshots
    current = copy.deepcopy(current)
    current["core/platform/release_integrity.py"] = "f" * 64
    denies("UNSEALED_FIFTH_SIXTH_OR_SEVENTH_DESCENDANT",
           compare_artifact_sets, historical, old, current, sealed)


def test_changed_fifth_successor_digest_denied(snapshots):
    historical, old, current, sealed = snapshots
    current = copy.deepcopy(current)
    current["core/platform/architecture_contract.py"] = "e" * 64
    denies("SOURCE_SEAL_MISMATCH",
           compare_artifact_sets, historical, old, current, sealed)


def test_missing_successor_seal_denied(snapshots):
    historical, old, current, sealed = snapshots
    sealed = copy.deepcopy(sealed)
    sealed.pop("core/platform/architecture_contract.py")
    denies("MISSING_OR_EXTRA_SOURCE_SEAL",
           compare_artifact_sets, historical, old, current, sealed)


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="local precommit git prestate only")
def test_wrong_source_head_denied_by_real_git_gate(monkeypatch):
    from scripts import verify_pc8_registered_current_source_r1 as module
    original_git = module._git

    def drift(command, *args, **kwargs):
        if command == "rev-parse":
            return b"a" * 40 + b"\n"
        return original_git(command, *args, **kwargs)

    monkeypatch.setattr(module, "_git", drift)
    denies("WRONG_SOURCE_HEAD", check_source_prestate, ROOT)


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="local precommit git prestate only")
def test_wrong_source_branch_denied_by_real_git_gate(monkeypatch):
    from scripts import verify_pc8_registered_current_source_r1 as module
    original_git = module._git

    def drift(command, *args, **kwargs):
        if command == "branch":
            return b"wrong-branch\n"
        return original_git(command, *args, **kwargs)

    monkeypatch.setattr(module, "_git", drift)
    denies("WRONG_SOURCE_BRANCH", check_source_prestate, ROOT)


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="local precommit git prestate only")
def test_unexpected_extra_or_missing_source_file_denied(monkeypatch):
    from scripts import verify_pc8_registered_current_source_r1 as module
    original_git = module._git

    def injected(command, *args, **kwargs):
        if command == "status":
            return ("\n".join(sorted(EXPECTED_STATUS | {
                "?? scripts/unregistered_sixth.py",
            })) + "\n").encode()
        return original_git(command, *args, **kwargs)

    monkeypatch.setattr(module, "_git", injected)
    denies("UNAPPROVED_WORKTREE_PATH_SET", check_source_prestate, ROOT)


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="local precommit git prestate only")
def test_dirty_tracked_source_denied(monkeypatch):
    from scripts import verify_pc8_registered_current_source_r1 as module
    original_git = module._git

    def injected(command, *args, **kwargs):
        if command == "diff" and args[:1] == ("--name-only",):
            return b"core/platform/release_integrity.py\n"
        return original_git(command, *args, **kwargs)

    monkeypatch.setattr(module, "_git", injected)
    denies("DIRTY_TRACKED_SOURCE", check_source_prestate, ROOT)


def test_wrong_external_registration_head_denied():
    proof = structural_external_proof()
    proof["registered_git_head"] = "d" * 40
    denies("WRONG_ATTESTED_HEAD", require_attestation_bindings, proof)


def test_wrong_external_required_ci_status_denied():
    proof = structural_external_proof()
    proof["required_ci_status"] = "legacy-PC8-only"
    denies("WRONG_REQUIRED_CI_STATUS", require_attestation_bindings, proof)


def test_ci_commit_mismatch_denied():
    proof = structural_external_proof()
    proof["ci_verified_source_head"] = "e" * 40
    denies("CI_SOURCE_HEAD_MISMATCH", require_attestation_bindings, proof)


def test_deploy_commit_mismatch_denied():
    proof = structural_external_proof()
    proof["deploy_verified_source_head"] = "b" * 40
    denies("DEPLOY_SOURCE_HEAD_MISMATCH", require_attestation_bindings, proof)


def test_disabled_branch_rule_denied():
    proof = structural_external_proof()
    proof["branch_protection_required"] = False
    denies("MISSING_REQUIRED_BRANCH_PROTECTION", require_attestation_bindings, proof)


def test_revoked_or_replayed_receipt_denied():
    proof = structural_external_proof()
    proof["signature_revoked"] = True
    denies("REVOKED_OR_REPLAYED_PROOF", require_attestation_bindings, proof)


def test_missing_nonce_denied():
    proof = structural_external_proof()
    proof["issuance_nonce"] = "replay"
    denies("MISSING_OR_REPLAYED_NONCE", require_attestation_bindings, proof)


def test_missing_any_externally_trusted_proof_denied():
    denies("MISSING_EXTERNAL_OPERATIVE_PROOF", require_attestation_bindings, None)


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="precommit-only source state")
def test_structurally_good_external_proof_is_not_trusted_for_operativity():
    proof = structural_external_proof()
    require_attestation_bindings(proof)
    denies(
        "OPERATIVE_HOLD_INDEPENDENT_ISSUER_REQUIRED_CI_AND_DEPLOY_NOT_COMMISSIONED",
        verify_operative, ROOT, proof,
    )


def test_operative_cli_exits_nonzero_without_external_commissioning():
    p = subprocess.run(
        [sys.executable, "scripts/verify_pc8_registered_current_source_r1.py",
         "--operative"], cwd=str(ROOT), capture_output=True, text=True, timeout=90,
    )
    assert p.returncode != 0
    r = json.loads(p.stdout)
    assert r["status"] == "DENIED" and r["operative_release"] is False


# Synthetic committed states test the STRICT contract in memory, without
# executing even one Git commit or silently authorizing operative release.

SYNTHETIC_POSTCOMMIT_SHA = "c" * 40


def simulated_committed_context(**overrides):
    context = {
        "actual_head": SYNTHETIC_POSTCOMMIT_SHA,
        "event_sha": SYNTHETIC_POSTCOMMIT_SHA,
        "expected_sha": SYNTHETIC_POSTCOMMIT_SHA,
        "repository": GITHUB_REPOSITORY,
        "event_name": "push",
        "branch": SOURCE_BRANCH,
        "parent_is_ancestor": True,
        "clean": True,
        "required_files_tracked": True,
    }
    context.update(overrides)
    return context


def test_synthetic_postcommit_positive_only_source_not_operative():
    result = validate_committed_checkout_binding(**simulated_committed_context())
    assert result["source_commit_bound"] == SYNTHETIC_POSTCOMMIT_SHA
    assert result["candidate_only"] is True
    assert result["independent_operative_release_approved"] is False


@pytest.mark.parametrize("bad,code", [
    ({"actual_head": "0" * 40}, "WRONG_COMMITTED_SOURCE_SHA"),
    ({"expected_sha": "a" * 40}, "WRONG_COMMITTED_SOURCE_SHA"),
    ({"event_sha": "b" * 40}, "WRONG_COMMITTED_SOURCE_SHA"),
    ({"expected_sha": None}, "MISSING_OR_MALFORMED_EXPECTED_SOURCE_SHA"),
    ({"event_sha": None}, "MISSING_OR_MALFORMED_EVENT_SOURCE_SHA"),
    ({"actual_head": "not-a-hash"}, "MISSING_OR_MALFORMED_ACTUAL_SOURCE_SHA"),
    ({"repository": "attacker/fork"}, "WRONG_COMMITTED_EVENT_REPOSITORY"),
    ({"event_name": "pull_request_target"}, "WRONG_GITHUB_EVENT_TYPE"),
    ({"branch": "untrusted-branch"}, "WRONG_COMMITTED_SOURCE_BRANCH"),
    ({"parent_is_ancestor": False}, "PARENT_NOT_VERIFIED_ANCESTOR"),
    ({"clean": False}, "DIRTY_COMMITTED_CHECKOUT"),
    ({"required_files_tracked": False}, "MISSING_REQUIRED_TRACKED_CANDIDATE_FILES"),
    ({"actual_head": CANDIDATE_HEAD, "event_sha": CANDIDATE_HEAD,
      "expected_sha": CANDIDATE_HEAD}, "UNCHANGED_PRECOMMIT_SOURCE_HEAD"),
])
def test_synthetic_committed_negative_controls(bad, code):
    denies(code, validate_committed_checkout_binding,
           **simulated_committed_context(**bad))


def test_no_local_registry_based_commit_promotion(registry):
    registry["postcommit_source_candidate"]["status"] = "COMMISSIONED"
    denies("FALSE_POSTCOMMIT_OPERATIVE_PROMOTION", validate_registry, registry)


def test_fake_pcr_release_receipt_in_registry_denied(registry):
    registry["postcommit_source_candidate"]["separately_verified_independent_owner_controller_release_proof"] = {
        "pcr": "self-signed"
    }
    denies("FORGED_POSTCOMMIT_AUTHORITY", validate_registry, registry)


def test_fake_deploy_receipt_in_registry_denied(registry):
    registry["postcommit_source_candidate"]["same_commit_deploy_admission"] = "fake"
    denies("FORGED_POSTCOMMIT_AUTHORITY", validate_registry, registry)


def test_fake_required_branch_check_receipt_denied(registry):
    registry["postcommit_source_candidate"]["protected_required_branch_check_receipt"] = "self-signed"
    denies("FORGED_POSTCOMMIT_AUTHORITY", validate_registry, registry)


def test_postcommit_mode_disabled_denied(registry):
    registry["postcommit_source_candidate"]["require_exact_event_checkout_commit"] = False
    denies("POSTCOMMIT_SECURITY_DISABLED", validate_registry, registry)


def test_synthetic_github_context_is_not_an_operative_issuer(monkeypatch):
    # A locally spoofed GITHUB_ACTIONS cannot install real proof. The current
    # checkout is still PRECOMMIT and therefore is correctly rejected.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", CANDIDATE_HEAD)
    monkeypatch.setenv("GITHUB_REPOSITORY", GITHUB_REPOSITORY)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_HEAD_REF", SOURCE_BRANCH)
    with pytest.raises(CurrentReleaseDenied) as caught:
        verify_committed_preflight(ROOT, expected_source_sha=CANDIDATE_HEAD)
    # Uncommitted local source denies as dirty; a future committed checkout
    # denies because the spoofed event SHA is not its actual reviewed HEAD.
    assert str(caught.value) in (
        "COMMITTED_WORKTREE_NOT_CLEAN",
        "UNCHANGED_PRECOMMIT_SOURCE_HEAD",
        "WRONG_COMMITTED_SOURCE_SHA",
    )


def test_committed_mode_without_github_runner_denied(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    denies("MISSING_GITHUB_RUNNER_SOURCE_CONTEXT",
           verify_committed_preflight, ROOT, expected_source_sha=SYNTHETIC_POSTCOMMIT_SHA)


def test_real_cli_committed_without_expected_sha_denied():
    p = subprocess.run([
        sys.executable, "scripts/verify_pc8_registered_current_source_r1.py",
        "--committed-preflight"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert p.returncode != 0
    assert "requires --expected-source-sha" in p.stderr


def test_real_cli_committed_source_not_forged_by_local_arg(monkeypatch):
    p = subprocess.run([
        sys.executable, "scripts/verify_pc8_registered_current_source_r1.py",
        "--committed-preflight",
        "--expected-source-sha", SYNTHETIC_POSTCOMMIT_SHA],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        env={k: v for k, v in __import__("os").environ.items()
             if k != "GITHUB_ACTIONS"},
    )
    assert p.returncode == 2
    assert "MISSING_GITHUB_RUNNER_SOURCE_CONTEXT" in p.stdout


def test_operative_external_proof_revocation_not_bypassed_by_mock_event():
    proof = structural_external_proof()
    proof["signature_revoked"] = True
    denies("REVOKED_OR_REPLAYED_PROOF", require_attestation_bindings, proof)


def test_committed_source_integrity_is_distinct_from_release_owner_approval(registry):
    assert registry["postcommit_source_candidate"]["postcommit_source_integrity_is_release_authority"] is False
    assert registry["postcommit_source_candidate"]["externally_accepted_operative_commit"] is None
    assert registry["current_operative"]["admitted"] is False


# PCR Nov08 exact isolated PR review branch: PURE synthetic GitHub event checks.
# These values are deliberately NOT cryptographic issuer/operative proof.

REVIEW_PR_NUMBER = 91
REVIEW_HEAD_SHA = "b" * 40
REVIEW_MERGE_SHA = "c" * 40


def review_pr_payload():
    return {
        "number": REVIEW_PR_NUMBER,
        "repository": {"full_name": GITHUB_REPOSITORY},
        "pull_request": {
            "number": REVIEW_PR_NUMBER,
            "head": {
                "ref": EXACT_REVIEW_BRANCH, "sha": REVIEW_HEAD_SHA,
                "repo": {"full_name": GITHUB_REPOSITORY},
            },
            "base": {
                "ref": SOURCE_BRANCH, "sha": CANDIDATE_HEAD,
                "repo": {"full_name": GITHUB_REPOSITORY},
            },
        },
    }


def review_context(**overrides):
    context = simulated_committed_context(
        actual_head=REVIEW_MERGE_SHA, event_sha=REVIEW_MERGE_SHA,
        expected_sha=REVIEW_MERGE_SHA, branch=EXACT_REVIEW_BRANCH,
        event_name="pull_request", base_branch=SOURCE_BRANCH,
        github_ref="refs/pull/91/merge", event_payload=review_pr_payload(),
        pr_head_is_merge_ancestor=True,
    )
    context.update(overrides)
    return context


def test_review_branch_exact_pr_positive_source_only():
    check = validate_committed_checkout_binding(**review_context())
    assert check["scoped_review_pr"] is True
    assert check["PR_base"] == SOURCE_BRANCH
    assert check["source_commit_bound"] == REVIEW_MERGE_SHA
    assert check["candidate_only"] is True
    assert check["independent_operative_release_approved"] is False


@pytest.mark.parametrize("bad,reason", [
    ({"event_name": "push"}, "REVIEW_BRANCH_ONLY_FOR_PULL_REQUEST"),
    ({"event_name": "workflow_dispatch"}, "REVIEW_BRANCH_ONLY_FOR_PULL_REQUEST"),
    ({"event_name": "pull_request_target"}, "WRONG_GITHUB_EVENT_TYPE"),
    ({"branch": "review/attacker-feature"}, "WRONG_COMMITTED_SOURCE_BRANCH"),
    ({"base_branch": "main"}, "GITHUB_PR_EVENT_REF_MISMATCH"),
    ({"event_payload": None}, "MISSING_GITHUB_PR_EVENT_PAYLOAD"),
    ({"github_ref": "refs/pull/92/merge"}, "WRONG_GITHUB_PR_MERGE_REF"),
    ({"event_sha": "d" * 40}, "WRONG_COMMITTED_SOURCE_SHA"),
    ({"expected_sha": "d" * 40}, "WRONG_COMMITTED_SOURCE_SHA"),
    ({"actual_head": "e" * 40}, "WRONG_COMMITTED_SOURCE_SHA"),
    ({"parent_is_ancestor": False}, "PARENT_NOT_VERIFIED_ANCESTOR"),
    ({"pr_head_is_merge_ancestor": False},
     "PR_HEAD_NOT_ANCESTOR_OF_CHECKED_OUT_MERGE_SHA"),
    ({"clean": False}, "DIRTY_COMMITTED_CHECKOUT"),
    ({"required_files_tracked": False}, "MISSING_REQUIRED_TRACKED_CANDIDATE_FILES"),
    ({"repository": "attacker/xbos"}, "WRONG_COMMITTED_EVENT_REPOSITORY"),
])
def test_review_branch_wrong_origin_base_commit_or_event_denied(bad, reason):
    denies(reason, validate_committed_checkout_binding, **review_context(**bad))


@pytest.mark.parametrize("mutation,reason", [
    ("root_repo", "WRONG_PR_EVENT_REPOSITORY"),
    ("external_head_fork", "EXTERNAL_PR_FORK_OR_UNTRUSTED_SOURCE"),
    ("external_base", "EXTERNAL_PR_FORK_OR_UNTRUSTED_SOURCE"),
    ("wrong_head", "GITHUB_PR_EVENT_REF_MISMATCH"),
    ("wrong_base", "GITHUB_PR_EVENT_REF_MISMATCH"),
    ("wrong_base_sha", "WRONG_PR_REVIEW_BASE"),
    ("missing_base_sha", "MISSING_OR_INVALID_PR_BASE_SHA"),
    ("wrong_number", "MISSING_OR_WRONG_PR_NUMBER"),
    ("wrong_head_sha", "MISSING_OR_INVALID_PR_HEAD_SHA"),
])
def test_review_branch_forged_event_payload_denied(mutation, reason):
    payload = review_pr_payload()
    if mutation == "root_repo":
        payload["repository"]["full_name"] = "attacker/xbos"
    elif mutation == "external_head_fork":
        payload["pull_request"]["head"]["repo"]["full_name"] = "attacker/xbos"
    elif mutation == "external_base":
        payload["pull_request"]["base"]["repo"]["full_name"] = "attacker/xbos"
    elif mutation == "wrong_head":
        payload["pull_request"]["head"]["ref"] = "review/attacker"
    elif mutation == "wrong_base":
        payload["pull_request"]["base"]["ref"] = "main"
    elif mutation == "wrong_base_sha":
        payload["pull_request"]["base"]["sha"] = "f" * 40
    elif mutation == "missing_base_sha":
        payload["pull_request"]["base"]["sha"] = None
    elif mutation == "wrong_number":
        payload["number"] = 92
    elif mutation == "wrong_head_sha":
        payload["pull_request"]["head"]["sha"] = "bad"
    denies(reason, validate_committed_checkout_binding,
           **review_context(event_payload=payload))


def test_review_branch_missing_number_denied():
    p = review_pr_payload()
    p["pull_request"]["number"] = None
    denies("MISSING_OR_WRONG_PR_NUMBER",
           validate_committed_checkout_binding,
           **review_context(event_payload=p))


def test_review_branch_pr_head_sha_is_not_merge_sha():
    p = review_pr_payload()
    p["pull_request"]["head"]["sha"] = REVIEW_MERGE_SHA
    denies("PR_HEAD_WRONGLY_USED_AS_MERGE_SHA",
           validate_committed_checkout_binding,
           **review_context(event_payload=p))


def test_pure_pr_event_payload_review_exact_positive():
    assert validate_pr_event_payload(
        payload=review_pr_payload(), event_head_ref=EXACT_REVIEW_BRANCH,
        event_base_ref=SOURCE_BRANCH, event_merge_ref="refs/pull/91/merge",
        runner_repository=GITHUB_REPOSITORY, exact_review=True,
    ) == REVIEW_HEAD_SHA


def test_original_source_and_main_push_still_allowed():
    for original_branch in (SOURCE_BRANCH, "main"):
        for event in ("push", "workflow_dispatch"):
            check = validate_committed_checkout_binding(
                **simulated_committed_context(branch=original_branch,
                                               event_name=event)
            )
            assert check["candidate_only"] is True
            assert check["scoped_review_pr"] is False


def test_review_branch_non_pr_push_and_dispatch_still_denied():
    for event in ("push", "workflow_dispatch"):
        denies("REVIEW_BRANCH_ONLY_FOR_PULL_REQUEST",
               validate_committed_checkout_binding,
               **review_context(event_name=event))


def test_registry_rejects_review_pr_wildcard(registry):
    registry["postcommit_source_candidate"]["isolated_review_pull_request_gate"]["allow_unrecognized_pr_branches"] = True
    denies("REVIEW_PR_WILDCARD_DENIED", validate_registry, registry)


def test_registry_rejects_unpinned_review_base(registry):
    registry["postcommit_source_candidate"]["isolated_review_pull_request_gate"]["exact_base_sha"] = "f" * 40
    denies("REVIEW_PR_BASE_CHANGED", validate_registry, registry)


def test_registry_rejects_false_review_operative_proof(registry):
    registry["postcommit_source_candidate"]["isolated_review_pull_request_gate"]["operative_issuer_signer_proof"] = {"self_signed": True}
    denies("REVIEW_PR_FALSE_OPERATIVE_PROMOTION", validate_registry, registry)


def test_repeated_stale_github_merge_event_sha_denied():
    denies("WRONG_COMMITTED_SOURCE_SHA",
           validate_committed_checkout_binding,
           **review_context(event_sha="a" * 40))


def test_exact_review_branch_keeps_parent_and_head_ancestor_constraints():
    denies("PARENT_NOT_VERIFIED_ANCESTOR",
           validate_committed_checkout_binding,
           **review_context(parent_is_ancestor=False))
    denies("PR_HEAD_NOT_ANCESTOR_OF_CHECKED_OUT_MERGE_SHA",
           validate_committed_checkout_binding,
           **review_context(pr_head_is_merge_ancestor=False))
