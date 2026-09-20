from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "c79d81094f8ee236851ae999582a453ecca63ec1"
EXPECTED_BRANCH = "integration/xafpay-xgi2-foundation-source-materialization"
AUTHORITY = "XBOS-XGI2-R4D-FOUNDATION-SOURCE-MATERIALIZATION"

AUTHORIZED_PATHS = (
    "core/platform/structure/identity_import_contract.py",
    "core/platform/structure/identity_import_service.py",
    "core/platform/structure/identity_import_repository.py",
    "core/platform/structure/currency_foundation_contract.py",
    "core/platform/structure/currency_foundation_service.py",
    "core/platform/structure/currency_foundation_repository.py",
    "contracts/platform/v1/xgi2_foundation_authority.json",
    "contracts/platform/v1/xgi2_foundation_release_manifest.json",
    "docs/platform_core/XGI2_TENANT_IDENTITY_AND_CURRENCY_FOUNDATION.md",
    "scripts/verify_xgi2_foundation_authority.py",
    "tests/contracts/test_xgi2_foundation_authority.py",
)


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changed_paths() -> set[str]:
    output = git("status", "--porcelain=v1", "-uall")
    return {
        line[3:].replace("\\", "/")
        for line in output.splitlines()
        if line.strip()
    }


def verify() -> dict[str, object]:
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    if head != EXPECTED_HEAD:
        raise RuntimeError(f"XGI2_R4D_HEAD_MISMATCH:{head}")
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"XGI2_R4D_BRANCH_MISMATCH:{branch}")

    changed = changed_paths()
    expected = set(AUTHORIZED_PATHS)
    if changed != expected:
        raise RuntimeError(
            "XGI2_R4D_PATH_ENVELOPE_MISMATCH:"
            f"missing={sorted(expected - changed)},unexpected={sorted(changed - expected)}"
        )
    if git("diff", "--cached", "--name-only"):
        raise RuntimeError("XGI2_R4D_STAGING_NOT_EMPTY")

    authority = json.loads(
        (ROOT / "contracts/platform/v1/xgi2_foundation_authority.json").read_text(
            encoding="utf-8"
        )
    )
    if authority["authority"] != AUTHORITY:
        raise RuntimeError("XGI2_R4D_AUTHORITY_MISMATCH")
    if tuple(authority["authorized_paths"]) != AUTHORIZED_PATHS:
        raise RuntimeError("XGI2_R4D_AUTHORIZED_PATH_ORDER_MISMATCH")
    if authority["database_foundation_rows"] or authority["schema_mutation"]:
        raise RuntimeError("XGI2_R4D_MUTATION_BOUNDARY_INVALID")
    if authority["existing_pc1_rewrite"] or authority["finance_kernel_mutation"]:
        raise RuntimeError("XGI2_R4D_AUTHORITY_BOUNDARY_INVALID")

    tenant = authority["tenant_identity"]
    exact_tenant = {
        "tenant_id": 2,
        "tenant_code": "wnd",
        "tenant_name": "Wine & Dine",
        "country_code": "CM",
        "currency": "XAF",
        "locale": "fr-CM",
        "timezone": "Africa/Douala",
        "legal_entity_code": "WND-CM",
        "legal_entity_name": "Wine & Dine Cameroon",
        "root_organization_code": "WND",
        "primary_location_code": "LOGPOM",
    }
    for key, value in exact_tenant.items():
        if tenant.get(key) != value:
            raise RuntimeError(f"XGI2_R4D_TENANT_PROFILE_MISMATCH:{key}")

    asset = authority["currency_asset"]
    if (
        asset["code"],
        asset["asset_kind"],
        asset["minor_unit_scale"],
        asset["maximum_storage_scale"],
        asset["active"],
    ) != ("XAF", "fiat", 0, 8, True):
        raise RuntimeError("XGI2_R4D_XAF_ASSET_MISMATCH")

    policy = authority["tenant_currency_policy"]
    if (
        policy["tenant_id"],
        policy["currency_code"],
        policy["rounding_mode"],
        policy["cash_rounding_increment"],
        policy["policy_version"],
        policy["effective_from"],
    ) != (2, "XAF", "half_even", "0", 1, "2026-09-19T00:00:00+00:00"):
        raise RuntimeError("XGI2_R4D_XAF_POLICY_MISMATCH")

    manifest = json.loads(
        (ROOT / "contracts/platform/v1/xgi2_foundation_release_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if manifest["authority"] != AUTHORITY or manifest["source_parent"] != EXPECTED_HEAD:
        raise RuntimeError("XGI2_R4D_RELEASE_IDENTITY_MISMATCH")
    artifacts = manifest["artifacts"]
    expected_manifest_paths = set(AUTHORIZED_PATHS) - {
        "contracts/platform/v1/xgi2_foundation_release_manifest.json"
    }
    if {item["path"] for item in artifacts} != expected_manifest_paths:
        raise RuntimeError("XGI2_R4D_RELEASE_ARTIFACT_SET_MISMATCH")
    for item in artifacts:
        actual = sha256(ROOT / item["path"])
        if actual != item["sha256"]:
            raise RuntimeError(f"XGI2_R4D_HASH_MISMATCH:{item['path']}")

    forbidden = {
        "core/platform/structure/contracts.py",
        "core/platform/structure/service.py",
        "core/platform/structure/sql_repository.py",
    }
    if changed & forbidden:
        raise RuntimeError("XGI2_R4D_EXISTING_PC1_REWRITE")
    if any(path.startswith("core/domain/finance/") for path in changed):
        raise RuntimeError("XGI2_R4D_FINANCE_KERNEL_MUTATION")
    if any(path.startswith("alembic_neutral/") for path in changed):
        raise RuntimeError("XGI2_R4D_SCHEMA_MUTATION")

    return {
        "status": "PASS",
        "authority": AUTHORITY,
        "head": head,
        "branch": branch,
        "changed_path_count": len(changed),
        "authorized_path_count": len(AUTHORIZED_PATHS),
        "staging": "EMPTY",
        "schema_mutation": "NO",
        "database_foundation_rows": "NO",
        "finance_kernel_mutation": "NO",
        "existing_pc1_rewrite": "NO",
        "release_artifact_count": len(artifacts),
    }


if __name__ == "__main__":
    result = verify()
    print("XGI2_R4D_VERIFY=PASS")
    print(json.dumps(result, sort_keys=True))
