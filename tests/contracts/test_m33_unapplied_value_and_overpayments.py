import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m33_unapplied_value_and_overpayment_workflows.json"
COMMANDS = ROOT / "core/domain/finance/value_application_contract.py"
BALANCE = ROOT / "core/domain/finance/value_source_balance_service.py"
ENGINE = ROOT / "core/domain/finance/value_application_engine.py"
VERIFIER = ROOT / "scripts/verify_m33_value_application_workflows.py"


@pytest.fixture(scope="module")
def authority():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _source(public_id=UUID("33000000-0000-0000-0000-000000000001")):
    from core.domain.finance.allocation_contract import CreateValueSourceCommand
    return CreateValueSourceCommand(
        public_id=public_id,tenant_id=3301,organization_unit_id=3311,
        owner_party_id=UUID("33000000-0000-0000-0000-000000000010"),source_type="customer_deposit",
        source_amount="1000",currency_code="XAF",occurred_at=datetime(2026,8,9,tzinfo=timezone.utc),
        business_date=date(2026,8,9),calendar_policy_version=1,
        correlation_id=UUID("33000000-0000-0000-0000-000000000099"),actor_service="m33.test",
        source_component="m33.test",source_record_id="receipt-1",idempotency_scope="m33.receipt",idempotency_key="receipt-1")


def _instruction(**changes):
    from core.domain.finance.value_application_contract import ValueApplicationInstruction
    values=dict(allocation_public_id=UUID("33000000-0000-0000-0000-000000000020"),
                obligation_public_id=UUID("33000000-0000-0000-0000-000000000030"),
                source_record_id="application-1",idempotency_key="application-1")
    values.update(changes)
    return ValueApplicationInstruction(**values)


def _batch(applications=None,source=UUID("33000000-0000-0000-0000-000000000001")):
    from core.domain.finance.value_application_contract import ApplyUnappliedValueCommand
    return ApplyUnappliedValueCommand(
        tenant_id=3301,value_source_public_id=source,occurred_at=datetime(2026,8,9,tzinfo=timezone.utc),
        business_date=date(2026,8,9),calendar_policy_version=1,
        correlation_id=UUID("33000000-0000-0000-0000-000000000099"),source_component="m33.test",
        idempotency_scope="m33.apply",applications=applications or (_instruction(),),actor_service="m33.test")


def test_contract_identity(authority):
    assert (authority["contract_code"],authority["contract_version"],authority["package_revision"]) == ("XBOS_M33_UNAPPLIED_VALUE_AND_OVERPAYMENT_WORKFLOWS",1,1)


def test_contract_is_anchored_to_m32(authority):
    assert authority["parent_checkpoint"] == {"commit":"4e02840","migration_revision":"m32_allocation_engine_009"}


def test_schema_is_unchanged(authority):
    assert authority["schema_change"] is False
    assert authority["target_revision"] == "m32_allocation_engine_009"
    assert not list((ROOT/"alembic_neutral/versions").glob("m33_*.py")) if (ROOT/"alembic_neutral").exists() else True


def test_overpayment_is_not_mutable_balance(authority):
    assert authority["workflows"]["overpayment"]["mutable_overpayment_row"] is False
    assert authority["workflows"]["overpayment"]["result_disposition"] == "overpayment_residual"


def test_balance_formula_is_explicit(authority):
    balance=authority["derived_value_source_balance"]
    assert balance["active_applied_amount"] == "allocations_minus_allocation_reversals"
    assert balance["available_amount"] == "source_amount_minus_active_applied_amount"
    assert balance["stored_balance_column"] is False


def test_no_integration_boundary_is_activated(authority):
    assert all(value is False for value in authority["boundaries"].values())


def test_instruction_without_amount_is_up_to_outstanding():
    assert _instruction().mode == "up_to_outstanding"


def test_instruction_with_amount_is_exact():
    assert _instruction(exact_amount="25").mode == "exact"
    assert _instruction(exact_amount="25").exact_amount == Decimal("25.00000000")


@pytest.mark.parametrize("amount",["0","-1","NaN","Infinity","1.000000001","10000000000000000"])
def test_exact_money_fails_closed(amount):
    from core.domain.finance.value_application_contract import ValueApplicationError
    with pytest.raises(ValueApplicationError) as exc:
        _instruction(exact_amount=amount)
    assert exc.value.code == "invalid_money"


def test_policy_code_and_version_must_be_paired():
    from core.domain.finance.value_application_contract import ValueApplicationError
    with pytest.raises(ValueApplicationError) as exc:
        _instruction(cross_organization_policy_code="shared_cash")
    assert exc.value.code == "invalid_cross_organization_policy"


def test_batch_requires_applications():
    from core.domain.finance.value_application_contract import ApplyUnappliedValueCommand, ValueApplicationError
    with pytest.raises(ValueApplicationError) as exc:
        ApplyUnappliedValueCommand(3301,UUID("33000000-0000-0000-0000-000000000001"),
          datetime(2026,8,9,tzinfo=timezone.utc),date(2026,8,9),1,
          UUID("33000000-0000-0000-0000-000000000099"),"m33.test","m33.apply",(),actor_service="m33.test")
    assert exc.value.code == "applications_required"


def test_batch_rejects_duplicate_obligation_target():
    from core.domain.finance.value_application_contract import ValueApplicationError
    first=_instruction(); second=replace(first,allocation_public_id=UUID("33000000-0000-0000-0000-000000000021"),idempotency_key="application-2")
    with pytest.raises(ValueApplicationError) as exc:
        _batch((first,second))
    assert exc.value.code == "duplicate_application_identity"


def test_receipt_and_batch_must_name_same_source():
    from core.domain.finance.value_application_contract import ReceiveAndApplyValueCommand, ValueApplicationError
    with pytest.raises(ValueApplicationError) as exc:
        ReceiveAndApplyValueCommand(_source(),_batch(source=UUID("33000000-0000-0000-0000-000000000002")))
    assert exc.value.code == "source_mismatch"


def test_receipt_without_application_is_valid_deposit():
    from core.domain.finance.value_application_contract import ReceiveAndApplyValueCommand
    assert ReceiveAndApplyValueCommand(_source()).application_batch is None


def test_batch_fingerprint_is_deterministic():
    assert _batch().request_fingerprint == _batch().request_fingerprint
    assert len(_batch().request_fingerprint) == 64


def test_balance_query_preaggregates_reversals():
    source=BALANCE.read_text(encoding="utf-8")
    assert "GROUP BY tenant_id,payment_allocation_id" in source
    assert "available=source-active" in source


def test_engine_sorts_targets_and_delegates_m32_locking():
    source=ENGINE.read_text(encoding="utf-8")
    assert "sorted(command.applications" in source
    assert "allocation_engine.allocate" in source
    assert "lock_value_source" not in source and "lock_obligation" not in source


def test_engine_delegates_final_write_to_m32():
    source=ENGINE.read_text(encoding="utf-8")
    assert "allocation_engine.allocate" in source
    assert "AllocateValueCommand" in source


def test_engine_has_no_commit():
    assert ".commit(" not in ENGINE.read_text(encoding="utf-8")


def test_zero_capacity_creates_no_fact():
    source=ENGINE.read_text(encoding="utf-8")
    zero=source[source.index("if amount == 0"):]
    assert zero.index("no_capacity") < zero.index("AllocateValueCommand")


def test_verifier_is_disposable_and_fail_safe():
    source=VERIFIER.read_text(encoding="utf-8")
    assert "xbos_track_b_m33_value_application_test" in source
    assert "retained" in source and "dropped=true" in source


def test_rehearsal_covers_core_workflows(authority):
    required={"deposit_unapplied","later_application","overpayment_residual","split_application","reversal_reopens_value","outer_rollback"}
    assert required <= authority["rehearsal"].keys()
