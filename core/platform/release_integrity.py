"""Canonical Platform Core release-integrity and descendant-chain verification."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


FINGERPRINT_MODE = "sha256_canonical_source_v1"
TEXT_NORMALIZATION = "crlf_to_lf_only"
BINARY_NORMALIZATION = "exact_bytes"
DEFAULT_TEXT_SUFFIXES = (
    ".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml",
)
_MANIFEST_PATTERN = re.compile(r"pc([1-9][0-9]*)_release_manifest\.json$")


class ReleaseIntegrityError(RuntimeError):
    pass


def canonical_bytes(data: bytes, *, artifact_kind: str) -> bytes:
    if artifact_kind == "text":
        return data.replace(b"\r\n", b"\n")
    if artifact_kind == "binary":
        return data
    raise ReleaseIntegrityError(f"unknown artifact kind={artifact_kind}")


def artifact_kind(relative_path: str, text_suffixes=DEFAULT_TEXT_SUFFIXES) -> str:
    suffix = Path(relative_path).suffix.casefold()
    return "text" if suffix in frozenset(text_suffixes) else "binary"


def _clean_git_blob(repository_root: Path, relative_path: str) -> bytes | None:
    git_dir = repository_root / ".git"
    if not git_dir.exists():
        return None
    tracked = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "--error-unmatch", "--", relative_path],
        check=False, capture_output=True,
    )
    if tracked.returncode:
        return None
    working = subprocess.run(
        ["git", "-C", str(repository_root), "diff", "--quiet", "--", relative_path],
        check=False, capture_output=True,
    )
    staged = subprocess.run(
        ["git", "-C", str(repository_root), "diff", "--cached", "--quiet", "--", relative_path],
        check=False, capture_output=True,
    )
    if working.returncode or staged.returncode:
        return None
    blob = subprocess.run(
        ["git", "-C", str(repository_root), "show", f"HEAD:{relative_path}"],
        check=False, capture_output=True,
    )
    if blob.returncode:
        raise ReleaseIntegrityError(f"cannot read clean Git source={relative_path}")
    return blob.stdout


def canonical_sha256(path: Path, *, relative_path: str | None = None, repository_root: Path | None = None, text_suffixes=DEFAULT_TEXT_SUFFIXES) -> str:
    relative = relative_path or path.as_posix()
    data = _clean_git_blob(repository_root, relative) if repository_root is not None else None
    if data is None:
        data = path.read_bytes()
    data = canonical_bytes(data, artifact_kind=artifact_kind(relative, text_suffixes))
    return hashlib.sha256(data).hexdigest()


def fingerprint_policy(manifest: dict) -> dict:
    policy = manifest.get("fingerprint_policy")
    if not isinstance(policy, dict):
        raise ReleaseIntegrityError("latest release manifest has no fingerprint policy")
    if policy.get("mode") != FINGERPRINT_MODE:
        raise ReleaseIntegrityError(f"unsupported fingerprint mode={policy.get('mode')}")
    if policy.get("text_normalization") != TEXT_NORMALIZATION or policy.get("binary_normalization") != BINARY_NORMALIZATION:
        raise ReleaseIntegrityError("release fingerprint normalization rule changed")
    suffixes = policy.get("text_suffixes")
    if suffixes != sorted(set(DEFAULT_TEXT_SUFFIXES)):
        raise ReleaseIntegrityError("release text-artifact classification changed")
    return policy


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseIntegrityError(f"invalid release manifest={path.name}: {exc}") from exc


def release_chain(root: Path) -> list[tuple[int, dict]]:
    directory = root / "contracts/platform/v1"
    found = {}
    for path in directory.glob("pc*_release_manifest.json"):
        match = _MANIFEST_PATTERN.fullmatch(path.name)
        if match:
            found[int(match.group(1))] = _load(path)
    if not found:
        raise ReleaseIntegrityError("no Platform Core release manifests")
    expected = list(range(1, max(found) + 1))
    if sorted(found) != expected:
        raise ReleaseIntegrityError(f"non-contiguous or unknown release sequence={sorted(found)}")
    chain = [(number, found[number]) for number in expected]
    for (prior_number, prior), (number, current) in zip(chain, chain[1:]):
        if current.get("previous_head") != prior.get("accepted_head"):
            raise ReleaseIntegrityError(f"unauthorized descendant lineage=PC{prior_number}->PC{number}")
    latest_number, latest = chain[-1]
    policy = fingerprint_policy(latest)
    if policy.get("release_sequence") != latest_number:
        raise ReleaseIntegrityError("latest release sequence declaration mismatch")
    for number, _ in chain[:-1]:
        if f"historical_pc{number}_replacements" not in latest:
            raise ReleaseIntegrityError(f"latest descendant omits PC{number} replacement proof")
    return chain


def latest_release(root: Path) -> tuple[int, dict]:
    return release_chain(root)[-1]


def _replacement_map(descendant: dict, milestone: int) -> dict[str, dict]:
    entries = descendant.get(f"historical_pc{milestone}_replacements", [])
    result = {item.get("path"): item for item in entries}
    if None in result or len(result) != len(entries):
        raise ReleaseIntegrityError(f"PC{milestone} replacement paths are invalid or duplicated")
    if any(any(token in path for token in "*?[") for path in result):
        raise ReleaseIntegrityError(f"PC{milestone} replacement wildcard forbidden")
    return result


def verify_historical_release(root: Path, milestone: int) -> dict:
    chain = release_chain(root)
    manifests = dict(chain)
    if milestone not in manifests:
        raise ReleaseIntegrityError(f"unknown historical milestone=PC{milestone}")
    latest_number, latest = chain[-1]
    policy = fingerprint_policy(latest)
    suffixes = policy["text_suffixes"]
    historical = manifests[milestone]
    replacements = {} if milestone == latest_number else _replacement_map(latest, milestone)
    mismatches = set()
    for artifact in historical.get("artifacts", []):
        relative = artifact["path"]
        path = root / relative
        actual = canonical_sha256(path, relative_path=relative, repository_root=root, text_suffixes=suffixes) if path.is_file() else None
        expected = artifact["sha256"]
        if actual != expected:
            mismatches.add(relative)
            replacement = replacements.get(relative)
            if not replacement or replacement.get("historical_sha256") != expected or replacement.get("descendant_sha256") != actual:
                raise ReleaseIntegrityError(f"PC{milestone} release manifest mismatch={relative}")
    if set(replacements) != mismatches:
        raise ReleaseIntegrityError(f"PC{milestone} replacement set mismatch={sorted(set(replacements)^mismatches)}")
    return {"milestone": milestone, "latest": latest_number, "artifact_count": len(historical.get("artifacts", [])), "replacement_count": len(replacements)}


def verify_latest_release(root: Path) -> dict:
    latest_number, latest = latest_release(root)
    policy = fingerprint_policy(latest)
    suffixes = policy["text_suffixes"]
    for artifact in latest.get("artifacts", []):
        relative = artifact["path"]
        path = root / relative
        actual = canonical_sha256(path, relative_path=relative, repository_root=root, text_suffixes=suffixes) if path.is_file() else None
        if actual != artifact["sha256"]:
            raise ReleaseIntegrityError(f"PC{latest_number} release manifest mismatch={relative}")
    return {"latest": latest_number, "artifact_count": len(latest.get("artifacts", []))}
