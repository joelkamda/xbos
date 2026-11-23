"""G4-A TEST source admission contract for canonical XBOS Complete.

This module is deliberately NONOPERATIVE. It validates the precise R7 source
bundle admitted into code review; it cannot create PC5 identities, apply
migrations, write any WND database, or publish a product. Existing canonical
FastAPI startup never imports or mounts the fenced rehearsal source.

The source bundle remains a *candidate for porting*, not an allowed kernel
runtime or a production implementation. All actual admissions are explicit.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json

R7_ACCEPTED_REPORT = "e27ac9524b6985e6d0208ac185e073f9ecd127873b2bd640c3b079da5707fb0d"
R6_ACCEPTED_REPORT = "4061846d82aa764764603aacccf351ad17d08023693f50e2d322ff037687f394"
EXPECTED_BASE = "376547f7c037814ab2b19a1df8fd6c7aec08f864"
SOURCE_GRADE = "SYNTHETIC_DETACHED_TEST_ONLY_NOT_RELEASED"
REQUIRED_ROOTS = frozenset((
    "source/backend/v24_init_r7.sql",
    "source/backend/rehearsal_v3/v24_native_api.py",
    "source/backend/rehearsal_v3/v24_pk_native_r7.py",
    "source/backend/rehearsal_v3/v24_pa_test_publish_grant.py",
    "source/backend/rehearsal_v3/v24_sof_ar_r6.py",
    "source/backend/rehearsal_v3/v24_w_receipt_custody.py",
    "source/backend/rehearsal_v3/v24_w_shift_handoff.py",
    "source/frontend/src/rehearsal_v3/V24IntegratedRestaurant.tsx",
    "source/integration/r7_unified_native_acceptance.py",
    "source/integration/r7_unified_chromium_acceptance.py",
))
FORBIDDEN_PERMISSIONS = frozenset((
    "live_wnd", "real_psp", "genuine_pc5", "official_finance",
    "canonical_kernel_route_mount", "protected_merge", "production_release",
))


class G4ASourceAdmissionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class G4ASourceAdmission:
    grade: str
    counted_files: int
    api_pg17_checks: int
    browser_checks: int
    total_checks: int
    canonical_runtime_mounted: bool
    production_admitted: bool


def require_production_admission(*_args: object, **_kwargs: object) -> None:
    """Protected boundary: no synthetic R7 source can authorize live effects."""
    raise G4ASourceAdmissionError("G4A_REAL_PC5_FINANCE_PACK_AND_FIELD_ADMISSION_REQUIRED")


def inspect_test_source(bundle_root: Path) -> G4ASourceAdmission:
    """SHA-bound review only. No network, DB, subprocess, file writes, or imports.

    Path is a repository-local candidate root containing R7_SOURCE_MANIFEST.json
    and source/. Reject symlinks, escaping paths, missing or mutated sources.
    """
    root = Path(bundle_root)
    if not root.is_dir() or root.is_symlink():
        raise G4ASourceAdmissionError("G4A_BUNDLE_NOT_DIRECTORY")
    manifest = root / "R7_SOURCE_MANIFEST.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise G4ASourceAdmissionError("G4A_MANIFEST_MISSING")
    try:
        obj = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise G4ASourceAdmissionError("G4A_MANIFEST_INVALID") from exc
    if (obj.get("schema") != "XCOMP_G4A_R7_CANONICAL_DETACHED_SOURCE_V1"
        or obj.get("source_grade") != SOURCE_GRADE
        or obj.get("canonical_protected_base") != EXPECTED_BASE
        or obj.get("accepted_r6_root_sha256") != R6_ACCEPTED_REPORT
        or obj.get("accepted_r7_report_sha256") != R7_ACCEPTED_REPORT):
        raise G4ASourceAdmissionError("G4A_SOURCE_LINEAGE_UNTRUSTED")
    perms = obj.get("permissions")
    if not isinstance(perms, dict) or set(perms) != FORBIDDEN_PERMISSIONS:
        raise G4ASourceAdmissionError("G4A_PERMISSION_MANIFEST_MISMATCH")
    if any(perms[k] is not False for k in FORBIDDEN_PERMISSIONS):
        raise G4ASourceAdmissionError("G4A_PREMATURE_OPERATIONAL_GRANT")
    tests = obj.get("accepted_r7_checks")
    if tests != {"native_postgresql":123, "chromium_react":38, "total":161}:
        raise G4ASourceAdmissionError("G4A_EVIDENCE_COUNTS_CHANGED")
    files = obj.get("files")
    if not isinstance(files, dict) or not REQUIRED_ROOTS.issubset(files):
        raise G4ASourceAdmissionError("G4A_CRITICAL_SOURCE_MISSING")
    if obj.get("artifact_count") != len(files):
        raise G4ASourceAdmissionError("G4A_FILE_COUNT_MISMATCH")
    resolved = root.resolve(strict=True)
    for name, info in files.items():
        if (not isinstance(name, str) or not name.startswith("source/")
            or "\\" in name or ".." in name.split("/")
            or name.startswith("/") or not isinstance(info, dict)):
            raise G4ASourceAdmissionError("G4A_INVALID_BUNDLE_PATH")
        path = root / name
        try:
            if path.is_symlink() or not path.is_file() or not path.resolve(strict=True).is_relative_to(resolved):
                raise G4ASourceAdmissionError("G4A_SYMLINK_OR_FILE_MISSING")
            data = path.read_bytes()
        except (OSError, ValueError) as exc:
            raise G4ASourceAdmissionError("G4A_SOURCE_UNREADABLE") from exc
        if info.get("bytes") != len(data) or info.get("sha256") != sha256(data).hexdigest():
            raise G4ASourceAdmissionError("G4A_SOURCE_SHA256_CHANGED")
    return G4ASourceAdmission(SOURCE_GRADE, len(files),123,38,161,False,False)
