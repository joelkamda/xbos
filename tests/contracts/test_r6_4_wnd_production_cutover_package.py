from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from restaurant.r6.production_cutover import (
    CutoverFingerprint,
    assert_legacy_truth_preserved,
    rollback_mode,
)

ROOT = Path(__file__).resolve().parents[2]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_r6_4_is_planning_only_and_cannot_authorize_live_cutover():
    c = load("contracts/restaurant/v1/r6_4_production_cutover_package_authority.json")
    assert c["source_checkpoint"] == "b97d3850b120aff92261ad9edcb3bf3151ebbcb3"
    assert c["production_write_authorized"] is False
    assert c["production_schema_migration_authorized"] is False
    assert c["writer_routing"] == "unchanged"
    assert c["legacy_writer_retirement_allowed"] is False
    assert c["live_cutover_authorized"] is False
    assert c["r6_5_target_head"] == "r63_legacy_inventory_writer_compat_044"


def test_r6_5_runbook_defers_retirement_and_has_explicit_operational_commit():
    c = load("contracts/restaurant/v1/r6_4_r6_5_cutover_runbook.json")
    ids = [p["id"] for p in c["phases"]]
    assert ids[0] == "P0_AUTHORIZATION"
    assert ids[-1] == "P8_HYPERCARE_ENTRY"
    assert c["point_of_operational_commit"] == "first successful business write after P7 reopen"
    assert c["writer_retirement"] == "deferred until post-cutover hypercare acceptance"
    assert c["r6_5_live_cutover_authorized_by_r6_4"] is False


def test_post_write_rollback_preserves_live_database():
    assert rollback_mode(reopened=False, post_cutover_business_write=False) == "FINAL_BACKUP_RESTORE_PERMITTED"
    assert rollback_mode(reopened=True, post_cutover_business_write=False) == "FINAL_BACKUP_RESTORE_AFTER_REENTERING_MAINTENANCE"
    assert rollback_mode(reopened=True, post_cutover_business_write=True) == "PRESERVE_LIVE_DB_APPLICATION_ROLLBACK_ONLY"


def test_legacy_truth_comparator_is_exact():
    assert_legacy_truth_preserved({"sales": 2}, {"sales": 2}, {"total": "3.00"}, {"total": "3.00"})


def test_cutover_fingerprint_is_deterministic():
    a = CutoverFingerprint("h", {"b": 2, "a": 1}, {"x": "1.00"}, {"status": "active"})
    b = CutoverFingerprint("h", {"a": 1, "b": 2}, {"x": "1.00"}, {"status": "active"})
    assert a.digest() == b.digest()


def test_hypercare_sequence_places_f_track_before_fresh_wnd_and_olympia():
    c = load("contracts/restaurant/v1/r6_4_hypercare_retirement_boundary.json")
    seq = c["sequence"]
    assert seq.index("legacy writer/compatibility retirement") < seq.index("complete F-track")
    assert seq.index("complete F-track") < seq.index("fresh WND onboarding through official XBOS administration and templates")
    assert seq.index("fresh WND onboarding through official XBOS administration and templates") < seq.index("Olympia Lounge & Restaurant onboarding using the same official tools")
    assert c["retirement_during_r6_5"] is False


def test_r6_4_control_runtime_matches_authoritative_wnd_server():
    c = load("contracts/restaurant/v1/r6_4_production_cutover_package_authority.json")
    runtime = c["r6_4_control_runtime"]
    assert runtime["python"] == "3.13.5"
    assert runtime["platform"] == "Windows"
    assert runtime["timezone_database"] == "tzdata==2025.2"
    assert runtime["timezone_required"] == "Africa/Douala"

    runner = (ROOT / "XBOS_R6_4_RUN_ACCEPTANCE.cmd").read_text(encoding="utf-8")
    assert 'Python 3.13.5' in runner
    assert "Africa/Douala" in runner
    assert "R6_4_CONTROL_RUNTIME=PASS" in runner

    req = (ROOT / "requirements-r6-4-control.txt").read_text(encoding="utf-8")
    assert "tzdata==2025.2" in req


def test_r6_4_registers_r63_inventory_compatibility_as_exact_so3_descendant():
    inventory = load("contracts/platform/v1/pc0_frozen_finance_inventory.json")
    rows = {
        item["path"]: item
        for item in inventory["authorized_non_finance_extensions"]
        if item["root"] == "alembic_neutral"
    }
    expected = {
        "versions/r63_legacy_inventory_writer_compat_044.py",
        "sql/r63_legacy_inventory_writer_compat_up.sql",
        "sql/r63_legacy_inventory_writer_compat_down.sql",
    }
    assert expected.issubset(rows)
    for path in expected:
        assert rows[path]["owner"] == "SO3"
        assert "Finance semantics and writer authority unchanged" in rows[path]["reason"]


def test_r6_4_cumulative_pc0_pc6_fingerprints_follow_r63_registration():
    import hashlib
    inv_path = ROOT / "contracts/platform/v1/pc0_frozen_finance_inventory.json"
    inv_sha = hashlib.sha256(inv_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert inv_sha == "18d8cdbdfcdc0edf8d566bbd27d353a1a61ff0fa33189efe48773b91f9de0e6d"

    pc0 = load("contracts/platform/v1/pc0_release_manifest.json")
    pc0_artifact = next(
        item for item in pc0["artifacts"]
        if item["path"] == "contracts/platform/v1/pc0_frozen_finance_inventory.json"
    )
    assert pc0_artifact["sha256"] == inv_sha

    pc0_path = ROOT / "contracts/platform/v1/pc0_release_manifest.json"
    pc0_sha = hashlib.sha256(pc0_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert pc0_sha == "0ba51c63cd41fb0366d7c7a6562af26693493ddb8b22ab63fb6065c06e4c8ee7"

    pc6 = load("contracts/platform/v1/pc7_release_manifest.json")
    for milestone in range(1, 7):
        replacements = pc6[f"historical_pc{milestone}_replacements"]
        inv = [item for item in replacements if item["path"] == "contracts/platform/v1/pc0_frozen_finance_inventory.json"]
        rel = next(item for item in replacements if item["path"] == "contracts/platform/v1/pc0_release_manifest.json")
        if milestone < 6:
            assert len(inv) == 1
            assert inv[0]["descendant_sha256"] == inv_sha
        else:
            assert len(inv) == 0
        assert rel["descendant_sha256"] == pc0_sha
    pc6_artifact = next(
        item for item in pc6["artifacts"]
        if item["path"] == "contracts/platform/v1/pc0_release_manifest.json"
    )
    assert pc6_artifact["sha256"] == pc0_sha



def test_r6_4_downstream_release_integrity_chain_is_current():
    import hashlib

    def canonical(path):
        raw = path.read_bytes().replace(b'\r\n', b'\n')
        return hashlib.sha256(raw).hexdigest()

    expected = {
        'contracts/shared_operations/v1/so1_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json'],
        'contracts/shared_operations/v1/so2_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json'],
        'contracts/shared_operations/v1/so3_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json'],
        'contracts/shared_operations/v1/so4_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json'],
        'contracts/shared_operations/v1/so5_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json'],
        'contracts/shared_operations/v1/so6_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json'],
        'contracts/shared_operations/v1/so7_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json'],
        'contracts/shared_operations/v1/so8_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json'],
        'contracts/shared_operations/v1/so9_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json'],
        'contracts/shared_operations/v1/so10_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json'],
        'contracts/shared_operations/v1/so_aggregate_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json'],
        'contracts/packs/v1/pk0123_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/packs/v1/pk456_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/packs/v1/pk_aggregate_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json'],
        'contracts/platform_admin/v1/pa0123_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/platform_admin/v1/pa45_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/platform_admin/v1/pa6_release_manifest.json': ['contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json'],
        'contracts/platform/v1/sc41_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/platform_admin/v1/pa6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/restaurant/v1/r1_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/platform/v1/sc41_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/platform_admin/v1/pa6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/restaurant/v1/r2_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc7_release_manifest.json', 'contracts/platform/v1/sc41_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/platform_admin/v1/pa6_release_manifest.json', 'contracts/restaurant/v1/r1_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
    }

    for manifest_path, changed_paths in expected.items():
        manifest = load(manifest_path)
        by_path = {item["path"]: item for item in manifest["artifacts"]}
        for artifact_path in changed_paths:
            assert by_path[artifact_path]["sha256"] == canonical(ROOT / artifact_path)


def test_r6_4_full_regression_is_hard_isolated_from_production():
    authority = load("contracts/restaurant/v1/r6_4_production_cutover_package_authority.json")
    safety = authority["full_regression_safety"]
    assert safety["production_database"] == "xbos"
    assert safety["disposable_regression_database"] == "xbos_track_b_test"
    assert safety["production_database_supplied_to_pytest"] is False
    assert safety["database_restore_allowed"] == ["xbos_track_b_test"]
    assert safety["python_dont_write_bytecode"] is True
    source = (ROOT / "scripts/run_r6_4_isolated_full_regression.py").read_text(encoding="utf-8")
    assert 'TEST_DATABASE = "xbos_track_b_test"' in source
    assert 'PRODUCTION_DATABASE = "xbos"' in source
    assert 'env["DATABASE_URL"] = url.set(database=TEST_DATABASE)' in source
    assert 'env["PYTHONDONTWRITEBYTECODE"] = "1"' in source
    assert 'DROP DATABASE IF EXISTS "{TEST_DATABASE}"' in source
    assert 'CREATE DATABASE "{TEST_DATABASE}"' in source


def test_r6_4_r61_certification_helper_remains_frozen_after_manifest_evolution():
    import scripts.verify_r6_1_wnd_rehearsal_adoption as verifier
    expected = (
        "4107bd79ec1f0926b5ecfd8e0dede083712258ad91fa4102886d820a6dabfb8f",
        "930303ec7d4d226f53abf12fd395a3db456318378b148134f8366e93b422c793",
        "6bea73750881a64d7e7a40e848c88e3a23c669ebddc350fa6e99325eeb44eff2",
        "53f0ff77ad7a822d0fd469fb7ca2bf6f515e6c8b5b1450c0c065362c17b5386a",
        "0df725876b9f605e6410cd4bea7e5f62b7e3aa6c28f6c907b0a570468de0ce93",
        "4a8f6d2a0e1b94303083d0c531c26c375c2d74e6d2844e6690e60782f9b03624",
        "fe3c8a84bf225300d5b13da4e3daa9dc02b55ddbd79ec5f0226f20bd92527a08",
    )
    assert verifier._r4_evidence_hashes() == expected
    source = (ROOT / "scripts/verify_r6_1_wnd_rehearsal_adoption.py").read_text(encoding="utf-8")
    helper = source[source.index("def _r4_evidence_hashes"):source.index("def _verify_release_manifest")]
    assert "FROZEN_R4_CERTIFICATION_EVIDENCE_SHA256" in helper
    assert "read_bytes" not in helper


def test_r6_4_control_runtime_requires_bcrypt_backend():
    c = load("contracts/restaurant/v1/r6_4_production_cutover_package_authority.json")
    runtime = c["r6_4_control_runtime"]
    assert runtime["passlib"] == "1.7.4"
    assert runtime["password_hash_backend"] == "bcrypt==4.2.1"
    assert runtime["password_hash_backend_required_for_characterization_suite"] is True

    req = (ROOT / "requirements-r6-4-control.txt").read_text(encoding="utf-8")
    assert "bcrypt==4.2.1" in req

    runner = (ROOT / "XBOS_R6_4_RUN_ACCEPTANCE.cmd").read_text(encoding="utf-8")
    assert "passlib_bcrypt.get_backend()=='bcrypt'" in runner
    assert "R6_4_BCRYPT_BACKEND=PASS" in runner


def test_r6_4_diagnostic_ports_are_collision_safe():
    authority = load("contracts/restaurant/v1/r6_4_production_cutover_package_authority.json")
    ports = authority["diagnostic_runtime_ports"]
    assert ports["binding"] == "127.0.0.1 only"
    assert ports["reference_candidates"] == [8002, 18002, 28002, 38002]
    assert ports["track_b_candidates"] == [8004, 18004, 28004, 38004]
    assert ports["selection"] == "first free candidate"
    assert ports["occupied_port_action"] == "LEAVE_UNTOUCHED"
    assert ports["production_ports_touched"] == []
    assert ports["production_services_stopped"] is False

    source = (ROOT / "scripts/verify_r6_4_wnd_production_cutover_package.py").read_text(encoding="utf-8")
    assert "def _select_free_port(" in source
    assert 'reference_port = _select_free_port(REFERENCE_PORT_CANDIDATES, "REFERENCE")' in source
    assert 'track_b_port = _select_free_port(TRACK_B_PORT_CANDIDATES, "TRACK_B")' in source
    assert "original_r63_backend_port = r63.BACKEND_PORT" in source
    assert "r63.BACKEND_PORT = original_r63_backend_port" in source
    assert "_track_b_runtime_read_smoke(track_b_port)" in source



def test_r6_4_option1_wnd_api_bridge_is_explicit_and_complete():
    bridge = load("contracts/restaurant/v1/r6_4_wnd_api_compatibility_bridge.json")
    assert bridge["mode"] == "temporary_hypercare_adapter"
    assert bridge["wnd_tenant_id"] == 2
    assert bridge["neutral_default_entrypoint"] == "main:app"
    assert bridge["wnd_hypercare_entrypoint"] == "restaurant.r6.wnd_compat_runtime:app"
    assert bridge["track_a_only_route_count"] == 26
    routes = {(r["method"], r["path"]) for r in bridge["track_a_only_routes"]}
    required = {
        ("GET", "/kernel/customers"),
        ("GET", "/kernel/payments/activity"),
        ("GET", "/kernel/reports/debt"),
        ("GET", "/kernel/inventory/reconciliation"),
        ("POST", "/kernel/inventory/reconciliation/close"),
        ("POST", "/kernel/inventory/waste"),
        ("PATCH", "/kernel/accounting/accounts/ar/{ar_id}/identity"),
        ("POST", "/kernel/payments/standalone/receive-income"),
        ("POST", "/kernel/payments/standalone/pay-expense"),
        ("POST", "/kernel/payments/standalone/transfer"),
    }
    assert required <= routes
    assert bridge["retirement"] == "post_hypercare_separate_approved_legacy_retirement_plan"


def test_r6_4_option1_does_not_modify_neutral_main_entrypoint():
    startup = (ROOT / "startup.py").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    runtime = (ROOT / "restaurant/r6/wnd_compat_runtime.py").read_text(encoding="utf-8")
    assert "wnd_api_compat" not in startup
    assert "wnd_api_compat" not in main
    assert 'app = FastAPI(title="XBOS Kernel — WND R6 Compatibility Hypercare")' in runtime
    assert runtime.index("app.include_router(wnd_r6_compat_router)") < runtime.index("app.include_router(kernel_router)")


def test_r6_4_option1_bridge_routes_fail_closed_outside_wnd():
    source = (ROOT / "restaurant/r6/wnd_api_compat/router.py").read_text(encoding="utf-8")
    customers = (ROOT / "restaurant/r6/wnd_api_compat/customers_router.py").read_text(encoding="utf-8")
    ar = (ROOT / "restaurant/r6/wnd_api_compat/ar_compat.py").read_text(encoding="utf-8")
    assert 'int(ctx.get("tenant_id") or 0) != 2' in source
    assert 'tenant_id != 2' in customers
    assert 'tenant_id != 2' in ar
    assert 'Compatibility route not available' in source


def test_r6_4_option1_rehearsal_exercises_compat_runtime_and_full_bridge():
    source = (ROOT / "scripts/verify_r6_4_wnd_production_cutover_package.py").read_text(encoding="utf-8")
    assert "restaurant.r6.wnd_compat_runtime:app" in source
    assert "r6_4_wnd_api_compatibility_bridge.json" in source
    assert 'bridge["track_a_only_routes"]' in source


def test_r6_4_wnd_compat_openapi_payload_annotations_are_eager():
    source = (ROOT / "restaurant/r6/wnd_api_compat/router.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" not in source
    for payload_type in ("ManualIncomePayload", "ExpensePayload", "CashMovementPayload"):
        assert f"payload: {payload_type}" in source

    authority = load("contracts/restaurant/v1/r6_4_production_cutover_package_authority.json")
    binding = authority["wnd_api_bridge_openapi_binding"]
    assert binding["compatibility_router_annotations"] == "EAGER_RUNTIME_TYPES"
    assert binding["future_annotations_in_compatibility_route_module"] is False
    assert binding["neutral_core_decorator_changed"] is False
    assert binding["neutral_main_changed"] is False


HISTORICAL_R6_4_OMISSIONS = {
    "R6_4_REVISION_9_WND_COMPAT_OPENAPI_BINDING.txt": (1670, "0860f93386e915c236564370d9437b128ab0ec40e85b546e12418dbdd7436fd6"),
    "R6_4_REVISION_8_WND_API_COMPATIBILITY_BRIDGE.txt": (2220, "317363db4ad8f904197555cd72465da2ac0a79ade51059f9048812fffb5f9139"),
    "R6_4_REVISION_7_COLLISION_SAFE_DIAGNOSTIC_PORTS.txt": (1233, "ea45e8ebb8e9439da29fb2ee8aa5beb52198faef9f013d843b952e93a6ec9d9c"),
    "R6_4_REVISION_6_BCRYPT_CONTROL_BACKEND.txt": (1022, "d6b7b063d6253d87687412d49e220523e0c3d01a5d2db884cb6adf88bccec935"),
    "R6_4_REVISION_5_ISOLATED_FULL_REGRESSION.txt": (1265, "14f2798384f36d2308d584b356bb801315be0f848bcf67db32eafe098608d8b2"),
    "R6_4_REVISION_4_DOWNSTREAM_RELEASE_INTEGRITY_CHAIN.txt": (1743, "2fd61835d14cac9dfb8199ad0e6b0d1cd40bb5b07c11ad2d87a3264a451aeff3"),
    "R6_4_REVISION_3_CUMULATIVE_PLATFORM_INTEGRITY.txt": (1962, "7149ba7d9cc3660f467f30f0cc53d0711d7e592f25ac51cdfc13ec59a4969283"),
    "R6_4_REVISION_2_WND_SERVER_RUNTIME.txt": (1034, "2e379014e41dc43ba24ca66fa864f544a3efe9afbfaed5bed6995f9fbfc37b0a"),
}


def canonical_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(bytes((13, 10)), b"\n")).hexdigest()


def git_show_bytes(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout


def test_r6_4_descendant_correction_contract_records_exact_historical_omissions():
    correction = load("contracts/restaurant/v1/r6_4_freeze_integrity_correction.json")
    assert correction["correction_class"] == "DESCENDANT_FREEZE_INTEGRITY_CORRECTION"
    assert correction["original_freeze_commit"] == "330694145cb1d06ea915c3c484451f664ebd75f3"
    assert correction["original_freeze_tag"] == "restaurant-r6-5-production-forward-baseline-v1-20260917"
    assert correction["original_install_manifest_sha256"] == "3ff1cf7cba91cd6391bd8d6f2a9d951c262379f8bc03c5799ff3991d78df09e0"
    assert correction["original_release_manifest_sha256"] == "cc0850be82e13c2ff3c4f8944eaf17ac3b58b733f8381ebcfd8a2423afb4e2ca"
    assert correction["historical_omission_count"] == 8
    rows = {row["path"]: row for row in correction["historical_omissions"]}
    assert set(rows) == set(HISTORICAL_R6_4_OMISSIONS)
    for path, (size, sha256) in HISTORICAL_R6_4_OMISSIONS.items():
        assert rows[path]["size"] == size
        assert rows[path]["sha256"] == sha256
        assert rows[path]["semantic_evidence"] == "COMPLETE"
        assert rows[path]["historical_artifact_byte_identity"] == "UNRECOVERABLE"
        assert rows[path]["underlying_semantics"] == "INDEPENDENTLY_PROVEN"
        assert rows[path]["supporting_paths"]


def test_r6_4_descendant_correction_preserves_original_freeze_identity_and_manifests():
    correction = load("contracts/restaurant/v1/r6_4_freeze_integrity_correction.json")
    commit = correction["original_freeze_commit"]
    tag_target = subprocess.run(
        ["git", "rev-parse", correction["original_freeze_tag"] + "^{}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert tag_target == commit
    assert canonical_sha(ROOT / "R6_4_INSTALL_MANIFEST.txt") == correction["original_install_manifest_sha256"]
    install = git_show_bytes(commit, "R6_4_INSTALL_MANIFEST.txt")
    release = git_show_bytes(commit, "contracts/restaurant/v1/r6_4_release_manifest.json")
    assert hashlib.sha256(install.replace(bytes((13, 10)), b"\n")).hexdigest() == correction["original_install_manifest_sha256"]
    assert hashlib.sha256(release.replace(bytes((13, 10)), b"\n")).hexdigest() == correction["original_release_manifest_sha256"]


def test_r6_4_descendant_correction_has_zero_recovery_and_no_authority_expansion():
    correction = load("contracts/restaurant/v1/r6_4_freeze_integrity_correction.json")
    assert correction["byte_identical_recovery_count"] == 0
    assert correction["deterministic_regeneration_count"] == 0
    assert correction["historical_artifact_byte_identity"] == "UNRECOVERABLE"
    assert correction["underlying_semantics"] == "INDEPENDENTLY_PROVEN"
    assert correction["historical_rewrite"] == "NO"
    assert correction["artifact_fabrication"] == "NO"
    assert set(correction["authority_changes"].values()) == {"NO"}


def test_r6_4_corrected_release_inventory_is_strict_and_contains_no_missing_historical_file():
    import scripts.verify_r6_4_wnd_production_cutover_package as verifier
    release = load("contracts/restaurant/v1/r6_4_release_manifest.json")
    paths = {row["path"] for row in release["artifacts"]}
    assert release["self_excluded"] is True
    assert release["source_checkpoint"] == "b97d3850b120aff92261ad9edcb3bf3151ebbcb3"
    assert release["artifact_count"] == len(release["artifacts"]) == 53
    assert not (set(HISTORICAL_R6_4_OMISSIONS) & paths)
    assert "contracts/restaurant/v1/r6_4_freeze_integrity_correction.json" in paths
    assert "R6_4_INSTALL_MANIFEST.txt" in paths
    assert verifier._verify_release_manifest(canonical_lf_identity=True) == 53


def test_r6_4_default_historical_branch_head_guards_remain_fail_closed_on_descendant_branch():
    import scripts.verify_r6_4_wnd_production_cutover_package as verifier
    source = (ROOT / "scripts/verify_r6_4_wnd_production_cutover_package.py").read_text(encoding="utf-8")
    assert 'EXPECTED_BRANCH = "restaurant/r6-4-wnd-production-cutover-package-runbook"' in source
    assert 'EXPECTED_HEAD = "b97d3850b120aff92261ad9edcb3bf3151ebbcb3"' in source
    with pytest.raises(RuntimeError, match="R6_4_WRONG_BRANCH"):
        verifier._static()


def test_r6_4_descendant_mode_requires_ancestor_tag_and_exact_correction_contract():
    import scripts.verify_r6_4_wnd_production_cutover_package as verifier
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    result = verifier._verify_descendant_freeze_integrity_correction(head)
    assert result["status"] == "PASS"
    assert result["original_freeze_tag_target"] == result["original_freeze_commit"]
    assert result["historical_omission_count"] == 8
    assert result["byte_identical_recovery_count"] == 0
    assert result["deterministic_regeneration_count"] == 0
    assert result["semantic_evidence_complete_count"] == 8


def test_r6_4_descendant_static_mode_preserves_all_other_r6_4_safety_laws():
    import scripts.verify_r6_4_wnd_production_cutover_package as verifier
    result = verifier._static(descendant_freeze_integrity_correction=True)
    assert result["status"] == "PASS"
    assert result["release_artifacts"] == 53
    assert result["production_writes"] == "NONE"
    assert result["writer_routing"] == "UNCHANGED"
    assert result["live_cutover_authorized"] is False
    assert result["descendant_freeze_integrity_correction"]["status"] == "PASS"


def historical_blob_identities(path: str) -> set[tuple[int, str]]:
    commits = subprocess.run(
        ["git", "log", "--all", "--format=%H", "--", path],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    identities: set[tuple[int, str]] = set()
    for commit in commits:
        cp = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True)
        if cp.returncode != 0:
            continue
        canonical = cp.stdout.replace(bytes((13, 10)), bytes((10,)))
        identities.add((len(canonical), hashlib.sha256(canonical).hexdigest()))
    return identities


def test_r6_4_c1_records_exact_inventory_service_manifest_identity_defect():
    correction = load("contracts/restaurant/v1/r6_4_freeze_integrity_correction.json")
    assert correction["additional_manifest_identity_defect_count"] == 1
    assert correction["descendant_artifact_size_basis"] == "CANONICAL_LF_BYTES"
    assert correction["descendant_artifact_hash_basis"] == "CANONICAL_LF_SHA256"
    assert correction["manifest_identity_defects"] == [{
        "path": "restaurant/r6/wnd_api_compat/inventory_service.py",
        "original_manifest_size": 54552,
        "original_manifest_sha256": "329e9ddc1c5e8d1798ad270caaa5c777067ad3d2f365ee565d8ceb92fd673e3f",
        "actual_frozen_git_blob_canonical_lf_size": 53723,
        "actual_frozen_git_blob_canonical_lf_sha256": "2000f54f377d01748b1c01a353eec8000af86905fdae37daa103b53ef07e1ece",
        "source_drift": "NO",
        "historical_blob_count": 1,
        "original_manifest_hash_matching_blob_count": 0,
    }]


def test_r6_4_c1_inventory_service_source_is_unchanged_and_bad_manifest_hash_matches_no_history():
    path = "restaurant/r6/wnd_api_compat/inventory_service.py"
    current = (ROOT / path).read_bytes().replace(bytes((13, 10)), bytes((10,)))
    assert len(current) == 53723
    assert hashlib.sha256(current).hexdigest() == "2000f54f377d01748b1c01a353eec8000af86905fdae37daa103b53ef07e1ece"
    frozen = git_show_bytes("330694145cb1d06ea915c3c484451f664ebd75f3", path).replace(
        bytes((13, 10)), bytes((10,))
    )
    assert current == frozen
    identities = historical_blob_identities(path)
    assert identities == {
        (53723, "2000f54f377d01748b1c01a353eec8000af86905fdae37daa103b53ef07e1ece")
    }
    assert all(
        sha != "329e9ddc1c5e8d1798ad270caaa5c777067ad3d2f365ee565d8ceb92fd673e3f"
        for _, sha in identities
    )


def test_r6_4_c1_all_53_descendant_rows_use_exact_canonical_lf_identity():
    release = load("contracts/restaurant/v1/r6_4_release_manifest.json")
    assert release["artifact_count"] == len(release["artifacts"]) == 53
    for row in release["artifacts"]:
        p = ROOT / row["path"]
        assert p.is_file(), row["path"]
        canonical = p.read_bytes().replace(bytes((13, 10)), bytes((10,)))
        assert row["size"] == len(canonical), row["path"]
        assert row["sha256"] == hashlib.sha256(canonical).hexdigest(), row["path"]
