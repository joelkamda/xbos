"""Verify PC8 posthoc successor integrity for H1B private-route admission."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONTRACTS = ROOT / "contracts/platform/v1"
BASE = "f4dcfbe3c555d7da17196cdc4b377fd333db7a4d"
PRIVATE_PREFIX = "/internal/customer-channel/v1"
TEXT_SUFFIXES = {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}
EXTRA_ARTIFACTS = {
    "startup.py",
    "core/middleware/auth_middleware.py",
    "core/middleware/tenant_middleware.py",
    "core/middleware/branch_middleware.py",
    "contracts/platform/v1/pc8_h1b_private_route_admission_successor.json",
    "scripts/verify_pc8_h1b_private_route_admission_successor.py",
    "tests/contracts/test_pc8_h1b_private_route_admission_successor.py",
}
H1B_MIGRATION_PATHS = {
    "alembic_neutral/versions/cch_customer_channel_checkout_authority_047.py",
    "alembic_neutral/sql/cch_customer_channel_checkout_authority_up.sql",
    "alembic_neutral/sql/cch_customer_channel_checkout_authority_down.sql",
}
R2_AUTHORITY = "XBOS-G02-C3-H1B-R2-R1-R2-R1-FULL-REGRESSION-SUCCESSOR-MATERIALIZATION-AND-REEXECUTION"
R1_AUTHORITY = "XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION"
NCE_EVENT_PATH = "/kernel/integrations/xafpay-v2/events"
NCE_UNIQUE_SHA = {
    "core/api/kernel_router.py": "a8b4a8b645ed7dd31367eb4dfa5643118ae7e518370817fdd5ddba997dd21c3d",
    "core/integrations/xafpay_v2/__init__.py": "81a784b6db2386847bab5b0a86633d85ae57986e76c003dd11e46dd5dd7fc38a",
    "core/integrations/xafpay_v2/contract.py": "8bb5e87bbd49d94b0a45499ca544c0f21964e84f867d3c9389c24afe8b54fb5f",
    "core/integrations/xafpay_v2/repository.py": "da0065acac20914b5f90063b9f72315aba41f06d15639ebd1b4e0cdbccaea8a8",
    "core/integrations/xafpay_v2/router.py": "21801c3bec26128b19426edab6066448fd98f72bc4ac56b7d477f27441b10e84",
    "core/integrations/xafpay_v2/service.py": "5af5e6484fd03bbfe843c1d21c3c01094d3166ff179ba3f8bbcf77f3f006cc51",
    "tests/contracts/test_xafpay_v2_current_checkout_contract.py": "69478c4f381321cbfbcceaf9c4f9a3f058d5b39d3698629bc7642e1e241de155",
}
COMBINED_MIDDLEWARE_SHA = {
    "core/middleware/auth_middleware.py": "abe47c31cd1bf7582671c11d677c67b2fefd76001601eb38020983c73f98fb08",
    "core/middleware/tenant_middleware.py": "dda4211df3a6cd4e0e07a2daf9590722b0717937348bebcd4d426b463dbc1101",
    "core/middleware/branch_middleware.py": "64d498a2644c15e10221edbcc43b499218d9f405c3823e19b7dc321998994c5e",
}
R2_ADDITIONS = {
    "tests/contracts/test_pc1_posthoc_legacy_branch_structural_bridge.py",
    "scripts/verify_pk_aggregate_conformance_freeze.py",
    "tests/contracts/test_pk_aggregate_conformance_freeze.py",
    "scripts/verify_xa_frontend_experience_architecture.py",
    "scripts/verify_so1_atomic_catalog_pricing.py",
    "scripts/verify_pa0123_platform_administration.py",
    "scripts/verify_pa6_platform_administration_aggregate_freeze.py",
}
REPLACEMENT_HISTORICAL_SHA = {
    "tests/contracts/test_pc1_posthoc_legacy_branch_structural_bridge.py": "580f02b6e572d6888ec7bd313e814b51a33998220054ab9e266fce889a7b7c70",
    "core/platform/architecture_contract.py": "eae3265ad7632fcb9bc811ccda290579d59583ebc15aaf8d762a7262c93755b8",
    "tests/contracts/test_pc0_kernel_boundaries.py": "ece19ea243bc1725ebf0e7446af69c28ff83411cd2ff0f2cf717a9de842d06f9",
    "scripts/verify_pk_aggregate_conformance_freeze.py": "b61bd1b618a9c97283a5451abfbd5acde1fe945e32dc4d28badcf6ddc00f32e9",
    "tests/contracts/test_pk_aggregate_conformance_freeze.py": "df0e10bf3190c20d74279fd7f6b7b1523a5aea3a5a29286bc7831d15deb66032",
    "scripts/verify_xa_frontend_experience_architecture.py": "623041f48a8bb8798cb00062f5108f791edbf2879a3028b95f6a295e2259409f",
    "scripts/verify_so1_atomic_catalog_pricing.py": "1835d16fffe36f56eeee633dac4b92e85928bdddb5ae1d32ebeb80dfbd025491",
    "scripts/verify_pa0123_platform_administration.py": "1e407de05ca5401809ff2f027050e89dba27895f4c4c7a5bd6b15e4f70b12c12",
    "scripts/verify_pa6_platform_administration_aggregate_freeze.py": "46f484377737a52dad27ac135a77b2f50382e02596c115279070b8990fbc06af",
}
REPLACEMENT_CONSUMERS = {
    "tests/contracts/test_pc1_posthoc_legacy_branch_structural_bridge.py": {"tests/contracts/test_pc1_posthoc_legacy_branch_structural_bridge.py"},
    "core/platform/architecture_contract.py": {
        "scripts/verify_pk_aggregate_conformance_freeze.py",
        "tests/contracts/test_pk_aggregate_conformance_freeze.py",
        "scripts/verify_so1_atomic_catalog_pricing.py",
        "scripts/verify_pa0123_platform_administration.py",
        "scripts/verify_pa6_platform_administration_aggregate_freeze.py",
    },
    "tests/contracts/test_pc0_kernel_boundaries.py": {"scripts/verify_so1_atomic_catalog_pricing.py"},
    "scripts/verify_pk_aggregate_conformance_freeze.py": {
        "scripts/verify_pk_aggregate_conformance_freeze.py",
        "tests/contracts/test_pk_aggregate_conformance_freeze.py",
        "scripts/verify_pa0123_platform_administration.py",
        "scripts/verify_pa6_platform_administration_aggregate_freeze.py",
    },
    "tests/contracts/test_pk_aggregate_conformance_freeze.py": {
        "scripts/verify_pk_aggregate_conformance_freeze.py",
        "tests/contracts/test_pk_aggregate_conformance_freeze.py",
        "scripts/verify_pa0123_platform_administration.py",
        "scripts/verify_pa6_platform_administration_aggregate_freeze.py",
    },
    "scripts/verify_xa_frontend_experience_architecture.py": {"scripts/verify_xa_frontend_experience_architecture.py"},
    "scripts/verify_so1_atomic_catalog_pricing.py": {"scripts/verify_so1_atomic_catalog_pricing.py"},
    "scripts/verify_pa0123_platform_administration.py": {
        "scripts/verify_pa0123_platform_administration.py",
        "scripts/verify_pa6_platform_administration_aggregate_freeze.py",
    },
    "scripts/verify_pa6_platform_administration_aggregate_freeze.py": {"scripts/verify_pa6_platform_administration_aggregate_freeze.py"},
}


def _json(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _canonical_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    return raw.replace(b"\r\n", b"\n") if path.suffix.casefold() in TEXT_SUFFIXES else raw


def _sha_path(path: Path) -> str:
    return hashlib.sha256(_canonical_bytes(path)).hexdigest()


def _replacement_map() -> dict[str, dict]:
    successor = _json("pc8_h1b_private_route_admission_successor.json")
    section = successor.get("full_regression_successor")
    if not isinstance(section, dict) or section.get("authority") != R2_AUTHORITY:
        raise RuntimeError("full-regression successor authority missing")
    entries = section.get("replacements")
    if not isinstance(entries, list):
        raise RuntimeError("full-regression replacement list missing")
    result = {entry.get("path"): entry for entry in entries}
    if None in result or len(result) != len(entries):
        raise RuntimeError("full-regression replacement paths invalid or duplicated")
    return result


def require_full_regression_replacement(
    relative: str, historical_sha256: str, descendant_sha256: str | None, consumer: str
) -> dict:
    entry = _replacement_map().get(relative)
    if entry is None:
        raise RuntimeError(f"PC8_SUCCESSOR_REPLACEMENT_UNLISTED={relative}")
    if entry.get("historical_sha256") != historical_sha256:
        raise RuntimeError(f"PC8_SUCCESSOR_HISTORICAL_HASH_MISMATCH={relative}")
    if entry.get("descendant_sha256") != descendant_sha256:
        raise RuntimeError(f"PC8_SUCCESSOR_DESCENDANT_HASH_MISMATCH={relative}")
    consumers = entry.get("authorized_consumers")
    if not isinstance(consumers, list) or consumer not in consumers:
        raise RuntimeError(f"PC8_SUCCESSOR_UNAUTHORIZED_CONSUMER={consumer}:{relative}")
    return entry


def _candidate_paths() -> set[str]:
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "diff", "--name-only", BASE], text=True
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard"], text=True
    ).splitlines()
    return {
        value.strip().replace("\\", "/")
        for value in (*tracked, *untracked)
        if value.strip()
    }


def _sha_without_successor_bypasses(relative: str) -> str:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    private_needle = f'            or path.startswith("{PRIVATE_PREFIX}")\n'
    nce_needle = f'            or path == "{NCE_EVENT_PATH}"\n'
    if text.count(private_needle) != 1 or text.count(nce_needle) != 1:
        raise RuntimeError(f"successor bypass count mismatch={relative}")
    restored = text.replace(private_needle, "", 1).replace(nce_needle, "", 1).encode("utf-8")
    return hashlib.sha256(restored).hexdigest()


def verify() -> dict:
    from core.platform.release_integrity import (
        release_chain,
        verify_historical_release,
        verify_latest_release,
    )

    successor = _json("pc8_h1b_private_route_admission_successor.json")
    pc7 = _json("pc7_release_manifest.json")
    pc8 = _json("pc8_release_manifest.json")
    h1 = json.loads(
        (ROOT / "contracts/restaurant/v1/h1_release_manifest.json").read_text(encoding="utf-8")
    )

    if successor.get("release") != "XBOS_PLATFORM_CORE_PC8_H1B_PRIVATE_ROUTE_ADMISSION_SUCCESSOR":
        raise RuntimeError("PC8 successor identity mismatch")
    if successor.get("release_class") != "POSTHOC_RELEASE_INTEGRITY_SUCCESSOR_ONLY":
        raise RuntimeError("PC8 successor class mismatch")
    if successor.get("source_base") != BASE or successor.get("release_sequence") != 8:
        raise RuntimeError("PC8 source base or sequence mismatch")
    if successor.get("previous_head") != "ia0_neutral_interaction_authority_045":
        raise RuntimeError("PC8 previous head mismatch")
    if successor.get("accepted_head") != "ia0_neutral_interaction_authority_045":
        raise RuntimeError("PC8 accepted head mismatch")
    if successor.get("migration") is not None or successor.get("migration_count") != 0:
        raise RuntimeError("PC8 migration authority invented")
    if any(
        successor.get(key) is not False
        for key in (
            "new_platform_business_authority",
            "new_platform_schema_authority",
            "finance_authority_change",
            "inventory_authority_change",
            "caller_x_tenant_code_authority",
            "caller_x_branch_code_authority",
            "development_fallback_authority",
            "request_state_tenant_id_preset",
            "request_state_branch_id_preset",
        )
    ):
        raise RuntimeError("PC8 authority boundary changed")

    immutable = successor["historical_manifest_sha256"]
    for number in range(1, 8):
        path = CONTRACTS / f"pc{number}_release_manifest.json"
        if _sha_path(path) != immutable[f"pc{number}"]:
            raise RuntimeError(f"PC{number} immutable release manifest changed")

    chain = release_chain(ROOT)
    if [number for number, _ in chain] != list(range(1, 9)):
        raise RuntimeError("release chain is not exactly PC1 through PC8")
    if verify_latest_release(ROOT) != {"latest": 8, "artifact_count": 40}:
        raise RuntimeError("PC8 is not exact current latest release")

    if (
        pc8.get("release") != "XBOS_PLATFORM_CORE_PC8_H1B_PRIVATE_ROUTE_ADMISSION_SUCCESSOR"
        or pc8.get("source_base") != BASE
        or pc8.get("previous_head") != "ia0_neutral_interaction_authority_045"
        or pc8.get("accepted_head") != "ia0_neutral_interaction_authority_045"
        or pc8.get("migration_count") != 0
        or pc8.get("fingerprint_policy", {}).get("release_sequence") != 8
    ):
        raise RuntimeError("PC8 release metadata mismatch")

    pc7_paths = {item["path"] for item in pc7["artifacts"]}
    expected_artifacts = pc7_paths | EXTRA_ARTIFACTS
    actual_artifacts = [item["path"] for item in pc8["artifacts"]]
    if len(actual_artifacts) != len(set(actual_artifacts)) or set(actual_artifacts) != expected_artifacts:
        raise RuntimeError("PC8 artifact set mismatch")
    if len(actual_artifacts) != 40:
        raise RuntimeError("PC8 artifact count is not 40")
    if "contracts/platform/v1/pc8_release_manifest.json" in actual_artifacts:
        raise RuntimeError("PC8 manifest self-hash forbidden")

    replacement_counts = {}
    for number in range(1, 8):
        key = f"historical_pc{number}_replacements"
        expected = pc8.get(key)
        if not isinstance(expected, list):
            raise RuntimeError(f"missing exact PC{number} replacement map")
        report = verify_historical_release(ROOT, number)
        if report["latest"] != 8 or report["replacement_count"] != len(expected):
            raise RuntimeError(f"PC{number} replacement-map resolution mismatch={report}")
        replacement_counts[number] = len(expected)

    private_line = f'path.startswith("{PRIVATE_PREFIX}")'
    nce_line = f'path == "{NCE_EVENT_PATH}"'
    for relative in (
        "core/middleware/auth_middleware.py",
        "core/middleware/tenant_middleware.py",
        "core/middleware/branch_middleware.py",
    ):
        current = (ROOT / relative).read_text(encoding="utf-8")
        if current.count(private_line) != 1 or current.count(nce_line) != 1:
            raise RuntimeError(f"successor admission missing or duplicated={relative}")
        if _sha_path(ROOT / relative) != COMBINED_MIDDLEWARE_SHA[relative]:
            raise RuntimeError(f"combined middleware hash mismatch={relative}")
        if _sha_without_successor_bypasses(relative) != successor["accepted_base_canonical_sha256"][relative]:
            raise RuntimeError(f"non-successor middleware behavior changed={relative}")

    if successor.get("tenant_authority") != "IA0_CONTEXT_BINDING_AT_ROUTER_SERVICE_LAYER":
        raise RuntimeError("tenant authority changed")
    if successor.get("structural_authority") != "PC1":
        raise RuntimeError("structural authority changed")

    changed = _candidate_paths()
    historical_authorized = set(h1["authorized_paths"])
    succession = successor.get("candidate_path_succession")
    if not isinstance(succession, dict):
        raise RuntimeError("missing candidate-path succession evidence")
    expected_succession_keys = {
        "historical_h1_authorized_path_count",
        "successor_addition_count",
        "current_candidate_path_count",
        "successor_additions",
    }
    if set(succession) != expected_succession_keys:
        raise RuntimeError("candidate-path succession shape mismatch")
    additions = set(succession["successor_additions"])
    if succession["historical_h1_authorized_path_count"] != 26 or len(historical_authorized) != 26:
        raise RuntimeError("historical H1 authorized path count changed")
    if succession["successor_addition_count"] != 6 or len(additions) != 6:
        raise RuntimeError("successor addition count mismatch")
    if historical_authorized & additions:
        raise RuntimeError("candidate-path succession overlaps historical H1 path set")
    prior_current = historical_authorized | additions
    if succession["current_candidate_path_count"] != 32 or len(prior_current) != 32:
        raise RuntimeError("prior candidate path count mismatch")

    r2 = successor.get("full_regression_successor")
    expected_r2_keys = {
        "authority", "prior_candidate_path_count", "successor_addition_count",
        "current_candidate_path_count", "successor_additions", "main_collection",
        "ia0_collection", "combined_collection", "historical_manifest_rewrites", "replacements",
    }
    if not isinstance(r2, dict) or set(r2) != expected_r2_keys or r2.get("authority") != R2_AUTHORITY:
        raise RuntimeError("full-regression successor shape mismatch")
    r2_additions = set(r2["successor_additions"])
    if r2["prior_candidate_path_count"] != 32 or r2["successor_addition_count"] != 7:
        raise RuntimeError("full-regression successor count mismatch")
    if r2_additions != R2_ADDITIONS or prior_current & r2_additions:
        raise RuntimeError("full-regression successor additions mismatch")
    expected_current = prior_current | r2_additions
    if r2["current_candidate_path_count"] != 39 or len(expected_current) != 39:
        raise RuntimeError("full-regression current candidate count mismatch")
    if (r2["main_collection"], r2["ia0_collection"], r2["combined_collection"]) != (2295, 15, 2310):
        raise RuntimeError("full-regression collection law mismatch")
    if r2["historical_manifest_rewrites"] != 0:
        raise RuntimeError("historical manifest rewrite authority invented")

    nce = successor.get("nce_h1b_additive_successor")
    expected_nce_keys = {
        "authority", "common_parent", "nce_commit", "nce_tag", "h1b_commit", "h1b_tag",
        "prior_h1b_candidate_path_count", "nce_unique_addition_count",
        "current_combined_candidate_path_count", "nce_unique_additions",
        "overlap_count", "overlap_sha256", "historical_manifest_rewrites",
    }
    if not isinstance(nce, dict) or set(nce) != expected_nce_keys:
        raise RuntimeError("NCE-H1B successor shape mismatch")
    if (
        nce["authority"] != R1_AUTHORITY
        or nce["common_parent"] != BASE
        or nce["nce_commit"] != "92f6dbc7db37f5e1e8cf9c3e497e5be57a03b611"
        or nce["nce_tag"] != "xbos-nce-r1-r1-e2-r1-xafpay-v2-event-consumer-accepted-20260923"
        or nce["h1b_commit"] != "d064f617489febfa95a6bab43cb96a9a8125dedd"
        or nce["h1b_tag"] != "xbos-g02-c3-h1b-customer-channel-cross-process-binding-accepted-20260925"
    ):
        raise RuntimeError("NCE-H1B accepted source identity mismatch")
    additions_list = nce["nce_unique_additions"]
    additions = {item.get("path"): item.get("sha256") for item in additions_list if isinstance(item, dict)}
    if (
        len(additions) != len(additions_list)
        or additions != NCE_UNIQUE_SHA
        or nce["prior_h1b_candidate_path_count"] != 39
        or nce["nce_unique_addition_count"] != 7
        or nce["current_combined_candidate_path_count"] != 46
        or nce["overlap_count"] != 3
        or nce["overlap_sha256"] != COMBINED_MIDDLEWARE_SHA
        or nce["historical_manifest_rewrites"] != 0
    ):
        raise RuntimeError("NCE-H1B succession evidence mismatch")
    for relative, expected_hash in NCE_UNIQUE_SHA.items():
        if _sha_path(ROOT / relative) != expected_hash:
            raise RuntimeError(f"NCE accepted source hash mismatch={relative}")
    combined_current = expected_current | set(NCE_UNIQUE_SHA)
    if expected_current & set(NCE_UNIQUE_SHA) or len(combined_current) != 46:
        raise RuntimeError("NCE-H1B unique succession overlap/count mismatch")
    if changed != combined_current:
        raise RuntimeError(
            f"candidate-path succession mismatch missing={sorted(combined_current-changed)} "
            f"extra={sorted(changed-combined_current)}"
        )

    replacement_map = _replacement_map()
    if set(replacement_map) != set(REPLACEMENT_HISTORICAL_SHA):
        raise RuntimeError("full-regression replacement path set mismatch")
    for relative, entry in replacement_map.items():
        if set(entry) != {"path", "historical_sha256", "descendant_sha256", "authorized_consumers"}:
            raise RuntimeError(f"replacement shape mismatch={relative}")
        if entry["historical_sha256"] != REPLACEMENT_HISTORICAL_SHA[relative]:
            raise RuntimeError(f"replacement historical hash changed={relative}")
        if set(entry["authorized_consumers"]) != REPLACEMENT_CONSUMERS[relative]:
            raise RuntimeError(f"replacement consumer set changed={relative}")
        path = ROOT / relative
        actual = _sha_path(path) if path.is_file() else None
        if entry["descendant_sha256"] != actual:
            raise RuntimeError(f"replacement descendant hash stale={relative}")
    if "core/platform/release_integrity.py" in changed:
        raise RuntimeError("release_integrity.py mutation forbidden")
    if any(
        path.startswith("contracts/platform/v1/pc") and path.endswith("_release_manifest.json")
        and path != "contracts/platform/v1/pc8_release_manifest.json"
        for path in changed
    ):
        raise RuntimeError("historical Platform Core release manifest mutation forbidden")
    if any(path.startswith("core/domain/finance/") or path.startswith("core/domain/inventory/") for path in changed):
        raise RuntimeError("finance or inventory authority changed")
    migration_changes = {path for path in changed if path.startswith("alembic_neutral/")}
    if migration_changes != H1B_MIGRATION_PATHS:
        raise RuntimeError(f"unexpected migration source change={sorted(migration_changes)}")

    pc7_report = verify_historical_release(ROOT, 7)
    if pc7_report["latest"] != 8:
        raise RuntimeError("PC7 did not transition to immutable historical milestone")

    return {
        "status": "PASS",
        "release_sequence": 8,
        "artifact_count": 40,
        "historical_authorized_path_count": 26,
        "successor_addition_count": 6,
        "r2_successor_addition_count": 7,
        "h1b_current_candidate_path_count": 39,
        "nce_unique_addition_count": 7,
        "overlap_count": 3,
        "current_candidate_path_count": 46,
        "full_regression_replacement_count": len(REPLACEMENT_HISTORICAL_SHA),
        "main_collection": 2295,
        "ia0_collection": 15,
        "combined_collection": 2310,
        "private_auth_bypass": "PASS",
        "private_tenant_bypass": "PASS",
        "private_branch_bypass": "PASS",
        "pc1_to_pc7_manifest_mutation": False,
        "migration_count": 0,
        "finance_authority_change": False,
        "inventory_authority_change": False,
        "replacement_counts": replacement_counts,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
