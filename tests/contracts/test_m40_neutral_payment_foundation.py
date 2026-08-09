import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/finance/v1/m40_neutral_payment_settlement_orchestration_foundation.json"
UP_PATH = ROOT / "alembic_neutral/sql/m40_payment_foundation_up.sql"
DOWN_PATH = ROOT / "alembic_neutral/sql/m40_payment_foundation_down.sql"
MIGRATION_PATH = ROOT / "alembic_neutral/versions/m40_payment_foundation_011_neutral_payment_settlement_orchestration.py"
POLICY_PATH = ROOT / "core/persistence/m40_payment_foundation.py"
M3_ACCEPTANCE_PATH = ROOT / "core/domain/finance/m3_acceptance.py"
M3_VERIFIER_PATH = ROOT / "scripts/verify_m36_m3_acceptance.py"
VERIFIER_PATH = ROOT / "scripts/verify_m40_payment_foundation.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def up_sql():
    return UP_PATH.read_text(encoding="utf-8")


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M40_NEUTRAL_PAYMENT_SETTLEMENT_ORCHESTRATION_FOUNDATION"
    assert contract["contract_version"] == 1
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_approved_m3_tag(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "0a9c292",
        "release_tag": "track-b-m3-obligations-balances-allocations-20260809",
        "migration_revision": "m34_obligation_aging_010",
    }


def test_migration_extends_the_single_m3_lineage():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m40_payment_foundation_011"' in source
    assert 'down_revision = "m34_obligation_aging_010"' in source
    assert "branch_labels = None" in source


@pytest.mark.parametrize(
    "table",
    [
        "canonical_payment_requests",
        "canonical_payment_intents",
        "canonical_payment_tenders",
        "canonical_payment_attempts",
        "provider_callback_events",
        "payment_settlements",
        "payment_settlement_reversals",
    ],
)
def test_foundation_installs_exact_authority_tables(up_sql, table):
    assert f"CREATE TABLE public.{table}" in up_sql


def test_contract_policy_and_sql_inventories_agree(contract, up_sql):
    from core.persistence.m40_payment_foundation import FOUNDATION_TABLES

    assert tuple(contract["tables"]) == FOUNDATION_TABLES
    assert all(f"CREATE TABLE public.{table}" in up_sql for table in FOUNDATION_TABLES)


def test_legacy_payment_tables_are_preserved(contract, up_sql):
    legacy = contract["legacy_coexistence"]["tables_preserved"]
    assert legacy == ["payments", "payment_intents", "payment_attempts"]
    for table in legacy:
        assert f"CREATE TABLE public.{table}" not in up_sql
        assert f"ALTER TABLE public.{table}" not in up_sql


def test_m40_is_empty_and_does_not_activate_writers(contract):
    scope = contract["scope"]
    assert scope["creates_empty_structures_only"] is True
    assert scope["activates_canonical_payment_writer"] is False
    assert scope["changes_wnd_writers"] is False
    assert scope["creates_development_payment_records"] is False
    assert scope["dispatches_outbox"] is False
    assert scope["creates_public_routes"] is False


def test_money_uses_governed_precision(up_sql):
    assert up_sql.count("NUMERIC(24,8)") == 8
    for amount in (
        "requested_amount",
        "tender_amount",
        "attempted_amount",
        "gross_amount",
        "fee_amount",
        "net_amount",
        "reversal_amount",
    ):
        assert f"{amount} NUMERIC(24,8) NOT NULL" in up_sql


def test_method_rail_orchestrator_and_provider_are_distinct(up_sql, contract):
    for field in (
        "payment_method_code",
        "payment_rail_code",
        "orchestrator_code",
        "underlying_provider_code",
        "provider_account_id",
    ):
        assert field in up_sql
    neutrality = contract["provider_neutrality"]
    assert neutrality["xafpay_role"] == "one_supported_orchestrator_adapter"
    assert neutrality["direct_provider_connections_supported"] is True
    assert neutrality["hard_coded_provider"] is False
    assert "xafpay" not in up_sql.lower()


def test_mixed_tender_structure_is_explicit(up_sql):
    assert "tender_number INTEGER NOT NULL" in up_sql
    assert "tender_amount NUMERIC(24,8) NOT NULL" in up_sql
    assert "UNIQUE (tenant_id, payment_intent_id, tender_number)" in up_sql
    assert "fk_canonical_payment_attempts_tender" in up_sql


def test_attempt_provider_account_is_tenant_scoped(up_sql):
    assert "fk_canonical_payment_attempts_provider_account" in up_sql
    assert "(tenant_id, provider_account_id)" in up_sql
    assert "REFERENCES public.payment_provider_accounts(tenant_id, id)" in up_sql


def test_callback_evidence_is_deduplicated_and_hashed(up_sql):
    assert "uq_provider_callback_events_provider_event" in up_sql
    assert "UNIQUE (tenant_id, provider_account_id, provider_event_reference)" in up_sql
    assert "payload_hash CHAR(64) NOT NULL" in up_sql
    assert "payload_hash ~ '^[0-9a-f]{64}$'" in up_sql
    assert "signature_status IN ('unverified','verified','rejected','not_applicable')" in up_sql


def test_callback_is_evidence_not_financial_event(up_sql, contract):
    boundary = contract["authority_boundaries"]["provider_callback_event"]
    assert "not_a_financial_event" in boundary
    callback_section = up_sql.split("CREATE TABLE public.provider_callback_events", 1)[1].split(
        "CREATE TABLE public.payment_settlements", 1
    )[0]
    assert "financial_event" not in callback_section
    assert "outbox_messages" not in callback_section


def test_settlement_math_and_finality_are_database_enforced(up_sql):
    assert "gross_amount > 0 AND fee_amount >= 0 AND net_amount >= 0" in up_sql
    assert "net_amount = gross_amount - fee_amount" in up_sql
    assert "ck_payment_settlements_external_evidence" in up_sql
    assert "OR provider_callback_event_id IS NOT NULL" in up_sql


def test_settlement_operational_account_currency_is_hard_bound(up_sql):
    assert "uq_operational_financial_accounts_settlement_target" in up_sql
    assert "UNIQUE (tenant_id, id, currency_code)" in up_sql
    assert "fk_payment_settlements_operational_account" in up_sql
    assert "(tenant_id, operational_account_id, currency_code)" in up_sql
    assert "REFERENCES public.operational_financial_accounts" in up_sql


def test_settlement_activates_the_deferred_m3_value_source_link(up_sql):
    assert "fk_value_sources_payment_settlement" in up_sql
    assert "(tenant_id, payment_settlement_public_id)" in up_sql
    assert "REFERENCES public.payment_settlements(tenant_id, public_id)" in up_sql


def test_provider_accounts_remain_distinct_from_operational_accounts(up_sql, contract):
    boundaries = contract["authority_boundaries"]
    assert "external_provider_identity" in boundaries["payment_provider_account"]
    assert "treasury_and_reconciliation" in boundaries["operational_financial_account"]
    assert "provider_account_id BIGINT" in up_sql
    assert "operational_account_id BIGINT NOT NULL" in up_sql


def test_all_records_have_tenant_time_business_and_correlation_context(up_sql):
    assert up_sql.count("occurred_at TIMESTAMPTZ NOT NULL") == 7
    assert up_sql.count("business_date DATE NOT NULL") == 7
    assert up_sql.count("calendar_policy_version INTEGER NOT NULL") == 7
    assert up_sql.count("correlation_id UUID NOT NULL") == 7


def test_commands_have_tenant_idempotency(up_sql):
    assert up_sql.count("idempotency_scope VARCHAR(80) NOT NULL") == 5
    assert up_sql.count("idempotency_key VARCHAR(200) NOT NULL") == 5
    assert up_sql.count("UNIQUE (tenant_id, idempotency_scope, idempotency_key)") == 5


def test_immutable_evidence_has_database_triggers(up_sql):
    assert "trg_provider_callback_events_immutable" in up_sql
    assert "trg_payment_settlement_reversals_immutable" in up_sql
    assert up_sql.count("BEFORE UPDATE OR DELETE") == 2


def test_downgrade_removes_only_m40_objects():
    source = DOWN_PATH.read_text(encoding="utf-8")
    from core.persistence.m40_payment_foundation import FOUNDATION_TABLES

    for table in reversed(FOUNDATION_TABLES):
        assert f"DROP TABLE IF EXISTS public.{table}" in source
    assert "DROP TABLE IF EXISTS public.payments" not in source
    assert "DROP TABLE IF EXISTS public.payment_intents" not in source
    assert "DROP TABLE IF EXISTS public.payment_attempts" not in source
    assert "DROP TABLE IF EXISTS public.financial_obligations" not in source


def test_sql_script_is_psycopg_percent_safe(up_sql):
    assert "%" not in up_sql.replace("%%", "")
    assert "RAISE EXCEPTION '%% is immutable" in up_sql


def test_m3_acceptance_is_checkpoint_not_permanent_head():
    source = M3_ACCEPTANCE_PATH.read_text(encoding="utf-8")
    assert "immutable M3 prefix" in source
    assert "revision_preserves_m3_checkpoint" in source
    assert "live_migration_lineage" in source


def test_m3_development_verifier_accepts_linear_descendants():
    source = M3_VERIFIER_PATH.read_text(encoding="utf-8")
    assert "revision_preserves_m3_checkpoint(ROOT, revision)" in source
    assert "or a linear descendant" in source


def test_verifier_is_exactly_scoped_to_disposable_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m40_payment_foundation_test"' in POLICY_PATH.read_text(
        encoding="utf-8"
    )
    assert "unsafe disposable database target" in source
    assert "exact disposable database confirmation is required" in source


def test_verifier_proves_upgrade_downgrade_upgrade_and_development_emptiness():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert source.count("_verify_development()") >= 2
    assert "_migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)" in source
    assert "_migrate(TEST_DATABASE_NAME, TARGET_REVISION)" in source
    assert "upgrade_downgrade_upgrade=PASS" in source


def test_package_does_not_add_routes_or_switch_writers():
    package_paths = (CONTRACT_PATH, POLICY_PATH, M3_ACCEPTANCE_PATH, VERIFIER_PATH, MIGRATION_PATH)
    joined = "\n".join(path.read_text(encoding="utf-8") for path in package_paths).lower()
    assert "from fastapi" not in joined
    assert "core.domain.payments.service" not in joined
    assert "wnd_writer" not in joined or "changes_wnd_writers" in joined
