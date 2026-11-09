"""D1/D2 N additive PC8 post-merge source-integrity bridge (NONOPERATIVE).

Does not edit frozen releases, old PC8 verifier, accepted Route A artifacts,
Git branch policy, or registry. It validates only the pinned merged checkout.
A source match never grants independent operative release or hosted admission.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from core.platform.release_integrity import ReleaseIntegrityError, verify_latest_release
from scripts.verify_xcomp_pc8_postrelease_delta import (
    ACCEPTED_LATER_SEALS, C2_COMMIT, HISTORIC, PC8_PATH,
    CandidateIntegrityDenied, _blob, _canonical, _git, _seal_digest,
    _sha, evaluate_pairs,
)

ROOT = Path(__file__).resolve().parents[1]
MERGED_HEAD = "47842917c102908e61e15318332eb5d55d50094c"
MERGED_BRANCH = "platform/xcomp-n-d1d2-nonoperative-20261109"
INTEGRATION_BRANCH = "platform/xcomp-d1d2-integrated-source-20261109"
PREMERGE_SOURCE = "e89d81d6ef427b88b94e2b78df083d767a12a094"
FROZEN_VERIFIER_RAW_SHA = "6ded92f7aa0fc0b3db5115ff5094b9e39b521a0d1f05d9ee102b96d668ab0ec4"
GITHUB_REPOSITORY = "joelkamda/xbos"


def must(condition: bool, code: str):
    if not condition:
        raise CandidateIntegrityDenied(code)


def validate_proposed_source_event(
    *, commit_sha: str, checked_out_sha: str, branch: str,
    repository: str, event_name: str, proof_nonce: str,
    previously_seen: frozenset[str] = frozenset(),
) -> dict:
    """Pure negative controls only; *not* a substitute for actual GH/PC8 trust."""
    for name, value in (("EVENT_SHA", commit_sha), ("CHECKOUT_SHA", checked_out_sha)):
        must(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
             "INVALID_" + name)
    must(commit_sha == checked_out_sha == MERGED_HEAD, "WRONG_MERGED_SOURCE_SHA")
    must(branch == MERGED_BRANCH, "WRONG_MERGED_SOURCE_BRANCH")
    must(repository == GITHUB_REPOSITORY, "WRONG_SOURCE_REPOSITORY")
    must(event_name == "source_candidate", "UNTRUSTED_GITHUB_EVENT_OR_RELEASE_MODE")
    must(isinstance(proof_nonce, str) and bool(re.fullmatch(r"[a-zA-Z0-9-]{8,64}", proof_nonce)),
         "INVALID_SOURCE_PROOF_NONCE")
    must(proof_nonce not in previously_seen, "REPLAYED_SOURCE_PROOF_NONCE")
    return {
        "source_head": MERGED_HEAD, "source_only": True,
        "operative_release": False, "nonce_is_local_test_only": True,
    }


def inspect(root: Path = ROOT) -> dict:
    head = _git("rev-parse", "HEAD", root=root).decode().strip()
    branch = _git("branch", "--show-current", root=root).decode().strip()
    # A source-only integration commit must descend from the accepted PR4 merge.
    # Requiring equal HEAD would invalidate every properly committed successor.
    # Historical manifests, sealed descendants and the frozen checker are
    # independently byte/canonical-checked below; no release is promoted.
    try:
        _git("merge-base", "--is-ancestor", MERGED_HEAD, head, root=root)
    except CandidateIntegrityDenied as exc:
        raise CandidateIntegrityDenied("WRONG_MERGED_SOURCE_HEAD") from exc
    must(branch == INTEGRATION_BRANCH, "WRONG_MERGED_SOURCE_BRANCH")
    for ancestor in (HISTORIC, C2_COMMIT, PREMERGE_SOURCE):
        _git("merge-base", "--is-ancestor", ancestor, head, root=root)

    verifier = root / "core/platform/release_integrity.py"
    must(hashlib.sha256(verifier.read_bytes()).hexdigest() == FROZEN_VERIFIER_RAW_SHA,
         "FROZEN_PC8_VERIFIER_TAMPERED")
    for n in range(1, 9):
        rel = f"contracts/platform/v1/pc{n}_release_manifest.json"
        local = (root / rel).read_bytes()
        must(_canonical(local, rel) == _canonical(_blob(HISTORIC, rel, root), rel),
             f"FROZEN_PC{n}_MANIFEST_MUTATED")
        must(_canonical(local, rel) == _canonical(_blob(head, rel, root), rel),
             f"DIRTY_PC{n}_MANIFEST")

    manifest = json.loads(_blob(HISTORIC, PC8_PATH, root))
    policy = manifest["fingerprint_policy"]
    must(policy.get("mode") == "sha256_canonical_source_v1" and
         policy.get("text_normalization") == "crlf_to_lf_only",
         "PC8_FINGERPRINT_POLICY_CHANGED")
    rows = manifest["artifacts"]
    expected = {row["path"]: row["sha256"] for row in rows}
    must(len(rows) == len(expected) == 40, "PC8_40_ARTIFACT_COUNT_DRIFT")
    old, current, seals = {}, {}, {}
    for rel in expected:
        old[rel] = _sha(_blob(HISTORIC, rel, root), rel)
        now = (root / rel).read_bytes()
        must(_canonical(now, rel) == _canonical(_blob(head, rel, root), rel),
             "PC8_TRACKED_ARTIFACT_DIRTY=" + rel)
        current[rel] = _sha(now, rel)
    for rel, (name, accepted) in ACCEPTED_LATER_SEALS.items():
        seal_path = "contracts/platform/v1/" + name
        raw = (root / seal_path).read_bytes()
        must(_canonical(raw, seal_path) ==
             _canonical(_blob(head, seal_path, root), seal_path),
             "PC8_SUCCESSOR_SEAL_DIRTY=" + name)
        seals[rel] = _seal_digest(rel, json.loads(raw), name)
        must(seals[rel] == accepted, "PC8_SUCCESSOR_SEAL_DRIFT=" + rel)
    result = evaluate_pairs(expected, old, current, seals)

    # Verify no altered historical latest=8 checker is silently used as
    # the current five-descendant source release.
    try:
        verify_latest_release(root)
    except ReleaseIntegrityError:
        pass
    else:
        raise CandidateIntegrityDenied("HISTORICAL_PC8_FALLBACK_PROMOTED")

    registry_rel = "contracts/platform/v1/pc8_current_source_companion_registry_r1.json"
    registry_raw = (root / registry_rel).read_bytes()
    must(_canonical(registry_raw, registry_rel) ==
         _canonical(_blob(head, registry_rel, root), registry_rel),
         "SOURCE_REGISTRY_TRACKED_DRIFT")
    registry = json.loads(registry_raw)
    must(registry.get("registered") is False and registry.get("active") is False,
         "FORGED_SOURCE_REGISTRY_OPERATIVE_PROMOTION")
    return {
        **result,
        "postmerge_source_head": head,
        "isolated_lane_branch": branch,
        "source_integrity_candidate": "PASS_LOCAL_PINNED_MERGED_SOURCE",
        "original_PC8_verifier_modified": False,
        "independent_operative_issuer_proven": False,
        "github_required_checks_proven": False,
        "hosted_service_and_schema_proven": False,
        "real_merchant_authority_proven": False,
        "operative_release": False,
        "D1_hosted": "HOLD",
        "D2_activation": "HOLD",
    }


if __name__ == "__main__":
    print(json.dumps(inspect(), indent=2, sort_keys=True))
