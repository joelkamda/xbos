import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m30_obligation_allocation_foundation.json"
UP_PATH = ROOT / "alembic_neutral" / "sql" / "m30_obligation_foundation_up.sql"
DOWN_PATH = ROOT / "alembic_neutral" / "sql" / "m30_obligation_foundation_down.sql"
MIGRATION_PATH = ROOT / "alembic_neutral" / "versions" / "m30_obligation_foundation_008_obligations_value_sources_allocations.py"
POLICY_PATH = ROOT / "core" / "persistence" / "m30_obligation_foundation.py"
M2_ACCEPTANCE_PATH = ROOT / "core" / "domain" / "finance" / "m2_acceptance.py"
M2_VERIFIER_PATH = ROOT / "scripts" / "verify_m27_m2_acceptance.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m30_obligation_foundation.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def up_sql():
    return UP_PATH.read_text(encoding="utf-8")


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M30_OBLIGATION_ALLOCATION_FOUNDATION"
    assert contract["contract_version"] == 1
    assert contract["package_revision"] == 2
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_the_approved_m2_tag(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "7f8fc3d",
        "release_tag": "track-b-m2-canonical-event-engine-20260808",
        "migration_revision": "m25_financial_dimensions_007",
    }


def test_migration_extends_the_single_m2_lineage():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m30_obligation_foundation_008"' in source
    assert 'down_revision = "m25_financial_dimensions_007"' in source
    assert "branch_labels = None" in source


@pytest.mark.parametrize(
    "table",
    [
        "financial_obligations",
        "financial_obligation_lines",
        "value_sources",
        "payment_allocations",
        "allocation_reversals",
    ],
)
def test_foundation_installs_exact_authority_tables(up_sql, table):
    assert f"CREATE TABLE public.{table}" in up_sql


def test_contract_and_policy_table_inventories_agree(contract):
    from core.persistence.m30_obligation_foundation import FOUNDATION_TABLES

    assert tuple(contract["tables"]) == FOUNDATION_TABLES


def test_money_uses_governed_precision(up_sql):
    assert up_sql.count("NUMERIC(24,8)") >= 7
    for amount in (
        "original_amount",
        "line_amount",
        "source_amount",
        "allocation_amount",
        "reversal_amount",
    ):
        assert f"{amount} NUMERIC(24,8) NOT NULL" in up_sql


def test_authoritative_amounts_are_positive(up_sql):
    for expression in (
        "original_amount > 0",
        "line_amount > 0",
        "source_amount > 0",
        "allocation_amount > 0",
        "reversal_amount > 0",
    ):
        assert expression in up_sql


def test_every_authoritative_fact_has_frozen_actor_and_time_context(up_sql):
    assert up_sql.count("occurred_at TIMESTAMPTZ NOT NULL") == 5
    assert up_sql.count("recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()") == 5
    assert up_sql.count("business_date DATE NOT NULL") == 5
    assert up_sql.count("calendar_policy_version INTEGER NOT NULL") == 5
    assert up_sql.count("correlation_id UUID NOT NULL") == 5
    assert up_sql.count("actor_user_id INTEGER NULL") == 5
    assert up_sql.count("actor_service VARCHAR(120) NULL") == 5
    assert up_sql.count("REFERENCES public.users(tenant_id, id)") == 5
    assert up_sql.count("actor_user_id IS NOT NULL") == 5


def test_obligation_parties_are_distinct_and_external(up_sql, contract):
    assert "debtor_party_id UUID NOT NULL" in up_sql
    assert "creditor_party_id UUID NOT NULL" in up_sql
    assert "debtor_party_id <> creditor_party_id" in up_sql
    assert "REFERENCES public.parties" not in up_sql
    assert "pending_pc2_party_authority" in contract["authority_boundaries"]["party_identity"]


def test_m3_does_not_create_payment_settlement_authority(up_sql, contract):
    assert "CREATE TABLE public.payment_settlements" not in up_sql
    assert "payment_settlement_public_id UUID NULL" in up_sql
    assert contract["scope"]["creates_payment_settlements"] is False


def test_balance_and_available_value_are_derived(contract, up_sql):
    formulas = contract["derived_formulas"]
    assert formulas["stored_balance_columns"] is False
    assert "outstanding_balance" not in up_sql
    assert "available_amount" not in up_sql


def test_allocations_hard_bind_tenant_and_currency(up_sql):
    assert "(tenant_id, value_source_id, currency_code)" in up_sql
    assert "(tenant_id, obligation_id, currency_code)" in up_sql
    assert "fk_payment_allocations_value_source" in up_sql
    assert "fk_payment_allocations_obligation" in up_sql
    assert "REFERENCES public.value_sources" in up_sql
    assert "REFERENCES public.financial_obligations" in up_sql


def test_obligation_lines_have_exact_composite_unique_fk_target(up_sql):
    assert "uq_financial_obligations_line_target" in up_sql
    assert "UNIQUE (tenant_id, organization_unit_id, id, currency_code)" in up_sql
    assert "(tenant_id, organization_unit_id, obligation_id, currency_code)" in up_sql
    assert "REFERENCES public.financial_obligations" in up_sql
    assert "(tenant_id, organization_unit_id, id, currency_code) ON DELETE RESTRICT" in up_sql


def test_cross_organization_path_requires_versioned_policy(up_sql, contract):
    assert "cross_organization_policy_code VARCHAR(80) NULL" in up_sql
    assert "cross_organization_policy_version INTEGER NULL" in up_sql
    assert "ck_payment_allocations_cross_org_policy" in up_sql
    assert "cross_organization_allocation_requires_explicit_versioned_policy" in contract["database_invariants"]
    assert "xbos_validate_payment_allocation_scope" in up_sql
    assert "cross-organization allocation requires explicit policy" in up_sql
    assert "allocation organization must be the obligation organization" in up_sql


def test_reversals_bind_to_original_allocation_scope(up_sql):
    assert "fk_allocation_reversals_allocation" in up_sql
    assert "REFERENCES public.payment_allocations" in up_sql
    assert "(tenant_id, organization_unit_id, payment_allocation_id, currency_code)" in up_sql


def test_authoritative_commands_have_tenant_idempotency(up_sql):
    assert up_sql.count("idempotency_scope VARCHAR(80) NOT NULL") == 4
    assert up_sql.count("idempotency_key VARCHAR(200) NOT NULL") == 4
    assert up_sql.count("UNIQUE (tenant_id, idempotency_scope, idempotency_key)") == 4


def test_append_only_facts_are_trigger_protected(up_sql):
    assert up_sql.count("BEFORE UPDATE OR DELETE") == 4
    for trigger in (
        "trg_financial_obligation_lines_immutable",
        "trg_value_sources_immutable",
        "trg_payment_allocations_immutable",
        "trg_allocation_reversals_immutable",
    ):
        assert trigger in up_sql


def test_obligation_authority_is_immutable_but_state_is_versioned(up_sql):
    assert "xbos_protect_financial_obligation_authority" in up_sql
    assert "OLD.original_amount IS DISTINCT FROM NEW.original_amount" in up_sql
    assert "OLD.debtor_party_id IS DISTINCT FROM NEW.debtor_party_id" in up_sql
    assert "NEW.row_version <> OLD.row_version + 1" in up_sql
    assert "OLD.obligation_state IS DISTINCT FROM NEW.obligation_state" not in up_sql


def test_downgrade_removes_only_m30_objects():
    source = DOWN_PATH.read_text(encoding="utf-8")
    for table in (
        "allocation_reversals",
        "payment_allocations",
        "value_sources",
        "financial_obligation_lines",
        "financial_obligations",
    ):
        assert f"DROP TABLE IF EXISTS public.{table}" in source
    assert "financial_events" not in source
    assert "journal_entries" not in source


def test_sql_script_is_psycopg_percent_safe(up_sql):
    assert "%" not in up_sql


def test_m2_checkpoint_validator_accepts_linear_m3_descendant():
    from core.domain.finance.m2_acceptance import EXPECTED_LINEAGE, validate_release_manifest

    result = validate_release_manifest(ROOT)
    assert result.canonical_head == "m25_financial_dimensions_007"
    assert result.lineage == EXPECTED_LINEAGE


def test_m2_checkpoint_validator_still_rejects_second_head(tmp_path):
    from core.domain.finance.m2_acceptance import M2AcceptanceError, validate_release_manifest

    versions = ROOT / "alembic_neutral" / "versions"
    rogue = versions / "temporary_test_rogue.py"
    rogue.write_text('revision = "rogue_m3_head"\ndown_revision = "m25_financial_dimensions_007"\n', encoding="utf-8")
    try:
        with pytest.raises(M2AcceptanceError) as exc:
            validate_release_manifest(ROOT)
        assert exc.value.code == "unexpected_migration_heads"
    finally:
        rogue.unlink()


def test_m2_acceptance_change_is_checkpoint_only():
    source = M2_ACCEPTANCE_PATH.read_text(encoding="utf-8")
    assert "immutable M2 prefix" in source
    assert "revision_preserves_m2_checkpoint" in source
    assert "EXPECTED_LINEAGE" in source


def test_m2_development_verifier_accepts_only_linear_descendants():
    source = M2_VERIFIER_PATH.read_text(encoding="utf-8")
    assert "revision_preserves_m2_checkpoint(ROOT, revision)" in source
    assert "or a linear descendant" in source


def test_m30_policy_preserves_frozen_m2_counts():
    from core.persistence.m30_obligation_foundation import expected_development_counts

    counts = expected_development_counts()
    assert counts["financial_event_type_versions"] == 20
    assert all(value == 0 for key, value in counts.items() if key != "financial_event_type_versions")
    assert len(counts) == 14


def test_verifier_has_one_guarded_disposable_target():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m30_foundation_test"' in POLICY_PATH.read_text(encoding="utf-8")
    assert "refusing to drop unapproved database" in source
    assert "database confirmation does not match guarded M3.0 target" in source


def test_verifier_pins_upgrade_and_downgrade_revisions():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "revision: str = TARGET_REVISION" in source
    assert "alembic_command.downgrade(_alembic_config(), PARENT_REVISION)" in source
    assert 'alembic_command.upgrade(_alembic_config(), revision)' in source


def test_verifier_checks_empty_upgrade_downgrade_upgrade():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    body = source.split("def _create_and_verify()", 1)[1].split("def main()", 1)[0]
    assert body.count("_verify_schema(TEST_DATABASE_NAME)") == 2
    assert "_verify_downgrade(TEST_DATABASE_NAME)" in body
    assert "upgrade_downgrade_upgrade=PASS" in body


def test_verifier_refuses_wrong_development_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "refusing development verification" in source
    assert "expected development revision" in source


def test_gate_defers_engines_and_cutovers(contract):
    assert contract["scope"]["activates_obligation_writer"] is False
    assert contract["scope"]["activates_allocation_writer"] is False
    assert contract["scope"]["changes_wnd_writers"] is False
    assert contract["scope"]["dispatches_outbox"] is False
    assert "allocation_capacity_and_concurrency_engine" in contract["deferred"]
    assert "pack_facing_service_contract" in contract["deferred"]
