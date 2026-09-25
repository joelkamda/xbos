"""Immutable PC7 milestone and cumulative historical resolution through PC8."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.platform.release_integrity import (
    canonical_sha256,
    release_chain,
    verify_historical_release,
    verify_latest_release,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/platform/v1"
EXPECTED_ARTIFACTS = {
    "XBOS_PC7_INSTALL_AND_VERIFY.txt",
    "XBOS_PC7_RUN_ACCEPTANCE.cmd",
    "contracts/platform/v1/pc0_module_map.json",
    "contracts/platform/v1/pc0_data_authority_register.json",
    "contracts/platform/v1/pc0_reference_authority_migration_register.json",
    "contracts/platform/v1/pc0_dependency_policy.json",
    "contracts/platform/v1/pc0_public_private_interfaces.json",
    "contracts/platform/v1/pc0_frozen_finance_inventory.json",
    "contracts/platform/v1/pc0_release_manifest.json",
    "contracts/platform/v1/pc6_public_contract_inventory.json",
    "core/platform/architecture_contract.py",
    "core/platform/release_integrity.py",
    "contracts/platform/v1/pc7_neutral_interaction_authority.json",
    "contracts/platform/v1/pc7_public_interfaces.json",
    "core/platform/interaction/__init__.py",
    "core/platform/interaction/contracts.py",
    "core/platform/interaction/sql_repository.py",
    "alembic_neutral/sql/ia0_neutral_interaction_authority_down.sql",
    "alembic_neutral/sql/ia0_neutral_interaction_authority_up.sql",
    "alembic_neutral/versions/ia0_neutral_interaction_authority_045.py",
    "docs/platform_core/PC7_NEUTRAL_INTERACTION_AUTHORITY.md",
    "docs/platform_core/adr/0011_PC7_NEUTRAL_INTERACTION_AUTHORITY_REGISTRATION.md",
    "scripts/verify_pc6_neutral_platform.py",
    "scripts/verify_pc7_neutral_interaction_authority.py",
    "tests/contracts/test_pc0_kernel_boundaries.py",
    "tests/contracts/test_ia0_neutral_interaction_contract_foundation.py",
    "tests/contracts/test_ia0_a2_persistence_foundation.py",
    "tests/contracts/test_pc4_cumulative_release_manifest_chain.py",
    "tests/contracts/test_pc5_cumulative_release_manifest_chain.py",
    "tests/contracts/test_pc6_cumulative_release_manifest_chain.py",
    "tests/contracts/test_pc6_neutral_platform_proof.py",
    "tests/contracts/test_pc7_neutral_interaction_authority.py",
    "tests/contracts/test_pc7_cumulative_release_manifest_chain.py",
}


def _json(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
def test_pc7_is_exact_immutable_historical_milestone_under_pc8():
    chain = release_chain(ROOT)
    assert [number for number, _ in chain] == list(range(1, 9))
    manifest = _json("pc7_release_manifest.json")
    assert manifest["release"] == "XBOS_PLATFORM_CORE_PC7"
    assert manifest["source_checkpoint"] == "b067d0a"
    assert manifest["previous_head"] == "pc5_identity_policy_audit_025"
    assert manifest["accepted_head"] == "ia0_neutral_interaction_authority_045"
    assert manifest["migration_count"] == 1
    assert manifest["fingerprint_policy"]["release_sequence"] == 7
    assert verify_latest_release(ROOT) == {"latest": 8, "artifact_count": 40}


def test_pc7_artifact_set_and_manifest_bytes_remain_immutable():
    manifest = _json("pc7_release_manifest.json")
    paths = [item["path"] for item in manifest["artifacts"]]
    assert len(paths) == len(set(paths)) == 33
    assert set(paths) == EXPECTED_ARTIFACTS
    raw = (CONTRACTS / "pc7_release_manifest.json").read_bytes().replace(b"\r\n", b"\n")
    successor = _json("pc8_h1b_private_route_admission_successor.json")
    assert hashlib.sha256(raw).hexdigest() == successor["historical_manifest_sha256"]["pc7"]


def test_every_historical_platform_release_resolves_exactly_through_pc8():
    pc8 = _json("pc8_release_manifest.json")
    reports = {number: verify_historical_release(ROOT, number) for number in range(1, 8)}
    assert {number: report["latest"] for number, report in reports.items()} == {
        number: 8 for number in range(1, 8)
    }
    assert {number: report["replacement_count"] for number, report in reports.items()} == {
        number: len(pc8[f"historical_pc{number}_replacements"])
        for number in range(1, 8)
    }
def test_pc6_historical_replacement_map_is_exact():
    manifest = _json("pc7_release_manifest.json")
    actual = manifest["historical_pc6_replacements"]
    expected = [
        {
            "path": "contracts/platform/v1/pc0_dependency_policy.json",
            "historical_sha256": "45352f7ebc1727968c819182b53cb15f57d7ed2baa270546530a5a65bed23e78",
            "descendant_sha256": "6fafc84f76e26422071d04c17b1944e77a6e8fa90f446771ee9c8fa897db5599",
        },
        {
            "path": "contracts/platform/v1/pc0_module_map.json",
            "historical_sha256": "526f4a2c1ddf2eacf2f541b43d68b7881f48582e4fcab6e1efbbf14a8c3a6a21",
            "descendant_sha256": "8a4396fa851e5cd9e719cf4948d7c92f2b965d41014dad83e21039500ae08840",
        },
        {
            "path": "contracts/platform/v1/pc0_public_private_interfaces.json",
            "historical_sha256": "bd871ee69a3f29fe17a11080d6596b552c5743f186bc794b63dbc900f145bc06",
            "descendant_sha256": "7a7bbe78c152878cd6fae03be98add995eaf310265c8cb5c642ad8ccf727e61d",
        },
        {
            "path": "contracts/platform/v1/pc0_release_manifest.json",
            "historical_sha256": "84b18a78630bea3657e07c044e4488bb588f1e2d3a7b0c64b38c2a7054301244",
            "descendant_sha256": "80a8a746de5ec584927f01723a22b65269389a45e8da1002d8a03bbf58525cc3",
        },
        {
            "path": "scripts/verify_pc6_neutral_platform.py",
            "historical_sha256": "6da17ced669533eeff4d47737b6e38d24f75762b4301a9abbcc7639611da9273",
            "descendant_sha256": "5249eab96356b5c20d374d04a59855be9519489eb58770209b4b92d0fc6c1dba",
        },
        {
            "path": "tests/contracts/test_pc6_cumulative_release_manifest_chain.py",
            "historical_sha256": "0a4aaa807a0030cfee0d0f0cb8515f2dd6782585361dc691bb75aa79b3b83940",
            "descendant_sha256": "52438e537b4afc58091bb76fc7600d960be03f3dc2f97a999c6f11752cbfc720",
        },
    ]
    assert actual == expected


def test_pc6_release_and_public_inventory_remain_immutable_historical_artifacts():
    assert canonical_sha256(
        CONTRACTS / "pc6_release_manifest.json",
        relative_path="contracts/platform/v1/pc6_release_manifest.json",
        repository_root=ROOT,
    ) == "cb384cc1d1c79f7874e240ecdc85ff6cb8f9d069e5f28c7f8a9d96dda05e6d5d"
    inventory = _json("pc6_public_contract_inventory.json")
    assert {item["authority"] for item in inventory["interfaces"]} == {
        "PC1", "PC2", "PC3", "PC4", "PC5",
    }
def test_pc0_release_refresh_identity_is_exact():
    path = CONTRACTS / "pc0_release_manifest.json"
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    assert len(raw) == 3925
    assert hashlib.sha256(raw).hexdigest() == (
        "80a8a746de5ec584927f01723a22b65269389a45e8da1002d8a03bbf58525cc3"
    )


def test_pc7_operator_surfaces_exist_a3_is_undefined_and_self_hash_cycle_is_absent():
    manifest = _json("pc7_release_manifest.json")
    authority = _json("pc7_neutral_interaction_authority.json")
    assert (ROOT / "XBOS_PC7_INSTALL_AND_VERIFY.txt").is_file()
    assert (ROOT / "XBOS_PC7_RUN_ACCEPTANCE.cmd").is_file()
    assert authority["registration"] == {
        "class": "FULL_PLATFORM_REGISTRATION",
        "release_manifest": "pc7_release_manifest.json",
        "release_freeze": True,
    }
    assert authority["a3_definition"] == "NOT_YET_REPOSITORY_AUTHORITY"
    release_sha = hashlib.sha256(
        (CONTRACTS / "pc7_release_manifest.json").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        if path.suffix.casefold() in {
            ".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"
        }:
            assert release_sha not in path.read_text(encoding="utf-8", errors="ignore")
