import json
from datetime import date,datetime,timezone
from pathlib import Path

import pytest

pytestmark=pytest.mark.contract
ROOT=Path(__file__).resolve().parents[2]
CONTRACT=ROOT/"contracts/finance/v1/m34_deterministic_obligation_aging.json"
CONTRACT_CODE=ROOT/"core/domain/finance/aging_contract.py"
SERVICE=ROOT/"core/domain/finance/obligation_aging_service.py"
UP=ROOT/"alembic_neutral/sql/m34_obligation_aging_up.sql"
DOWN=ROOT/"alembic_neutral/sql/m34_obligation_aging_down.sql"
MIGRATION=ROOT/"alembic_neutral/versions/m34_obligation_aging_010_historical_state_and_as_of_authority.py"
VERIFIER=ROOT/"scripts/verify_m34_obligation_aging.py"

@pytest.fixture(scope="module")
def authority(): return json.loads(CONTRACT.read_text(encoding="utf-8"))

def test_identity(authority):
    assert (authority["contract_code"],authority["contract_version"],authority["package_revision"])==("XBOS_M34_DETERMINISTIC_OBLIGATION_AGING",1,1)

def test_parent_and_target(authority):
    assert authority["parent_checkpoint"]=={"commit":"8cf0944","migration_revision":"m32_allocation_engine_009"}
    assert authority["target_revision"]=="m34_obligation_aging_010"

def test_history_is_append_only_and_triggered(authority):
    history=authority["historical_state_authority"]
    assert history["append_only"] and history["database_triggered"]
    assert history["ordering"]==["effective_at","id"]

def test_balance_is_not_stored(authority):
    assert authority["as_of_balance"]["stored_snapshot"] is False
    assert authority["as_of_balance"]["formula"]=="original_amount_minus_allocations_plus_reversals"

def test_no_integration_boundary(authority): assert all(value is False for value in authority["boundaries"].values())

def test_default_policy_classifies_boundaries():
    from core.domain.finance.aging_contract import AgingPolicy
    policy=AgingPolicy()
    expected={-1:"not_due",0:"due_today",1:"past_due_1_30",30:"past_due_1_30",31:"past_due_31_60",60:"past_due_31_60",61:"past_due_61_90",90:"past_due_61_90",91:"past_due_91_plus"}
    assert {day:policy.classify(day) for day in expected}==expected

def test_policy_has_versioned_identity():
    from core.domain.finance.aging_contract import AgingPolicy
    assert (AgingPolicy().code,AgingPolicy().version)==("standard_receivables",1)

def test_query_requires_timezone():
    from core.domain.finance.aging_contract import AsOfAgingQuery,AgingValidationError
    with pytest.raises(AgingValidationError) as exc: AsOfAgingQuery(1,datetime(2026,8,9),date(2026,8,9))
    assert exc.value.code=="timezone_required"

@pytest.mark.parametrize("tenant,org",[(0,None),(-1,None),(1,0),(1,-2)])
def test_query_scope_fails_closed(tenant,org):
    from core.domain.finance.aging_contract import AsOfAgingQuery,AgingValidationError
    with pytest.raises(AgingValidationError) as exc: AsOfAgingQuery(tenant,datetime(2026,8,9,tzinfo=timezone.utc),date(2026,8,9),org)
    assert exc.value.code=="invalid_scope"

def test_migration_is_linear():
    source=MIGRATION.read_text(encoding="utf-8")
    assert 'revision="m34_obligation_aging_010"' in source and 'down_revision="m32_allocation_engine_009"' in source

def test_history_table_has_as_of_index():
    sql=UP.read_text(encoding="utf-8")
    assert "CREATE TABLE public.obligation_state_transitions" in sql
    assert "effective_at DESC,id DESC" in sql

def test_existing_rows_are_baselined(): assert "baseline_adoption" in UP.read_text(encoding="utf-8")

def test_insert_and_update_are_database_captured():
    sql=UP.read_text(encoding="utf-8")
    assert "AFTER INSERT ON public.financial_obligations" in sql
    assert "AFTER UPDATE OF obligation_state" in sql

def test_history_is_database_immutable(): assert "trg_obligation_state_transitions_immutable" in UP.read_text(encoding="utf-8")

def test_downgrade_removes_only_m34_authority():
    sql=DOWN.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS public.obligation_state_transitions" in sql
    assert "payment_allocations" not in sql

def test_as_of_query_cuts_each_fact_stream():
    source=SERVICE.read_text(encoding="utf-8")
    assert source.count("occurred_at<=:as_of")==3
    assert "effective_at<=:as_of" in source

def test_due_date_uses_organization_timezone(): assert "AT TIME ZONE ou.timezone_name" in SERVICE.read_text(encoding="utf-8")

def test_latest_state_has_deterministic_tie_break(): assert "effective_at DESC,st.id DESC" in SERVICE.read_text(encoding="utf-8")

def test_service_requires_tenant_and_optional_org():
    source=SERVICE.read_text(encoding="utf-8")
    assert "o.tenant_id=:tenant" in source and ":organization_id IS NULL" in source

def test_terminal_rows_are_opt_in(): assert "include_terminal" in SERVICE.read_text(encoding="utf-8")

def test_negative_capacity_fails_closed(): assert "obligation_capacity_corrupt" in SERVICE.read_text(encoding="utf-8")

def test_verifier_is_disposable_and_fail_safe():
    source=VERIFIER.read_text(encoding="utf-8")
    assert "xbos_track_b_m34_aging_test" in source and "retained" in source and "dropped=true" in source

def test_rehearsal_scope(authority):
    required={"bucket_boundaries","as_of_allocation_cutoff","as_of_reversal_cutoff","historical_state","immutability","upgrade_downgrade_upgrade"}
    assert required <= authority["rehearsal"].keys()
