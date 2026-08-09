import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m32_allocation_reversal_engine.json"
CODE = ROOT / "core/domain/finance/allocation_contract.py"
REPOSITORY = ROOT / "core/domain/finance/allocation_repository.py"
ENGINE = ROOT / "core/domain/finance/allocation_engine.py"
UP = ROOT / "alembic_neutral/sql/m32_allocation_engine_up.sql"
DOWN = ROOT / "alembic_neutral/sql/m32_allocation_engine_down.sql"
MIGRATION = ROOT / "alembic_neutral/versions/m32_allocation_engine_009_capacity_policy_and_reversals.py"
VERIFIER = ROOT / "scripts/verify_m32_allocation_engine.py"


@pytest.fixture(scope="module")
def authority():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _common():
    return dict(public_id=UUID("32000000-0000-0000-0000-000000000001"), tenant_id=3201,
                occurred_at=datetime(2026, 8, 9, 12, tzinfo=timezone.utc), business_date=date(2026, 8, 9),
                calendar_policy_version=1, correlation_id=UUID("32000000-0000-0000-0000-000000000099"),
                source_component="m32.test", source_record_id="record-1", idempotency_scope="m32.test",
                idempotency_key="key-1", actor_service="m32.test")


def _source(**changes):
    from core.domain.finance.allocation_contract import CreateValueSourceCommand
    values = {**_common(), "organization_unit_id": 3211,
              "owner_party_id": UUID("32000000-0000-0000-0000-000000000010"),
              "source_type": "payment", "source_amount": Decimal("1000"), "currency_code": "XAF"}
    values.update(changes)
    return CreateValueSourceCommand(**values)


def _allocation(**changes):
    from core.domain.finance.allocation_contract import AllocateValueCommand
    values = {**_common(), "organization_unit_id": 3211,
              "value_source_public_id": UUID("32000000-0000-0000-0000-000000000020"),
              "obligation_public_id": UUID("32000000-0000-0000-0000-000000000030"),
              "allocation_amount": Decimal("500"), "currency_code": "XAF"}
    values.update(changes)
    return AllocateValueCommand(**values)


def _reversal(**changes):
    from core.domain.finance.allocation_contract import ReverseAllocationCommand
    values = {**_common(), "organization_unit_id": 3211,
              "payment_allocation_public_id": UUID("32000000-0000-0000-0000-000000000040"),
              "reversal_amount": Decimal("100"), "currency_code": "XAF", "reason_code": "customer_refund"}
    values.update(changes)
    return ReverseAllocationCommand(**values)


def test_contract_identity(authority):
    assert (authority["contract_code"], authority["contract_version"], authority["package_revision"]) == ("XBOS_M32_ALLOCATION_REVERSAL_ENGINE", 1, 1)


def test_parent_and_target(authority):
    assert authority["parent_checkpoint"]["migration_revision"] == "m30_obligation_foundation_008"
    assert authority["target_revision"] == "m32_allocation_engine_009"


def test_all_commands_leave_commit_to_caller(authority):
    assert all(command["commit_owner"] == "caller" for command in authority["commands"].values())


def test_lock_order_is_frozen(authority):
    assert authority["locking"]["order"] == ["value_source", "financial_obligation", "payment_allocation"]


def test_database_is_final_capacity_authority(authority):
    assert authority["capacity"]["database_final_authority"] is True
    assert authority["capacity"]["direct_sql_bypass"] == "rejected"


def test_no_integration_boundary_is_activated(authority):
    assert all(value is False for value in authority["boundaries"].values())


def test_source_normalization_and_stable_fingerprint():
    first = _source(currency_code="xaf", metadata={"b": 2, "a": 1})
    second = _source(metadata={"a": 1, "b": 2})
    assert first.currency_code == "XAF" and first.request_fingerprint == second.request_fingerprint


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "1.000000001", "10000000000000000"])
def test_money_fails_closed(amount):
    from core.domain.finance.allocation_contract import AllocationValidationError
    with pytest.raises(AllocationValidationError) as exc:
        _allocation(allocation_amount=amount)
    assert exc.value.code == "invalid_money"


def test_timestamps_require_timezone():
    from core.domain.finance.allocation_contract import AllocationValidationError
    with pytest.raises(AllocationValidationError) as exc:
        _source(occurred_at=datetime(2026, 8, 9))
    assert exc.value.code == "timezone_required"


def test_actor_is_required():
    from core.domain.finance.allocation_contract import AllocationValidationError
    with pytest.raises(AllocationValidationError) as exc:
        _source(actor_service=None, actor_user_id=None)
    assert exc.value.code == "actor_required"


def test_policy_code_and_version_are_paired():
    from core.domain.finance.allocation_contract import AllocationValidationError
    with pytest.raises(AllocationValidationError) as exc:
        _allocation(cross_organization_policy_code="shared_cash")
    assert exc.value.code == "invalid_cross_organization_policy"


def test_policy_is_normalized():
    command = _allocation(cross_organization_policy_code="SHARED_CASH", cross_organization_policy_version=2)
    assert command.cross_organization_policy_code == "shared_cash"


def test_changed_amount_changes_fingerprint():
    assert _allocation().request_fingerprint != _allocation(allocation_amount="499").request_fingerprint


def test_reversal_reason_is_canonical():
    assert _reversal(reason_code="CUSTOMER_REFUND").reason_code == "customer_refund"


def test_migration_is_linear():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "m32_allocation_engine_009"' in source
    assert 'down_revision = "m30_obligation_foundation_008"' in source


def test_database_has_explicit_policy_authority():
    sql = UP.read_text(encoding="utf-8")
    assert "CREATE TABLE public.allocation_scope_policies" in sql
    assert "policy_version" in sql and "effective_from" in sql and "effective_through" in sql


def test_database_capacity_guards_lock_aggregates():
    sql = UP.read_text(encoding="utf-8")
    assert sql.count("FOR UPDATE") >= 5
    assert "allocation exceeds value-source capacity" in sql
    assert "allocation exceeds obligation capacity" in sql
    assert "reversal exceeds active allocation capacity" in sql


def test_rowtype_percent_is_escaped_for_driver_sql():
    assert "%%ROWTYPE" in UP.read_text(encoding="utf-8")


def test_downgrade_restores_m30_scope_guard():
    sql = DOWN.read_text(encoding="utf-8")
    assert "cross-organization allocation requires explicit policy" in sql
    assert "DROP TABLE IF EXISTS public.allocation_scope_policies" in sql


def test_repository_preaggregates_reversals():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert source.count("GROUP BY tenant_id,payment_allocation_id") >= 2


def test_engine_refreshes_only_after_fact_insert():
    source = ENGINE.read_text(encoding="utf-8")
    assert source.index("insert_allocation") < source.index("refresh_satisfaction_state")
    reverse_section = source[source.index("def reverse"):]
    assert reverse_section.index("insert_reversal") < reverse_section.index("refresh_satisfaction_state")


def test_engine_has_no_commit():
    assert ".commit(" not in ENGINE.read_text(encoding="utf-8")


def test_verifier_is_disposable_and_fail_safe():
    source = VERIFIER.read_text(encoding="utf-8")
    assert "xbos_track_b_m32_allocation_test" in source
    assert "retained" in source and "dropped=true" in source


def test_package_declares_expected_rehearsal(authority):
    required = {"partial_and_split", "one_to_many_and_many_to_one", "concurrency", "direct_sql_enforcement", "upgrade_downgrade_upgrade"}
    assert required <= authority["rehearsal"].keys()
