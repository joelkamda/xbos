"""Additive, nonoperative PC8 historical/current cumulative source verifier R1.

This is NOT a registered PC9/PC8 release, and it never edits the old canonical
release verifier, historical manifests, runtime routers or middleware.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Works identically under pytest and direct `python scripts/<name>.py` invocation.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.platform.release_integrity import ReleaseIntegrityError, verify_latest_release
from scripts.verify_xcomp_pc8_postrelease_delta import (
    ACCEPTED_LATER_SEALS,
    C2_COMMIT,
    CANDIDATE_HEAD,
    CandidateIntegrityDenied,
    HISTORIC,
    PC8_PATH,
    ROOT,
    _blob,
    _canonical,
    _git,
    _seal_digest,
    _sha,
    inspect,
)

CANDIDATE_REL = "contracts/platform/v1/pc8_postrelease_cumulative_successor_r1.json"
PC8_CANONICAL_SHA = "d94b0316c5c5205e3b314595f466935861cfb9851afc1d07f40a5aeaa7a6161b"
EXPECTED_PCR_ROOT = "7fa3b4c6c50545a17a3a211cdf730564bf6a5ef7ac5e5d6635ad8a30776594cf"
EXPECTED_GRANT_SHA = "1890ed1e1393a55fd11522b1022ad835d3eec8de5585eca4e8d8f12a8609af12"
EXPECTED_PREDECESSOR_SHA = "dc3bb678851e61232cbc6e09557d8182d1edfee158a9c2b11f0d2553ff247a49"
BRANCH = "platform/neutral-vnext-vn2-pc0-discovery-successor"
NEW_PATHS = (
    CANDIDATE_REL,
    "scripts/verify_pc8_postrelease_cumulative_successor_r1.py",
    "tests/contracts/test_pc8_postrelease_cumulative_successor_r1.py",
)
PREVIOUS_PATHS = (
    "scripts/verify_xcomp_pc8_postrelease_delta.py",
    "tests/contracts/test_xcomp_n_wave1_authorized_http_seam.py",
    "tests/contracts/test_xcomp_pc8_postrelease_delta.py",
)


def _deny(condition: bool, code: str) -> None:
    if not condition:
        raise CandidateIntegrityDenied(code)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def check_clean_tracked(raw: bytes, git_blob: bytes, relative: str) -> None:
    _deny(
        _canonical(raw, relative) == _canonical(git_blob, relative),
        "DIRTY_PROTECTED_SOURCE=" + relative,
    )


def check_frozen_manifest(local_raw: bytes, historical_blob: bytes, relative: str) -> None:
    _deny(
        _canonical(local_raw, relative) == _canonical(historical_blob, relative),
        "HISTORICAL_MANIFEST_MUTATED=" + relative,
    )


def validate_record(
    record: dict,
    historical_expected: dict[str, str],
    *,
    current_head: str = CANDIDATE_HEAD,
    current_branch: str = BRANCH,
) -> dict[str, dict]:
    """Pure fail-closed versioned candidate protocol, useful for negatives."""
    _deny(isinstance(record, dict), "INVALID_CANDIDATE")
    _deny(
        record.get("schema")
        == "XCOMP_PLATFORM_CORE_PC8_POST_RELEASE_CUMULATIVE_CANDIDATE_R1",
        "SCHEMA_MISMATCH",
    )
    _deny(record.get("record_state") == "PENDING_NONOPERATIVE_CANDIDATE", "STATE_NOT_PENDING")
    for token in ("registered", "active", "successor_promoted", "operative_authority"):
        _deny(record.get(token) is False, "FALSE_OPERATIVE_RELEASE=" + token)
    _deny(record.get("declared_release_number") is None, "PREMATURE_NEW_RELEASE_NUMBER")
    _deny(record.get("pcr_parent_root_sha256") == EXPECTED_PCR_ROOT, "PCR_ROOT_MISMATCH")
    _deny(record.get("exact_source_grant_sha256") == EXPECTED_GRANT_SHA, "GRANT_MISMATCH")
    _deny(
        record.get("predecessor_candidate_sha256") == EXPECTED_PREDECESSOR_SHA,
        "PREDECESSOR_PROOF_MISMATCH",
    )

    historical = record.get("historical") or {}
    current = record.get("cumulative_current") or {}
    _deny(historical.get("release") == "PC8", "HISTORICAL_RELEASE_MISMATCH")
    _deny(historical.get("git_commit") == HISTORIC, "HISTORICAL_COMMIT_CHANGED")
    _deny(historical.get("manifest_path") == PC8_PATH, "HISTORICAL_PATH_CHANGED")
    _deny(historical.get("manifest_sha256_canonical") == PC8_CANONICAL_SHA, "FROZEN_DIGEST_CHANGED")
    _deny(historical.get("historical_pc8_artifact_count") == 40, "HISTORICAL_COUNT_CHANGED")
    _deny(historical.get("historical_manifest_count") == 8, "MANIFEST_CHAIN_LENGTH_CHANGED")
    _deny(historical.get("historical_artifact_digest_mode") == "sha256_canonical_source_v1", "FINGERPRINT_MODE_CHANGED")
    _deny(len(historical_expected) == 40, "HISTORICAL_ARTIFACT_SET_CHANGED")
    _deny(current.get("git_commit") == current_head == CANDIDATE_HEAD, "UNPINNED_CURRENT_SOURCE")
    _deny(current.get("branch") == current_branch == BRANCH, "UNPINNED_SOURCE_BRANCH")
    _deny(current.get("unmodified_pc8_artifacts") == 35, "UNMODIFIED_COUNT_CHANGED")
    _deny(current.get("descendant_count") == 5, "DESCENDANT_COUNT_CHANGED")
    rows = current.get("exact_descendants")
    _deny(isinstance(rows, list) and len(rows) == 5, "FIVE_PATH_SCOPE_MISMATCH")
    paths = [row.get("path") for row in rows if isinstance(row, dict)]
    _deny(len(paths) == 5 and len(set(paths)) == 5, "DUPLICATE_OR_MALFORMED_DESCENDANT")
    _deny(set(paths) == set(ACCEPTED_LATER_SEALS), "UNAUTHORIZED_DESCENDANT_SET")
    mapped = {}
    for row in rows:
        path = row["path"]
        seal_name, digest = ACCEPTED_LATER_SEALS[path]
        _deny(
            row.get("pc8_historical_sha256") == historical_expected.get(path),
            "HISTORICAL_DESCENDANT_HASH_MISMATCH=" + path,
        )
        _deny(row.get("current_descendant_sha256") == digest,
              "CURRENT_DESCENDANT_HASH_MISMATCH=" + path)
        _deny(
            row.get("source_successor_seal") == f"contracts/platform/v1/{seal_name}",
            "UNAUTHORIZED_SOURCE_SEAL=" + path,
        )
        _deny(row.get("admission") == "PROPOSED_NONOPERATIVE",
              "UNAPPROVED_DESCENDANT_ADMISSION=" + path)
        mapped[path] = row
    _deny(
        record.get("verification_protocol", {}).get("current_legacy_pc8_validator")
        == "EXPECTED_FAILURE_NOT_BYPASSED",
        "OLD_VALIDATOR_BYPASS",
    )
    return mapped


def verify(root: Path = ROOT) -> dict:
    current_head = _git("rev-parse", "HEAD", root=root).decode().strip()
    branch = _git("branch", "--show-current", root=root).decode().strip()
    _deny(current_head == CANDIDATE_HEAD, "UNPINNED_CURRENT_SOURCE")
    _deny(branch == BRANCH, "UNPINNED_SOURCE_BRANCH")
    for ancestor in (HISTORIC, C2_COMMIT):
        _git("merge-base", "--is-ancestor", ancestor, current_head, root=root)
    for cmd in (
        ("diff", "--name-only"),
        ("diff", "--cached", "--name-only"),
    ):
        _deny(not _git(*cmd, root=root).strip(), "TRACKED_SOURCE_MODIFICATION")
    status = {
        line.strip()
        for line in _git("status", "--porcelain=v1", "--untracked-files=normal", root=root)
        .decode().splitlines()
    }
    _deny(
        status == {"?? " + path for path in (*PREVIOUS_PATHS, *NEW_PATHS)},
        "UNEXPECTED_SOURCE_WORKTREE_PRESTATE",
    )
    record = json.loads((root / CANDIDATE_REL).read_text(encoding="utf8"))
    historical_pc8 = json.loads(_blob(HISTORIC, PC8_PATH, root))
    rows = historical_pc8["artifacts"]
    historical_expected = {row["path"]: row["sha256"] for row in rows}
    _deny(len(rows) == 40 and len(historical_expected) == 40,
          "HISTORICAL_PC8_DUPLICATE_OR_MISSING")
    mapping = validate_record(
        record, historical_expected,
        current_head=current_head, current_branch=branch,
    )

    # Historical PC1–PC8 manifests: no new numbering and no rewritten bytes.
    for sequence in range(1, 9):
        rel = f"contracts/platform/v1/pc{sequence}_release_manifest.json"
        check_frozen_manifest((root / rel).read_bytes(), _blob(HISTORIC, rel, root), rel)
        check_clean_tracked((root / rel).read_bytes(), _blob(current_head, rel, root), rel)
    _deny(_sha((root / PC8_PATH).read_bytes(), PC8_PATH) == PC8_CANONICAL_SHA,
          "PC8_MANIFEST_FINGERPRINT_CHANGED")
    policy = historical_pc8.get("fingerprint_policy") or {}
    _deny(
        policy.get("mode") == "sha256_canonical_source_v1"
        and policy.get("text_normalization") == "crlf_to_lf_only",
        "HISTORICAL_FINGERPRINT_POLICY_CHANGED",
    )

    current_mismatches = set()
    for path, expected in historical_expected.items():
        historical_sha = _sha(_blob(HISTORIC, path, root), path)
        _deny(historical_sha == expected, "HISTORICAL_ARTIFACT_TAMPERED=" + path)
        local = (root / path).read_bytes()
        check_clean_tracked(local, _blob(current_head, path, root), path)
        actual = _sha(local, path)
        if actual != expected:
            current_mismatches.add(path)
            _deny(path in mapping, "UNAUTHORIZED_SIXTH_DESCENDANT=" + path)
            _deny(actual == mapping[path]["current_descendant_sha256"],
                  "CURRENT_SOURCE_TAMPERED=" + path)
    _deny(current_mismatches == set(mapping), "INCOMPLETE_DESCENDANT_GRAPH")

    for path, row in mapping.items():
        seal = row["source_successor_seal"]
        local = (root / seal).read_bytes()
        check_clean_tracked(local, _blob(current_head, seal, root), seal)
        sealed = _seal_digest(path, json.loads(local), Path(seal).name)
        _deny(sealed == row["current_descendant_sha256"],
              "UNACCEPTED_OR_CHANGED_SOURCE_SEAL=" + path)

    # Reuse independently accepted earlier source proof; it must still agree.
    baseline = inspect(root)
    _deny(baseline["historical_pc8_match"] == 40
          and baseline["current_descendant_count"] == 5
          and baseline["current_pc8_unchanged"] == 35,
          "PREDECESSOR_SOURCE_PROOF_DRIFT")

    # Explicit negative control: existing latest-release validator is *not* repaired.
    try:
        verify_latest_release(root)
    except ReleaseIntegrityError as exc:
        _deny("PC8 release manifest mismatch=" in str(exc),
              "UNEXPECTED_LEGACY_RELEASE_FAILURE")
    else:
        raise CandidateIntegrityDenied("LEGACY_VALIDATOR_WAS_SILENTLY_BYPASSED")

    return {
        "status": "ADDITIVE_CUMULATIVE_PC8_SOURCE_CANDIDATE_QUALIFIED",
        "historical_pc8_artifacts_matched": 40,
        "manifests_pc1_pc8_unchanged": 8,
        "current_pc8_artifacts_unchanged": 35,
        "current_sealed_descendants": 5,
        "descendant_paths": sorted(current_mismatches),
        "source_git_head": current_head,
        "candidate_sha256_raw": _digest((root / CANDIDATE_REL).read_bytes()),
        "legacy_pc8_current_head_validator": "EXPECTED_FAIL_PRESERVED",
        "registered_release": False,
        "operative_authority": False,
        "hosted_or_db_effect": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
