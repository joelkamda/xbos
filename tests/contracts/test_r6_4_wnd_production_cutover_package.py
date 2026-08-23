from __future__ import annotations

import json
from pathlib import Path

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
    assert inv_sha == "85f45225fd783244f00dec1c8d3cc290f5885caa5d0e442cd83dd3c40bb843d2"

    pc0 = load("contracts/platform/v1/pc0_release_manifest.json")
    pc0_artifact = next(
        item for item in pc0["artifacts"]
        if item["path"] == "contracts/platform/v1/pc0_frozen_finance_inventory.json"
    )
    assert pc0_artifact["sha256"] == inv_sha

    pc0_path = ROOT / "contracts/platform/v1/pc0_release_manifest.json"
    pc0_sha = hashlib.sha256(pc0_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert pc0_sha == "6e335af697bde10dfc2cf847fdd489ea4df12f315e626dfd6fb3a674b64e6a6a"

    pc6 = load("contracts/platform/v1/pc6_release_manifest.json")
    for milestone in range(1, 6):
        replacements = pc6[f"historical_pc{milestone}_replacements"]
        inv = next(item for item in replacements if item["path"] == "contracts/platform/v1/pc0_frozen_finance_inventory.json")
        rel = next(item for item in replacements if item["path"] == "contracts/platform/v1/pc0_release_manifest.json")
        assert inv["descendant_sha256"] == inv_sha
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
        'contracts/shared_operations/v1/so1_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json'],
        'contracts/shared_operations/v1/so2_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json'],
        'contracts/shared_operations/v1/so3_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json'],
        'contracts/shared_operations/v1/so4_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json'],
        'contracts/shared_operations/v1/so5_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json'],
        'contracts/shared_operations/v1/so6_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json'],
        'contracts/shared_operations/v1/so7_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json'],
        'contracts/shared_operations/v1/so8_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json'],
        'contracts/shared_operations/v1/so9_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json'],
        'contracts/shared_operations/v1/so10_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json'],
        'contracts/shared_operations/v1/so_aggregate_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json'],
        'contracts/packs/v1/pk0123_release_manifest.json': ['contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/packs/v1/pk456_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/packs/v1/pk_aggregate_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json'],
        'contracts/platform_admin/v1/pa0123_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/platform_admin/v1/pa45_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/platform_admin/v1/pa6_release_manifest.json': ['contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json'],
        'contracts/platform/v1/sc41_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/platform_admin/v1/pa6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/restaurant/v1/r1_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/platform/v1/sc41_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/platform_admin/v1/pa6_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
        'contracts/restaurant/v1/r2_release_manifest.json': ['contracts/packs/v1/pk0123_release_manifest.json', 'contracts/packs/v1/pk456_release_manifest.json', 'contracts/packs/v1/pk_aggregate_release_manifest.json', 'contracts/platform/v1/pc0_frozen_finance_inventory.json', 'contracts/platform/v1/pc0_release_manifest.json', 'contracts/platform/v1/pc6_release_manifest.json', 'contracts/platform/v1/sc41_release_manifest.json', 'contracts/platform_admin/v1/pa0123_release_manifest.json', 'contracts/platform_admin/v1/pa45_release_manifest.json', 'contracts/platform_admin/v1/pa6_release_manifest.json', 'contracts/restaurant/v1/r1_release_manifest.json', 'contracts/shared_operations/v1/so10_release_manifest.json', 'contracts/shared_operations/v1/so1_release_manifest.json', 'contracts/shared_operations/v1/so2_release_manifest.json', 'contracts/shared_operations/v1/so3_release_manifest.json', 'contracts/shared_operations/v1/so4_release_manifest.json', 'contracts/shared_operations/v1/so5_release_manifest.json', 'contracts/shared_operations/v1/so6_release_manifest.json', 'contracts/shared_operations/v1/so7_release_manifest.json', 'contracts/shared_operations/v1/so8_release_manifest.json', 'contracts/shared_operations/v1/so9_release_manifest.json', 'contracts/shared_operations/v1/so_aggregate_release_manifest.json'],
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
