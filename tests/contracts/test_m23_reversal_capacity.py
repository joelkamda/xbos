import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m23_original_linked_correction_capacity.json"
CATALOG_PATH = ROOT / "contracts" / "finance" / "v1" / "financial_event_catalog.json"
POLICY_PATH = ROOT / "core" / "domain" / "finance" / "reversal_policy.py"
ENGINE_PATH = ROOT / "core" / "domain" / "finance" / "transactional_event_engine.py"
UP_PATH = ROOT / "alembic_neutral" / "sql" / "m23_reversal_capacity_up.sql"
DOWN_PATH = ROOT / "alembic_neutral" / "sql" / "m23_reversal_capacity_down.sql"
MIGRATION_PATH = ROOT / "alembic_neutral" / "versions" / "m23_reversal_capacity_005_original_linked_corrections.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m23_reversal_capacity.py"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M23_ORIGINAL_LINKED_CORRECTION_CAPACITY"
    assert contract["contract_version"] == 1
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_committed_m22(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "8056fbb",
        "migration_revision": "m22_transactional_delivery_004",
    }


def test_migration_is_one_linear_revision():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision = "m23_reversal_capacity_005"' in source
    assert 'down_revision = "m22_transactional_delivery_004"' in source
    assert "branch_labels = None" in source


def test_migration_is_structural_only(contract):
    assert contract["migration"]["data_mutation"] is False
    source = UP_PATH.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION" in source
    assert "CREATE TRIGGER" in source
    assert "UPDATE public.financial_events" not in source


def test_rowtype_percent_is_escaped_for_psycopg_driver():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "public.financial_events%%ROWTYPE" in source
    assert "public.financial_events%ROWTYPE" not in source.replace("%%", "")


def test_catalog_and_contract_original_linked_types_match(contract, catalog):
    catalog_types = {
        item["event_type_code"]
        for item in catalog["event_types"]
        if item["requires_original_event"]
    }
    assert catalog_types == set(contract["original_linked_types"])


@pytest.mark.parametrize(
    ("correction", "original"),
    [
        ("COMMERCIAL_RETURN_RECOGNIZED", "COMMERCIAL_REVENUE_RECOGNIZED"),
        ("PAYMENT_SETTLEMENT_REVERSED", "PAYMENT_SETTLED"),
        ("PAYMENT_ALLOCATION_REVERSED", "PAYMENT_ALLOCATED"),
    ],
)
def test_specific_correction_mapping_is_exact(contract, correction, original):
    assert contract["original_linked_types"][correction] == original
    policy = POLICY_PATH.read_text(encoding="utf-8")
    sql = UP_PATH.read_text(encoding="utf-8")
    assert f'"{correction}": "{original}"' in policy
    assert f"'{correction}'" in sql
    assert f"'{original}'" in sql


def test_generic_reversal_requires_no_dedicated_type(contract):
    assert contract["original_linked_types"]["FINANCIAL_FACT_REVERSED"] == (
        "posting_eligible_original_without_dedicated_type"
    )
    policy = POLICY_PATH.read_text(encoding="utf-8")
    assert '"specific_reversal_type_required"' in policy
    assert '"original_event_not_posting_eligible"' in policy


def test_correction_chain_is_forbidden_in_both_layers(contract):
    assert contract["invariants"]["correction_chain_forbidden"] is True
    assert '"original_event_is_correction"' in POLICY_PATH.read_text(encoding="utf-8")
    assert "a correction cannot become the original" in UP_PATH.read_text(encoding="utf-8")


def test_original_is_locked_before_capacity_sum():
    source = POLICY_PATH.read_text(encoding="utf-8")
    assert "FOR UPDATE OF fe" in source
    assert source.index("FOR UPDATE OF fe") < source.index("SELECT COALESCE(sum(amount), 0)")


def test_database_trigger_also_locks_original_before_sum():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "FOR UPDATE;" in source
    assert source.index("FOR UPDATE;") < source.index("SELECT COALESCE(sum(amount), 0)")


def test_capacity_counts_every_direct_correction():
    app = POLICY_PATH.read_text(encoding="utf-8")
    sql = UP_PATH.read_text(encoding="utf-8")
    for source in (app, sql):
        assert "original_event_id = :original_event_id" in source or "original_event_id = NEW.original_event_id" in source
        assert "sum(amount)" in source


def test_capacity_failure_is_explicit():
    source = POLICY_PATH.read_text(encoding="utf-8")
    assert '"reversal_capacity_exceeded"' in source
    assert "command.amount > remaining_before" in source


def test_partial_and_exact_capacity_are_allowed(contract):
    invariants = contract["invariants"]
    assert invariants["partial_correction_allowed"] is True
    assert invariants["exact_capacity_allowed"] is True
    assert invariants["over_capacity_rejected"] is True


def test_same_org_currency_and_time_are_checked_in_application():
    source = POLICY_PATH.read_text(encoding="utf-8")
    for code in (
        "original_event_organization_mismatch",
        "original_event_currency_mismatch",
        "correction_precedes_original",
    ):
        assert f'"{code}"' in source


def test_same_org_currency_and_time_are_checked_in_database():
    source = UP_PATH.read_text(encoding="utf-8")
    assert "original.organization_unit_id <> NEW.organization_unit_id" in source
    assert "original.currency_code <> NEW.currency_code" in source
    assert "NEW.occurred_at < original.occurred_at" in source


@pytest.mark.parametrize(
    "event_type",
    ["PAYMENT_SETTLEMENT_REVERSED", "FINANCIAL_FACT_REVERSED"],
)
def test_inverse_original_types_are_declared(contract, event_type):
    assert event_type in contract["invariants"]["inverse_account_types"]


def test_inverse_accounts_are_exact_not_merely_present():
    app = POLICY_PATH.read_text(encoding="utf-8")
    sql = UP_PATH.read_text(encoding="utf-8")
    assert '"inverse_original_accounts_mismatch"' in app
    assert 'policy.operational_account_policy.get("mode")' in app
    assert "IS DISTINCT FROM" in sql


@pytest.mark.parametrize(
    "event_type",
    ["COMMERCIAL_RETURN_RECOGNIZED", "PAYMENT_ALLOCATION_REVERSED"],
)
def test_no_account_correction_types_are_declared(contract, event_type):
    assert event_type in contract["invariants"]["no_account_types"]


def test_transactional_engine_calls_policy_before_insert():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    policy_call = "reversal_policy.validate_and_lock"
    insert_call = "event_repository.insert"
    assert policy_call in source
    assert source.index(policy_call) < source.index(insert_call)


def test_transactional_engine_still_has_m22_atomic_sequence():
    source = ENGINE_PATH.read_text(encoding="utf-8")
    for call in (
        "idempotency_repository.reserve",
        "event_repository.insert",
        "outbox_repository.ensure_for_event",
        "idempotency_repository.complete",
    ):
        assert call in source
    assert ".commit(" not in source


def test_database_rejects_direct_insert_bypass(contract):
    assert contract["enforcement"]["direct_insert_bypass_rejected"] is True
    source = UP_PATH.read_text(encoding="utf-8")
    assert "BEFORE INSERT ON public.financial_events" in source


def test_downgrade_removes_only_m23_guard():
    source = DOWN_PATH.read_text(encoding="utf-8")
    assert "DROP TRIGGER IF EXISTS tr_financial_events_reversal_capacity" in source
    assert "DROP FUNCTION IF EXISTS public.xbos_enforce_financial_reversal_capacity" in source
    assert "DROP TABLE" not in source


def test_verifier_is_guarded_to_exact_disposable_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m23_reversal_test"' in source
    assert "LOCAL_HOSTS" in source
    assert "--confirm-database-name" in source


def test_verifier_exercises_real_concurrency():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "ThreadPoolExecutor(max_workers=2)" in source
    assert "threading.Event()" in source
    assert '"reversal_capacity_exceeded"' in source


def test_verifier_exercises_database_bypass_and_atomic_counts():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "INSERT INTO public.financial_events" in source
    assert "Database trigger accepted direct over-reversal" in source
    assert "counts != (5, 5, 5)" in source


def test_wnd_cutover_remains_deferred(contract):
    assert "wnd_writer_cutover" in contract["deferred"]
