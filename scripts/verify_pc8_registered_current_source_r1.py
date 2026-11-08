"""Route A — LOCAL nonoperative PC8 current-source companion verifier.

Historical PC1–PC8 manifests and the frozen canonical verifier are immutable.
The companion source is a candidate, not an operative issuer, CI or deploy gate.
No JSON boolean, CLI flag, or local source file can make this release operative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.release_integrity import ReleaseIntegrityError, verify_latest_release
from scripts.verify_xcomp_pc8_postrelease_delta import (
    CANDIDATE_HEAD, HISTORIC, C2_COMMIT, ACCEPTED_LATER_SEALS,
    CandidateIntegrityDenied, _canonical, _git, _blob, _sha, _seal_digest, inspect,
)

COMPANION_ID = "XCOMP_PLATFORM_CORE_PC8_CURRENT_SOURCE_COMPANION_R1"
REGISTRY_REL = "contracts/platform/v1/pc8_current_source_companion_registry_r1.json"
PREDECESSOR_REL = "contracts/platform/v1/pc8_postrelease_cumulative_successor_r1.json"
MANIFEST_REL = "contracts/platform/v1/pc8_release_manifest.json"
SOURCE_BRANCH = "platform/neutral-vnext-vn2-pc0-discovery-successor"
SOURCE_GRANT_SHA = "5175a09235b1cbb9ba3801a2d95c28989bb32549e94e2efa4de82c453413f2af"
PCR_ROOT_SHA = "cd0c62360ee3628b6e988adeba618fea962a48846542f25ae28e95f7110594f6"
PREDECESSOR_SHA = "bb3530847975ba2ac29f9116c1cc02d0ce8bf4fc2db727df75dc16321e1c33a8"
MANIFEST_SHA = "d94b0316c5c5205e3b314595f466935861cfb9851afc1d07f40a5aeaa7a6161b"
VERIFIER_RAW_SHA = "6ded92f7aa0fc0b3db5115ff5094b9e39b521a0d1f05d9ee102b96d668ab0ec4"
OWNER_FINGERPRINT = "SHA256:NLjmYKfcALv6JRIO42ouo7DO4CBfWGOJg1aHjhmnySc"
REQUIRED_CHECK = "xcomp-pc8-registered-current-source"

OLD_SIX = (
    PREDECESSOR_REL,
    "scripts/verify_pc8_postrelease_cumulative_successor_r1.py",
    "scripts/verify_xcomp_pc8_postrelease_delta.py",
    "tests/contracts/test_pc8_postrelease_cumulative_successor_r1.py",
    "tests/contracts/test_xcomp_n_wave1_authorized_http_seam.py",
    "tests/contracts/test_xcomp_pc8_postrelease_delta.py",
)
EXACT_FIVE = (
    REGISTRY_REL,
    "scripts/verify_pc8_registered_current_source_r1.py",
    "tests/contracts/test_pc8_registered_current_source_r1.py",
    "XBOS_PC8_CURRENT_SOURCE_RUN_ACCEPTANCE.cmd",
    ".github/workflows/xcomp-pc8-registered-current-source.yml",
)
EXPECTED_STATUS = frozenset("?? " + path for path in OLD_SIX + EXACT_FIVE)
COMMITTED_REQUIRED_FILES = OLD_SIX + EXACT_FIVE
GITHUB_REPOSITORY = "joelkamda/xbos"
ALLOWED_COMMITTED_EVENTS = frozenset(("pull_request", "push", "workflow_dispatch"))
ALLOWED_COMMITTED_BRANCHES = frozenset((SOURCE_BRANCH, "main"))
EXACT_REVIEW_BRANCH = "review/xcomp-pc8-route-a-11file-20261108"
REVIEW_PR_BASE = SOURCE_BRANCH


class CurrentReleaseDenied(RuntimeError):
    """Fail-closed local source or operative release admission."""


def require(condition: bool, failure: str) -> None:
    if not condition:
        raise CurrentReleaseDenied(failure)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(raw: bytes, relative: str) -> str:
    return digest(_canonical(raw, relative))


def require_frozen(local: bytes, accepted_git_blob: bytes, rel: str) -> None:
    require(
        _canonical(local, rel) == _canonical(accepted_git_blob, rel),
        "FROZEN_MANIFEST_OR_VERIFIER_MUTATION=" + rel,
    )


def check_source_prestate(root: Path = ROOT) -> tuple[str, str]:
    head = _git("rev-parse", "HEAD", root=root).decode().strip()
    branch = _git("branch", "--show-current", root=root).decode().strip()
    require(head == CANDIDATE_HEAD, "WRONG_SOURCE_HEAD")
    require(branch == SOURCE_BRANCH, "WRONG_SOURCE_BRANCH")
    for ancestor in (HISTORIC, C2_COMMIT):
        _git("merge-base", "--is-ancestor", ancestor, head, root=root)
    require(not _git("diff", "--name-only", root=root).strip(), "DIRTY_TRACKED_SOURCE")
    require(not _git("diff", "--cached", "--name-only", root=root).strip(),
            "DIRTY_STAGED_SOURCE")
    actual_status = set(
        _git("status", "--porcelain=v1", "--untracked-files=all", root=root)
        .decode().splitlines()
    )
    require(actual_status == EXPECTED_STATUS,
            "UNAPPROVED_WORKTREE_PATH_SET=" + repr(sorted(actual_status ^ EXPECTED_STATUS)))
    return head, branch


def validate_registry(record: dict) -> None:
    """Validate nonoperative companion; registration by local flag is forbidden."""
    require(isinstance(record, dict), "MALFORMED_COMPANION_REGISTRY")
    require(record.get("schema") == "XCOMP_PC8_ROUTE_A_CURRENT_SOURCE_COMPANION_REGISTRY_R1",
            "BAD_REGISTRY_SCHEMA")
    require(record.get("companion_id") == COMPANION_ID, "BAD_COMPANION_IDENTITY")
    require(record.get("class") == "NON_NUMBERED_POST_PC8_CURRENT_SOURCE_COMPANION",
            "UNAPPROVED_PC9_CLASS")
    require(record.get("status") == "PROPOSED_NONOPERATIVE", "UNAUTHORIZED_STATUS_PROMOTION")
    for key in ("registered", "active"):
        require(record.get(key) is False, "UNAUTHORIZED_LOCAL_SELF_ACTIVATION=" + key)
    require(record.get("release_sequence") is None, "INVENTED_RELEASE_SEQUENCE")
    auth = record.get("authority") or {}
    require(auth.get("pcr_source_grant_sha256") == SOURCE_GRANT_SHA, "GRANT_NOT_PINNED")
    require(auth.get("pcr_root_sha256") == PCR_ROOT_SHA, "PCR_ROOT_NOT_PINNED")
    hist = record.get("historical") or {}
    require(hist.get("git_commit") == HISTORIC, "HISTORICAL_COMMIT_DRIFT")
    require(hist.get("manifest_path") == MANIFEST_REL, "HISTORICAL_MANIFEST_DRIFT")
    require(hist.get("canonical_manifest_sha256") == MANIFEST_SHA, "HISTORICAL_SHA_DRIFT")
    require(hist.get("frozen_manifest_count") == 8, "HISTORICAL_MANIFEST_COUNT")
    require(hist.get("artifact_count") == 40, "HISTORICAL_ARTIFACT_COUNT")
    require(hist.get("original_verifier_path") == "core/platform/release_integrity.py",
            "ORIGINAL_VERIFIER_PATH_DRIFT")
    require(hist.get("original_verifier_sha256_raw") == VERIFIER_RAW_SHA,
            "ORIGINAL_VERIFIER_HASH_DRIFT")
    prior = record.get("current_predecessor") or {}
    require(prior.get("git_head") == CANDIDATE_HEAD, "PREDECESSOR_HEAD_DRIFT")
    require(prior.get("branch") == SOURCE_BRANCH, "PREDECESSOR_BRANCH_DRIFT")
    require(prior.get("candidate_path") == PREDECESSOR_REL, "PREDECESSOR_PATH_DRIFT")
    require(prior.get("candidate_sha256_raw") == PREDECESSOR_SHA, "PREDECESSOR_HASH_DRIFT")
    require(prior.get("unchanged_historical_artifacts") == 35
            and prior.get("exact_sealed_descendants") == 5, "UNAPPROVED_SIXTH_DESCENDANT")
    issuer = record.get("issuer") or {}
    require(issuer.get("proposed_source_owner") == "joelkamda"
            and issuer.get("verified_source_owner_public_key_fingerprint") == OWNER_FINGERPRINT,
            "SOURCE_OWNER_IDENTITY_MISMATCH")
    require(issuer.get("qualification") == "ATTENDED_SOURCE_ENGINEERING_ONLY",
            "OWNER_CUSTODY_OVERCLAIM")
    require(issuer.get("operative_issuer_trust_anchor") is None
            and issuer.get("operative_attestation") is None
            and issuer.get("independent_operative_signing_custody") is False,
            "FORGED_OPERATIVE_ISSUER")
    operative = record.get("current_operative") or {}
    for name in (
        "accepted_git_head", "accepted_registry_sha256",
        "release_owner_independent_operative_signature",
        "pcr_independent_release_signature", "required_check_attestation",
        "protected_branch_rule_receipt", "deploy_same_commit_receipt",
    ):
        require(operative.get(name) is None, "FORGED_OPERATIVE_EVIDENCE=" + name)
    require(operative.get("admitted") is False, "FORGED_OPERATIVE_ADMISSION")
    require(operative.get("required_github_check_name") == REQUIRED_CHECK,
            "WRONG_REQUIRED_CI_CHECK")
    postcommit = record.get("postcommit_source_candidate") or {}
    require(postcommit.get("mode") ==
            "GITHUB_EVENT_BOUND_COMMITTED_SOURCE_PREFLIGHT_NOT_OPERATIVE",
            "POSTCOMMIT_MODE_NOT_NONOPERATIVE")
    require(postcommit.get("parent_before_new_five_files") == CANDIDATE_HEAD,
            "POSTCOMMIT_PREDECESSOR_CHANGED")
    require(postcommit.get("event_repository") == GITHUB_REPOSITORY,
            "POSTCOMMIT_REPOSITORY_CHANGED")
    require(set(postcommit.get("event_allowed_types", ())) == ALLOWED_COMMITTED_EVENTS,
            "POSTCOMMIT_EVENT_SCOPE_CHANGED")
    require(set(postcommit.get("event_allowed_branches", ())) == ALLOWED_COMMITTED_BRANCHES,
            "POSTCOMMIT_BRANCH_SCOPE_CHANGED")
    pr_gate = postcommit.get("isolated_review_pull_request_gate") or {}
    require(pr_gate.get("schema") == "XCOMP_ROUTE_A_SINGLE_REVIEW_BRANCH_GITHUB_PR_SCOPE_R0",
            "REVIEW_PR_GATE_SCHEMA_MISMATCH")
    require(pr_gate.get("review_head_ref") == EXACT_REVIEW_BRANCH
            and pr_gate.get("accepted_event") == "pull_request",
            "REVIEW_PR_SCOPE_CHANGED")
    require(pr_gate.get("exact_base_ref") == REVIEW_PR_BASE
            and pr_gate.get("exact_base_sha") == CANDIDATE_HEAD,
            "REVIEW_PR_BASE_CHANGED")
    require(pr_gate.get("exact_source_repository") == GITHUB_REPOSITORY,
            "REVIEW_PR_REPOSITORY_CHANGED")
    for key in ("head_repository_must_equal_base_repository",
                "github_event_path_payload_required",
                "github_ref_must_match_pr_number_and_merge",
                "github_head_ref_and_base_ref_must_match_payload",
                "github_sha_must_equal_checked_out_pr_merge_sha",
                "pr_head_commit_sha_must_be_merge_ancestor",
                "original_parent_sha_must_be_merge_ancestor"):
        require(pr_gate.get(key) is True, "REVIEW_PR_SECURITY_DISABLED=" + key)
    require(pr_gate.get("push_or_manual_dispatch_to_review_branch") == "DENY"
            and pr_gate.get("allow_unrecognized_pr_branches") is False
            and pr_gate.get("accepted_source_and_main_branch_push_or_dispatch") == "PRESERVED",
            "REVIEW_PR_WILDCARD_DENIED")
    require(pr_gate.get("proof_grade") ==
            "ONLY_GITHUB_EVENT_BOUND_SOURCE_INTEGRITY_NOT_OPERATIVE_RELEASE"
            and pr_gate.get("operative_issuer_signer_proof") is None
            and pr_gate.get("activation_status") == "SOURCE_CANDIDATE_NOT_REGISTERED",
            "REVIEW_PR_FALSE_OPERATIVE_PROMOTION")
    for name in ("external_event_commit_required", "require_parent_ancestor",
                 "require_exact_event_checkout_commit", "require_git_clean",
                 "require_all_eleven_past_and_new_files_tracked_and_match_checkout",
                 "require_frozen_pc8_and_sealed_five"):
        require(postcommit.get(name) is True, "POSTCOMMIT_SECURITY_DISABLED=" + name)
    require(postcommit.get("postcommit_source_integrity_is_release_authority") is False
            and postcommit.get("status") == "NOT_COMMISSIONED",
            "FALSE_POSTCOMMIT_OPERATIVE_PROMOTION")
    for name in ("externally_accepted_operative_commit",
                 "separately_verified_independent_owner_controller_release_proof",
                 "protected_required_branch_check_receipt", "same_commit_deploy_admission"):
        require(postcommit.get(name) is None, "FORGED_POSTCOMMIT_AUTHORITY=" + name)
    sec = record.get("security") or {}
    require(sec.get("registry_local_flags_cannot_grant_authority") is True
            and sec.get("canonical_legacy_latest8_not_current_authority") is True,
            "UNSAFE_LEGACY_FALLBACK")


def compare_artifact_sets(
    historical: dict[str, str], historical_observed: dict[str, str],
    current: dict[str, str], sealed: dict[str, str],
) -> dict:
    """Pure exact historical/current verification: no sixth or wildcard."""
    require(len(historical) == 40, "HISTORICAL_40_REQUIRED")
    require(set(historical) == set(historical_observed) == set(current),
            "HISTORICAL_ARTIFACT_SET_CHANGED")
    for path, expected in historical.items():
        require(historical_observed[path] == expected,
                "HISTORICAL_ARTIFACT_CORRUPT=" + path)
    changed = {p for p in historical if current[p] != historical[p]}
    require(changed == set(ACCEPTED_LATER_SEALS), "UNSEALED_FIFTH_SIXTH_OR_SEVENTH_DESCENDANT")
    require(set(sealed) == changed, "MISSING_OR_EXTRA_SOURCE_SEAL")
    for path in changed:
        require(current[path] == sealed[path] == ACCEPTED_LATER_SEALS[path][1],
                "SOURCE_SEAL_MISMATCH=" + path)
    return {"historical": 40, "unchanged": 35, "sealed_descendants": 5}


def require_attestation_bindings(
    proof: dict, *, expected_head: str = CANDIDATE_HEAD,
    required_check: str = REQUIRED_CHECK,
) -> None:
    """Structural denial gate only; not cryptographic or operative acceptance."""
    require(isinstance(proof, dict), "MISSING_EXTERNAL_OPERATIVE_PROOF")
    require(proof.get("companion_id") == COMPANION_ID, "WRONG_EXTERNAL_RELEASE_ID")
    require(proof.get("registered_git_head") == expected_head, "WRONG_ATTESTED_HEAD")
    require(proof.get("required_ci_status") == required_check, "WRONG_REQUIRED_CI_STATUS")
    require(proof.get("ci_verified_source_head") == expected_head, "CI_SOURCE_HEAD_MISMATCH")
    require(proof.get("deploy_verified_source_head") == expected_head, "DEPLOY_SOURCE_HEAD_MISMATCH")
    require(proof.get("branch_protection_required") is True,
            "MISSING_REQUIRED_BRANCH_PROTECTION")
    require(proof.get("signature_revoked") is False, "REVOKED_OR_REPLAYED_PROOF")
    require(isinstance(proof.get("issuance_nonce"), str)
            and len(proof["issuance_nonce"]) >= 16, "MISSING_OR_REPLAYED_NONCE")
    # This function only checks shape and binding. It cannot supply trusted
    # signer custody, GitHub branch policy or same-commit deploy attestations.
    # No branch of this module upgrades a local proof to OPERATIVE.


def validate_pr_event_payload(
    *, payload: dict | None, event_head_ref: str, event_base_ref: str | None,
    event_merge_ref: str | None, runner_repository: str,
    exact_review: bool,
) -> str:
    """Validate actual GH PR event fields, never operative signing authority."""
    require(isinstance(payload, dict), "MISSING_GITHUB_PR_EVENT_PAYLOAD")
    root_repo = payload.get("repository") or {}
    require(isinstance(root_repo, dict) and
            root_repo.get("full_name") == GITHUB_REPOSITORY
            and runner_repository == GITHUB_REPOSITORY,
            "WRONG_PR_EVENT_REPOSITORY")
    pr = payload.get("pull_request") or {}
    require(isinstance(pr, dict), "MISSING_PR_EVENT_IDENTITY")
    number = pr.get("number")
    require(isinstance(number, int) and not isinstance(number, bool)
            and number > 0 and payload.get("number") == number,
            "MISSING_OR_WRONG_PR_NUMBER")
    pr_head, pr_base = pr.get("head") or {}, pr.get("base") or {}
    require(isinstance(pr_head, dict) and isinstance(pr_base, dict),
            "MALFORMED_PR_HEAD_OR_BASE")
    head_repo, base_repo = pr_head.get("repo") or {}, pr_base.get("repo") or {}
    require(isinstance(head_repo, dict) and isinstance(base_repo, dict)
            and head_repo.get("full_name") == GITHUB_REPOSITORY
            and base_repo.get("full_name") == GITHUB_REPOSITORY,
            "EXTERNAL_PR_FORK_OR_UNTRUSTED_SOURCE")
    require(pr_head.get("ref") == event_head_ref
            and pr_base.get("ref") == event_base_ref,
            "GITHUB_PR_EVENT_REF_MISMATCH")
    require(event_merge_ref == f"refs/pull/{number}/merge",
            "WRONG_GITHUB_PR_MERGE_REF")
    head_sha, base_sha = pr_head.get("sha"), pr_base.get("sha")
    require(isinstance(head_sha, str) and
            re.fullmatch(r"[0-9a-f]{40}", head_sha) is not None,
            "MISSING_OR_INVALID_PR_HEAD_SHA")
    require(isinstance(base_sha, str) and
            re.fullmatch(r"[0-9a-f]{40}", base_sha) is not None,
            "MISSING_OR_INVALID_PR_BASE_SHA")
    if exact_review:
        require(pr_head.get("ref") == EXACT_REVIEW_BRANCH,
                "UNAUTHORIZED_PR_REVIEW_HEAD")
        require(pr_base.get("ref") == REVIEW_PR_BASE
                and base_sha == CANDIDATE_HEAD,
                "WRONG_PR_REVIEW_BASE")
    return head_sha


def validate_committed_checkout_binding(
    *, actual_head: str, event_sha: str | None, expected_sha: str | None,
    repository: str, event_name: str, branch: str, parent_is_ancestor: bool,
    clean: bool, required_files_tracked: bool,
    event_payload: dict | None = None, base_branch: str | None = None,
    github_ref: str | None = None, pr_head_is_merge_ancestor: bool = False,
) -> dict:
    """Pure simulated GH event/source check; never operative release proof."""
    for name, value in (("ACTUAL", actual_head), ("EVENT", event_sha),
                        ("EXPECTED", expected_sha)):
        require(isinstance(value, str) and
                re.fullmatch(r"[0-9a-f]{40}", value) is not None,
                "MISSING_OR_MALFORMED_" + name + "_SOURCE_SHA")
    require(actual_head == event_sha == expected_sha, "WRONG_COMMITTED_SOURCE_SHA")
    require(actual_head != CANDIDATE_HEAD, "UNCHANGED_PRECOMMIT_SOURCE_HEAD")
    require(repository == GITHUB_REPOSITORY, "WRONG_COMMITTED_EVENT_REPOSITORY")
    require(event_name in ALLOWED_COMMITTED_EVENTS, "WRONG_GITHUB_EVENT_TYPE")
    review = branch == EXACT_REVIEW_BRANCH
    if review:
        require(event_name == "pull_request", "REVIEW_BRANCH_ONLY_FOR_PULL_REQUEST")
    else:
        require(branch in ALLOWED_COMMITTED_BRANCHES, "WRONG_COMMITTED_SOURCE_BRANCH")
    if event_name == "pull_request":
        pr_sha = validate_pr_event_payload(
            payload=event_payload, event_head_ref=branch,
            event_base_ref=base_branch, event_merge_ref=github_ref,
            runner_repository=repository, exact_review=review,
        )
        require(pr_head_is_merge_ancestor is True,
                "PR_HEAD_NOT_ANCESTOR_OF_CHECKED_OUT_MERGE_SHA")
        require(pr_sha != actual_head, "PR_HEAD_WRONGLY_USED_AS_MERGE_SHA")
    require(parent_is_ancestor is True, "PARENT_NOT_VERIFIED_ANCESTOR")
    require(clean is True, "DIRTY_COMMITTED_CHECKOUT")
    require(required_files_tracked is True, "MISSING_REQUIRED_TRACKED_CANDIDATE_FILES")
    return {
        "source_commit_bound": actual_head,
        "source_branch": branch,
        "source_parent_commit": CANDIDATE_HEAD,
        "repository": repository,
        "event_type": event_name,
        "scoped_review_pr": review,
        "PR_base": base_branch if event_name == "pull_request" else None,
        "candidate_only": True,
        "independent_operative_release_approved": False,
    }


def verify_committed_preflight(
    root: Path = ROOT, *, expected_source_sha: str | None = None,
) -> dict:
    """A distinct FUTURE GitHub CI source preflight; never an operative gate.

    No locally spoofable CLI arg, environment variable, or candidate registry
    can establish independent release signer, required branch rule or deploy.
    """
    require(os.environ.get("GITHUB_ACTIONS") == "true",
            "MISSING_GITHUB_RUNNER_SOURCE_CONTEXT")
    head = _git("rev-parse", "HEAD", root=root).decode().strip()
    status = _git("status", "--porcelain=v1", "--untracked-files=all", root=root)
    require(not status.strip(), "COMMITTED_WORKTREE_NOT_CLEAN")
    require(not _git("diff", "--cached", "--name-only", root=root).strip(),
            "COMMITTED_STAGED_DIFFERENCE")
    required_tracked = True
    for rel in COMMITTED_REQUIRED_FILES:
        try:
            _git("ls-files", "--error-unmatch", "--", rel, root=root)
        except CandidateIntegrityDenied:
            required_tracked = False
            break
        require((root / rel).is_file(), "COMMITTED_SOURCE_MISSING=" + rel)
        require(_canonical((root / rel).read_bytes(), rel) ==
                _canonical(_blob(head, rel, root), rel),
                "COMMITTED_SOURCE_WORKTREE_DRIFT=" + rel)
    parent_ancestor = False
    try:
        _git("merge-base", "--is-ancestor", CANDIDATE_HEAD, head, root=root)
        parent_ancestor = True
    except CandidateIntegrityDenied:
        parent_ancestor = False
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    branch = (os.environ.get("GITHUB_HEAD_REF") or
              os.environ.get("GITHUB_REF_NAME") or "")
    base_branch = os.environ.get("GITHUB_BASE_REF")
    payload = None
    pr_head_is_merge_ancestor = False
    if event == "pull_request":
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        require(isinstance(event_path, str) and bool(event_path),
                "MISSING_GITHUB_EVENT_PATH")
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf8"))
        except (OSError, ValueError) as exc:
            raise CurrentReleaseDenied("UNREADABLE_GITHUB_PR_EVENT_PAYLOAD") from exc
        pr_sha = validate_pr_event_payload(
            payload=payload, event_head_ref=branch,
            event_base_ref=base_branch,
            event_merge_ref=os.environ.get("GITHUB_REF"),
            runner_repository=os.environ.get("GITHUB_REPOSITORY", ""),
            exact_review=(branch == EXACT_REVIEW_BRANCH),
        )
        try:
            _git("merge-base", "--is-ancestor", pr_sha, head, root=root)
            pr_head_is_merge_ancestor = True
        except CandidateIntegrityDenied:
            pr_head_is_merge_ancestor = False
    validate_committed_checkout_binding(
        actual_head=head, event_sha=os.environ.get("GITHUB_SHA"),
        expected_sha=expected_source_sha,
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        event_name=event, branch=branch, parent_is_ancestor=parent_ancestor,
        clean=not status.strip(), required_files_tracked=required_tracked,
        event_payload=payload, base_branch=base_branch,
        github_ref=os.environ.get("GITHUB_REF"),
        pr_head_is_merge_ancestor=pr_head_is_merge_ancestor,
    )

    # No imported historical PC8 verifier is modified or bypassed.
    record = json.loads((root / REGISTRY_REL).read_text(encoding="utf8"))
    validate_registry(record)
    require(digest((root / PREDECESSOR_REL).read_bytes()) == PREDECESSOR_SHA,
            "TAMPERED_COMMITTED_PREDECESSOR")
    require(digest((root / "core/platform/release_integrity.py").read_bytes())
            == VERIFIER_RAW_SHA, "FROZEN_PC8_VERIFIER_CHANGED")
    for number in range(1, 9):
        rel = f"contracts/platform/v1/pc{number}_release_manifest.json"
        require_frozen((root / rel).read_bytes(), _blob(HISTORIC, rel, root), rel)
        require_frozen((root / rel).read_bytes(), _blob(head, rel, root), rel)
    require(canonical_hash((root / MANIFEST_REL).read_bytes(), MANIFEST_REL) ==
            MANIFEST_SHA, "COMMITTED_PC8_MANIFEST_DRIFT")
    manifest = json.loads(_blob(HISTORIC, MANIFEST_REL, root))
    rows = manifest["artifacts"]
    expected = {row["path"]: row["sha256"] for row in rows}
    require(len(rows) == len(expected) == 40, "COMMITTED_PC8_40_ARTIFACT_SET_CHANGED")
    historic, current, seals = {}, {}, {}
    for rel in expected:
        historic[rel] = _sha(_blob(HISTORIC, rel, root), rel)
        file_bytes = (root / rel).read_bytes()
        require_frozen(file_bytes, _blob(head, rel, root), rel)
        current[rel] = _sha(file_bytes, rel)
    for rel, (name, accepted_digest) in ACCEPTED_LATER_SEALS.items():
        seal_rel = "contracts/platform/v1/" + name
        seal_bytes = (root / seal_rel).read_bytes()
        require_frozen(seal_bytes, _blob(head, seal_rel, root), seal_rel)
        value = _seal_digest(rel, json.loads(seal_bytes), name)
        require(value == accepted_digest, "COMMITTED_SOURCE_SEAL_CHANGED=" + rel)
        seals[rel] = value
    counts = compare_artifact_sets(expected, historic, current, seals)
    try:
        verify_latest_release(root)
    except ReleaseIntegrityError as exc:
        require(str(exc) == "PC8 release manifest mismatch=core/platform/architecture_contract.py",
                "UNEXPECTED_HISTORICAL_LATEST8_RESULT")
    else:
        raise CurrentReleaseDenied("HISTORICAL_LATEST8_INCORRECTLY_ADMITTED_AS_CURRENT")

    return {
        "status": "PASS_COMMITTED_SOURCE_INTEGRITY_PREFLIGHT_ONLY",
        "current_source_sha": head, "source_branch": branch,
        "historical_pc8_artifacts": counts["historical"],
        "frozen_manifests": 8, "unchanged_pc8": counts["unchanged"],
        "sealed_descendants": counts["sealed_descendants"],
        "source_commit_bound_to_github_event": True,
        "source_candidate_only": True,
        "registered": False, "operative_release": False,
        "required_branch_ci_rule_proven": False,
        "independent_release_issuer_proven": False,
        "deployment_same_commit_proven": False,
    }


def verify_local_candidate(root: Path = ROOT) -> dict:
    head, branch = check_source_prestate(root)
    record = json.loads((root / REGISTRY_REL).read_text(encoding="utf-8"))
    validate_registry(record)
    require(digest((root / PREDECESSOR_REL).read_bytes()) == PREDECESSOR_SHA,
            "TAMPERED_PREDECESSOR_SOURCE")
    require(digest((root / "core/platform/release_integrity.py").read_bytes())
            == VERIFIER_RAW_SHA, "FROZEN_PC8_VERIFIER_CHANGED")
    for number in range(1, 9):
        rel = f"contracts/platform/v1/pc{number}_release_manifest.json"
        require_frozen((root / rel).read_bytes(), _blob(HISTORIC, rel, root), rel)
        require_frozen((root / rel).read_bytes(), _blob(head, rel, root), rel)
    require(canonical_hash((root / MANIFEST_REL).read_bytes(), MANIFEST_REL)
            == MANIFEST_SHA, "PC8_MANIFEST_FINGERPRINT_DRIFT")

    pc8 = json.loads(_blob(HISTORIC, MANIFEST_REL, root))
    rows = pc8["artifacts"]
    expected = {entry["path"]: entry["sha256"] for entry in rows}
    require(len(rows) == len(expected) == 40, "FROZEN_PC8_DUPLICATE_OR_MISSING_ARTIFACT")
    old, current, seals = {}, {}, {}
    for rel in expected:
        old[rel] = _sha(_blob(HISTORIC, rel, root), rel)
        local = (root / rel).read_bytes()
        require_frozen(local, _blob(head, rel, root), rel)
        current[rel] = _sha(local, rel)
    # Existing accepted seals and source are verified by the predecessor's
    # frozen-aware independent inspect(), not trusted merely from this registry.
    baseline = inspect(root)
    require(baseline["historical_pc8_match"] == 40
            and baseline["current_pc8_unchanged"] == 35
            and baseline["current_descendant_count"] == 5,
            "PREDECESSOR_SNAPSHOT_OR_SEAL_DRIFT")
    for rel in ACCEPTED_LATER_SEALS:
        seals[rel] = ACCEPTED_LATER_SEALS[rel][1]
    counts = compare_artifact_sets(expected, old, current, seals)
    try:
        verify_latest_release(root)
    except ReleaseIntegrityError as exc:
        require(str(exc) == "PC8 release manifest mismatch=core/platform/architecture_contract.py",
                "HISTORICAL_CANONICAL_FAILURE_CHANGED")
    else:
        raise CurrentReleaseDenied("LEGACY_CURRENT_HEAD_FALLBACK_SILENTLY_ACCEPTED")

    return {
        "status": "PASS_LOCAL_CURRENT_SOURCE_CANDIDATE_ONLY",
        "proposed_companion_id": COMPANION_ID,
        "source_head": head, "source_branch": branch,
        "historical_pc8_artifacts": counts["historical"],
        "frozen_manifests": 8, "current_pc8_unchanged": counts["unchanged"],
        "sealed_descendants": counts["sealed_descendants"],
        "legacy_verify_latest_release": "EXPECTED_FAIL_UNCHANGED",
        "registered": False, "operative_release": False,
        "required_github_ci_proven": False, "deployment_proven": False,
    }


def verify_operative(root: Path = ROOT, proof: dict | None = None) -> dict:
    # Preserve source-validation first, then ALWAYS deny uncommissioned release.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        verify_committed_preflight(
            root, expected_source_sha=os.environ.get("GITHUB_SHA")
        )
    else:
        verify_local_candidate(root)
    if proof is not None:
        require_attestation_bindings(proof)
    # Fails closed EVEN if an attacker fabricates locally shaped external
    # proofs. A later independently admitted trust/CI implementation is needed.
    raise CurrentReleaseDenied(
        "OPERATIVE_HOLD_INDEPENDENT_ISSUER_REQUIRED_CI_AND_DEPLOY_NOT_COMMISSIONED"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Nonoperative Route A source gate")
    parser.add_argument("--local-candidate", action="store_true")
    parser.add_argument("--committed-preflight", action="store_true")
    parser.add_argument("--operative", action="store_true")
    parser.add_argument("--expected-source-sha")
    args = parser.parse_args()
    if sum((args.local_candidate, args.committed_preflight, args.operative)) != 1:
        parser.error("select exactly one explicit gate mode")
    if args.committed_preflight and not args.expected_source_sha:
        parser.error("--committed-preflight requires --expected-source-sha")
    if args.expected_source_sha and not args.committed_preflight:
        parser.error("unexpected --expected-source-sha outside committed source mode")
    try:
        if args.local_candidate:
            receipt = verify_local_candidate(ROOT)
        elif args.committed_preflight:
            receipt = verify_committed_preflight(
                ROOT, expected_source_sha=args.expected_source_sha
            )
        else:
            receipt = verify_operative(ROOT)
    except (CurrentReleaseDenied, CandidateIntegrityDenied, OSError, ValueError,
            subprocess.CalledProcessError) as exc:
        print(json.dumps({
            "status": "DENIED", "reason": str(exc),
            "operative_release": False,
        }, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
