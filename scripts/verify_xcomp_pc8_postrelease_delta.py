"""XCOMP Wave1 N delta: PC8 frozen snapshot vs current descendant evidence.

Source-only, *non-operative* candidate. Does not mint a PC9 release, edit manifests,
change the canonical PC8 validator, or confer release/hosting authority.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts/platform/v1"
HISTORIC = "5931c901413af296c156af593ff3187b75006d5b"
CANDIDATE_HEAD = "e89d81d6ef427b88b94e2b78df083d767a12a094"
C2_COMMIT = "d2b7e3f4ee2b9beec384ee593b7860e0c4a9344a"
PC8_PATH = "contracts/platform/v1/pc8_release_manifest.json"

# A fixed five-path scope, not a wildcard permission to replace future bytes.
ACCEPTED_LATER_SEALS = {
    "core/platform/architecture_contract.py": (
        "pc0_validator_successor_seal_r8.json",
        "2d04bbf17aed7c6481f0b22fa12abf4a191253043672aa92cd2083b79442925d",
    ),
    "tests/contracts/test_pc0_kernel_boundaries.py": (
        "pc0_validator_successor_seal_r8.json",
        "46bad44c9392fd43cde0cbc55ed742a4f3c369a6b640b4b65ce4f1625f1d7604",
    ),
    "core/middleware/auth_middleware.py": (
        "pc0_vn2_c2_discovery_implementation_seal.json",
        "66797bd319cfcce3fceb4b75af256e704736cd140be2d67158d4a5a66e0cbb55",
    ),
    "core/middleware/tenant_middleware.py": (
        "pc0_post_nce_source_successors.json",
        "db8ea71d0205fbf6b40b8e857d20d12f8584283a40441a2df49869c10394d0ff",
    ),
    "core/middleware/branch_middleware.py": (
        "pc0_post_nce_source_successors.json",
        "568d8f7ee0f1bec31d5e46ca2386b093f23a25886a390680cc4d825fd5b3dfa4",
    ),
}


class CandidateIntegrityDenied(RuntimeError):
    """Fail closed if the proposed post-PC8 evidence changes."""


def _git(*args: str, root: Path = ROOT) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise CandidateIntegrityDenied(
            "GIT_READ_OR_LINEAGE_FAILED=" + "|".join(args[:2])
        )
    return result.stdout


def _blob(commit: str, relative: str, root: Path = ROOT) -> bytes:
    return _git("show", f"{commit}:{relative}", root=root)


def _canonical(raw: bytes, relative: str) -> bytes:
    text_types = {
        ".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml",
        ".txt", ".yaml", ".yml",
    }
    return raw.replace(b"\r\n", b"\n") if Path(relative).suffix.casefold() in text_types else raw


def _sha(raw: bytes, relative: str) -> str:
    return hashlib.sha256(_canonical(raw, relative)).hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seal_digest(relative: str, seal: dict, name: str) -> str:
    if name in (
        "pc0_validator_successor_seal_r8.json",
        "pc0_vn2_c2_discovery_implementation_seal.json",
    ):
        selected = [entry["successor_sha256"] for entry in seal["files"]
                    if entry["path"] == relative]
    elif name == "pc0_post_nce_source_successors.json":
        records = [entry for entry in seal["paths"] if entry["path"] == relative]
        selected = ([item["successor_sha256"]
                     for item in records[0]["successors"]]
                    if len(records) == 1 else [])
        selected = selected[-1:]  # the current terminal accepted descendant
    else:
        raise CandidateIntegrityDenied("UNRECOGNIZED_SEAL=" + name)
    if len(selected) != 1:
        raise CandidateIntegrityDenied("SEAL_NOT_UNIQUE=" + relative)
    return selected[0]


def evaluate_pairs(
    expected_historical: dict[str, str],
    historic_actual: dict[str, str],
    current_actual: dict[str, str],
    sealed_actual: dict[str, str],
) -> dict:
    """Pure validator; keeps negative tests independent of Git and provider."""
    expected = set(expected_historical)
    if not expected or expected != set(historic_actual) or expected != set(current_actual):
        raise CandidateIntegrityDenied("ARTIFACT_SET_CHANGED")
    for path in expected:
        if expected_historical[path] != historic_actual[path]:
            raise CandidateIntegrityDenied("FROZEN_SNAPSHOT_MISMATCH=" + path)
    mismatches = {
        path for path in expected
        if current_actual[path] != expected_historical[path]
    }
    if mismatches != set(ACCEPTED_LATER_SEALS):
        raise CandidateIntegrityDenied("FIVE_PATH_SCOPE_MISMATCH")
    if set(sealed_actual) != mismatches:
        raise CandidateIntegrityDenied("SUCCESSOR_SEAL_SET_MISMATCH")
    for path in mismatches:
        if (sealed_actual[path] != ACCEPTED_LATER_SEALS[path][1]
                or current_actual[path] != sealed_actual[path]):
            raise CandidateIntegrityDenied("UNAUTHORIZED_DESCENDANT=" + path)
    return {
        "historical_pc8_count": len(expected),
        "historical_pc8_match": len(expected),
        "current_pc8_unchanged": len(expected) - len(mismatches),
        "current_descendant_count": len(mismatches),
        "descendant_paths": sorted(mismatches),
        "historical_pc8_snapshot": "MATCH",
        "post_pc8_candidate_source": "QUALIFIED_LOCAL_LINEAGE_ONLY",
        "cumulative_release_registered": False,
        "current_frozen_pc8_test_suite_expected_to_pass": False,
    }


def inspect(root: Path = ROOT) -> dict:
    head = _git("rev-parse", "HEAD", root=root).decode().strip()
    if head != CANDIDATE_HEAD:
        raise CandidateIntegrityDenied("UNPINNED_CANDIDATE_HEAD")
    for ancestor in (HISTORIC, C2_COMMIT):
        _git("merge-base", "--is-ancestor", ancestor, head, root=root)

    # Manifests are immutable. Historical snapshot must be an actual ancestor.
    for milestone in range(1, 9):
        rel = f"contracts/platform/v1/pc{milestone}_release_manifest.json"
        if _canonical(_blob(HISTORIC, rel, root), rel) != _canonical(
            (root / rel).read_bytes(), rel
        ):
            raise CandidateIntegrityDenied(f"HISTORICAL_PC{milestone}_MANIFEST_MUTATED")

    manifest = json.loads(_blob(HISTORIC, PC8_PATH, root))
    policy = manifest["fingerprint_policy"]
    if (policy.get("mode") != "sha256_canonical_source_v1"
            or policy.get("text_normalization") != "crlf_to_lf_only"):
        raise CandidateIntegrityDenied("CHANGED_FINGERPRINT_POLICY")
    rows = manifest["artifacts"]
    expected = {row["path"]: row["sha256"] for row in rows}
    if len(rows) != 40 or len(expected) != 40:
        raise CandidateIntegrityDenied("PC8_ARTIFACT_CARDINALITY")

    old = {path: _sha(_blob(HISTORIC, path, root), path) for path in expected}
    current = {}
    for path in expected:
        source = root / path
        if not source.is_file():
            raise CandidateIntegrityDenied("CURRENT_PATH_MISSING=" + path)
        local = source.read_bytes()
        committed = _blob(head, path, root)
        if _canonical(local, path) != _canonical(committed, path):
            raise CandidateIntegrityDenied("PROTECTED_TRACKED_PATH_DIRTY=" + path)
        current[path] = _sha(local, path)

    seals = {}
    for relative, (filename, registered_sha) in ACCEPTED_LATER_SEALS.items():
        seal_path = f"contracts/platform/v1/{filename}"
        data = (root / seal_path).read_bytes()
        if _canonical(data, seal_path) != _canonical(
            _blob(head, seal_path, root), seal_path
        ):
            raise CandidateIntegrityDenied("SOURCE_SEAL_DIRTY=" + filename)
        if (filename == "pc0_validator_successor_seal_r8.json"
                and _git("merge-base", "--is-ancestor", C2_COMMIT, head, root=root) != b""):
            raise CandidateIntegrityDenied("PC0_C2_LINEAGE_ERROR")
        seals[relative] = _seal_digest(relative, json.loads(data), filename)
        if seals[relative] != registered_sha:
            raise CandidateIntegrityDenied("EXPECTED_REGISTRY_HASH_CHANGED=" + relative)

    result = evaluate_pairs(expected, old, current, seals)
    result.update({
        "historic_release_commit": HISTORIC,
        "current_source_commit": head,
        "pc8_manifest_sha256": _sha((root / PC8_PATH).read_bytes(), PC8_PATH),
        "owner_admission": "PENDING_PCR_EXACT_ADDITIVE_RELEASE_REGISTRY",
        "effective_authority": "SOURCE_ONLY_NO_HOSTED_OR_RUNTIME_EFFECT",
    })
    return result


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True, indent=2))
