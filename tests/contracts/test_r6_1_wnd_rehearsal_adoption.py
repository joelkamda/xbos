from __future__ import annotations

import json
from pathlib import Path

from restaurant.r6 import (
    CANDIDATE_DATABASE,
    CANONICAL_SOURCE_STAMP,
    DISPOSABLE_DATABASES,
    EXPECTED_COUNTS,
    KITCHEN_BON_PRESERVATION,
    REFERENCE_RELEASE_PRESERVATION,
    REFERENCE_RELEASE_TAG,
    REFERENCE_SOURCE_EVIDENCE_SHA256,
    PRODUCTION_BACKEND_RELEASE_BRANCH,
    PRODUCTION_FRONTEND_RELEASE_BRANCH,
    PRODUCTION_BACKEND_HEAD,
    PRODUCTION_DATABASE,
    PRODUCTION_FRONTEND_HEAD,
    SERVER_BACKUP_SHA256,
    SOURCE_DATABASE,
    SOURCE_REVISION,
    TARGET_HEAD,
)

ROOT = Path(__file__).resolve().parents[2]


def load(name: str):
    return json.loads((ROOT / "contracts/restaurant/v1" / name).read_text())


def test_r6_0_freezes_exact_reference_release_server_snapshot_and_live_source():
    value = load("r6_0_wnd_production_baseline.json")
    assert value["server_evidence"]["database"] == PRODUCTION_DATABASE == "xbos"
    assert value["server_evidence"]["database_revision"] == SOURCE_REVISION
    assert value["server_evidence"]["snapshot_backup"]["sha256"] == SERVER_BACKUP_SHA256
    assert value["runtime_source"]["backend_head"] == PRODUCTION_BACKEND_HEAD
    assert value["runtime_source"]["frontend_head"] == PRODUCTION_FRONTEND_HEAD
    assert value["baseline_generation"] == "R6_REFERENCE_RELEASE_20260821_171736"
    assert value["reference_release"]["release_tag"] == REFERENCE_RELEASE_TAG
    assert value["reference_release"]["backend_release_branch"] == PRODUCTION_BACKEND_RELEASE_BRANCH
    assert value["reference_release"]["frontend_release_branch"] == PRODUCTION_FRONTEND_RELEASE_BRANCH
    assert value["reference_release"]["source_evidence_sha256"] == REFERENCE_SOURCE_EVIDENCE_SHA256
    assert value["capture_safety"] == {
        "production_writes": "NONE",
        "writer_routing_changes": "NONE",
        "cutover": "NONE",
    }


def test_r6_0_reference_release_behavior_and_untracked_disclosure_are_frozen():
    value = load("r6_0_wnd_production_baseline.json")
    assert value["runtime_source"]["backend_untracked_files"] == ["scripts/wnd_taxonomy_tree_export.py"]
    assert value["runtime_source"]["frontend_untracked_files"] == []
    behavior = value["reference_behavior"]
    assert "takeaway" in behavior["fulfillment"].lower()
    assert "delivery" in behavior["fulfillment"].lower()
    assert "semantic" in behavior["kitchen"].lower()
    assert "unlinked" in behavior["customer_ar"].lower()
    assert "semantic add/cancel/change" in KITCHEN_BON_PRESERVATION.lower()
    assert "fulfillment" in REFERENCE_RELEASE_PRESERVATION.lower()
    assert "customer/a-r identity" in REFERENCE_RELEASE_PRESERVATION.lower()


def test_r6_0_reference_schema_freezes_fulfillment_and_customer_ar_identity():
    value = load("r6_0_wnd_production_baseline.json")["legacy_reference_schema"]
    assert value["customers_table"]["exists"] is True
    assert value["customers_table"]["row_count"] == 0
    assert value["orders_fulfillment_mode"]["nullable"] is True
    assert value["orders_fulfillment_mode"]["allowed_values"] == ["DINE_IN", "TAKEAWAY", "DELIVERY"]
    assert value["accounts_receivable_customer_identity"]["column"] == "customer_id"
    assert value["accounts_receivable_customer_identity"]["linked_rows_at_capture"] == 0


def test_r6_1_is_disposable_clone_only_and_cannot_target_production():
    value = load("r6_1_rehearsal_adoption_authority.json")
    assert value["production_write_authorized"] is False
    assert set(value["rehearsal_databases"]) == {SOURCE_DATABASE, CANDIDATE_DATABASE}
    assert DISPOSABLE_DATABASES == {SOURCE_DATABASE, CANDIDATE_DATABASE}
    assert PRODUCTION_DATABASE not in DISPOSABLE_DATABASES
    assert "no connection to production database xbos for writes" in value["explicit_non_actions"]


def test_r6_1_adopts_lineage_by_stamp_then_upgrade_not_reconstructing_source():
    value = load("r6_1_rehearsal_adoption_authority.json")
    sequence = value["candidate_clone"]["lineage_adoption"]
    assert CANONICAL_SOURCE_STAMP in sequence[1]
    assert TARGET_HEAD in sequence[2]
    assert value["source_clone"]["expected_head"] == SOURCE_REVISION


def test_r6_1_control_counts_equal_frozen_production_evidence():
    value = load("r6_1_control_totals.json")
    assert value["count_controls"] == EXPECTED_COUNTS
    assert value["count_controls"]["customers"] == 0
    assert value["count_controls"]["orders"] == 8451
    assert value["count_controls"]["sales"] == 7745
    assert value["financial_operational_controls"]["ar_equation_mismatches"] == 0
    assert value["financial_operational_controls"]["inventory_historical_cache_ledger_mismatches"] == 156
    assert value["financial_operational_controls"]["inventory_historical_aggregate_delta"] == "1995833"
    assert value["financial_operational_controls"]["reconciliation_rows"] == 791
    assert value["legacy_reference_schema_controls"]["orders_fulfillment_mode"]["column_exists"] is True
    assert value["legacy_reference_schema_controls"]["accounts_receivable_customer_identity"]["linked_rows_at_capture"] == 0


def test_r6_1_existing_wnd_tenant_is_composed_without_creating_r5_proof_tenant():
    value = load("r6_1_rehearsal_adoption_authority.json")["composition_rehearsal"]
    assert value["existing_production_tenant_id"] == 2
    assert value["existing_production_branch_id"] == 1
    assert value["create_new_wnd_tenant"] is False
    assert value["register_certified_pack"] == "industry.restaurant@1.0.0"
    assert value["template"] == "restaurant.counter_service@1.0.0"


def test_r6_1_preserves_m7_advisory_boundary_until_explicit_live_authorization():
    value = json.loads(
        (ROOT / "contracts/finance/v1/m75_finance_migration_support_acceptance_and_freeze.json").read_text()
    )
    assert value["live_cutover_owner"] == "R6"
    assert value["cutover_authorized"] is False
    assert value["retirement_execution_allowed"] is False


def test_r6_1_has_no_schema_migration():
    assert not list((ROOT / "alembic_neutral/versions").glob("r6_*"))
    assert not list((ROOT / "alembic_neutral/sql").glob("r6_*"))


def test_r6_1_acceptance_script_has_exact_disposable_guards_and_backup_hash_gate():
    source = (ROOT / "scripts/verify_r6_1_wnd_rehearsal_adoption.py").read_text()
    assert "_assert_disposable" in source
    assert "R6_1_PRODUCTION_DATABASE_WRITE_REFUSED" in source
    assert "R6_1_SERVER_BACKUP_NOT_FOUND_OR_HASH_MISMATCH" in source
    assert "command.stamp(cfg, CANONICAL_SOURCE_STAMP, purge=True)" in source
    assert "command.upgrade(cfg, TARGET_HEAD)" in source
    assert "_register_and_compose_candidate" in source
    assert "_legacy_reference_schema" in source
    assert "R6_1_LEGACY_REFERENCE_SCHEMA_CHANGED" in source
    assert "R6_1_REFERENCE_FULFILLMENT_COLUMN_MISSING" in source
    assert "R6_1_REFERENCE_AR_CUSTOMER_ID_MISSING" in source


def test_r6_1_release_manifest_is_self_excluded_and_complete():
    manifest = load("r6_1_release_manifest.json")
    assert manifest["self_excluded"] is True
    assert manifest["artifact_count"] == len(manifest["artifacts"])
    assert "contracts/restaurant/v1/r6_1_release_manifest.json" not in {
        row["path"] for row in manifest["artifacts"]
    }


def test_r6_1_static_verifier_pins_exact_r6_branch_and_r5_commit():
    source = (ROOT / "scripts/verify_r6_1_wnd_rehearsal_adoption.py").read_text()
    assert 'EXPECTED_BRANCH = "restaurant/r6-wnd-cutover"' in source
    assert 'SOURCE_COMMIT = "2f90f1714782bcf54da6d8cac2cc0499d2e82dfc"' in source
    assert "R6_1_WRONG_BRANCH" in source
    assert "R6_1_SOURCE_HEAD_DRIFT" in source


def test_r6_1_gate_checks_frozen_m75_source_contract_without_replaying_stale_m75_dev_db_gate():
    source = (ROOT / "XBOS_R6_1_RUN_ACCEPTANCE.cmd").read_text(encoding="utf-8")
    assert "tests/contracts/test_m75_finance_migration_support_acceptance_and_freeze.py" in source
    assert "python scripts/verify_m75_m7_acceptance.py ||" not in source
    # M7.5's executable aggregate is pinned to its historical m64 development DB.
    # R6.1 has already advanced the neutral development lineage through Restaurant R2,
    # so predecessor integrity here is source/contract authority, not a replay of that old DB gate.

def test_r6_1_r4_certification_evidence_helper_is_local_and_matches_frozen_r5_evidence():
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
    assert "from restaurant.r4 import build_certification_command, build_registration_command, r4_evidence_hashes" not in source
    assert "build_certification_command(_r4_evidence_hashes())" in source



def test_r6_1_pack_and_template_post_compose_queries_use_actual_pk_schema_columns():
    source = (ROOT / "scripts/verify_r6_1_wnd_rehearsal_adoption.py").read_text(encoding="utf-8")
    assert "v.pack_version AS version" in source
    assert "v.template_version AS version" in source
    assert "SELECT i.lifecycle_status AS status,v.version" not in source
    assert "SELECT t.template_code,v.version" not in source

    pk0123 = (ROOT / "alembic_neutral/sql/pk0123_pack_manifest_lifecycle_up.sql").read_text(encoding="utf-8")
    pk456 = (ROOT / "alembic_neutral/sql/pk456_pack_conformance_templates_up.sql").read_text(encoding="utf-8")
    assert "pack_version VARCHAR(64) NOT NULL" in pk0123
    assert "template_version VARCHAR(64) NOT NULL" in pk456
