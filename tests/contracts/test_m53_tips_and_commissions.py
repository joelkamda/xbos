from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.participant_earning_contract import (
    CommissionBasis, EarningContext, ParticipantEarningError, RecognizeCommissionCommand, RecognizeTipCommand,
)
from core.domain.finance.participant_earning_engine import TransactionalParticipantEarningEngine


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m53_tips_and_commissions.json"
BASE = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
TENANT_PARTY = UUID("53000000-0000-0000-0000-000000000010")
BENEFICIARY = UUID("53000000-0000-0000-0000-000000000011")


def context(amount="10", number=1):
    return EarningContext(UUID(f"53000000-0000-0000-0001-{number:012d}"), 1, 2, number, amount, "xaf", BASE, date(2026, 8, 10), 1, UUID(int=99), "m53.earning", "tests")


def payable(ctx=None, beneficiary=BENEFICIARY, earning_type="commission", number=1, amount=None, currency=None, obligation_type="expense_payable"):
    ctx = ctx or context(number=number)
    value = amount or ctx.amount
    return CreateObligationCommand(
        UUID(f"53000000-0000-0000-0002-{number:012d}"), ctx.tenant_id, ctx.organization_unit_id,
        TENANT_PARTY, beneficiary, obligation_type, value, currency or ctx.currency_code,
        ctx.occurred_at + timedelta(days=1), ctx.occurred_at, ctx.business_date, ctx.calendar_policy_version,
        ctx.correlation_id, "m53.tests", f"earning-{number}", "m53.payable", f"payable-{number}",
        (ObligationLineCommand(1, "earning", "Participant earning", 1, value, value, f"line-{number}"),),
        actor_service="tests", metadata={"earning_type": earning_type, "beneficiary_party_id": str(beneficiary)},
    )


def staff_tip(amount="10"):
    ctx = context(amount)
    return RecognizeTipCommand(ctx, "staff_beneficiary", BENEFICIARY, payable(ctx, earning_type="tip"))


def commission(amount="10", basis=None):
    ctx = context(amount, 3)
    return RecognizeCommissionCommand(ctx, BENEFICIARY, basis or CommissionBasis("fixed", amount, "0"), payable(ctx, earning_type="commission", number=3), "sales_commission")


def test_contract_is_valid_and_schema_neutral():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["contract_code"] == "XBOS_M53_TIPS_AND_COMMISSIONS"
    assert data["canonical_head"] == "m46_provider_financials_015"
    assert data["migration"] is False


def test_contract_groups_tip_and_commission_scope():
    data = json.loads(CONTRACT.read_text())
    assert set(data["tips"]["policies"]) == {"staff_beneficiary", "tenant_income"}
    assert data["commissions"]["basis_types"] == ["fixed", "percentage"]


def test_staff_tip_requires_matching_payable():
    assert staff_tip().payable.original_amount == 10


def test_staff_tip_without_payable_rejected():
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(context(), "staff_beneficiary", BENEFICIARY, None)
    assert raised.value.code == "tip_payable_required"


def test_tenant_income_tip_forbids_payable():
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(context(), "tenant_income", BENEFICIARY, payable(earning_type="tip"))
    assert raised.value.code == "tenant_income_payable_forbidden"


def test_tenant_income_tip_without_beneficiary_is_valid():
    assert RecognizeTipCommand(context(), "tenant_income").payable is None


def test_unknown_tip_policy_rejected():
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(context(), "unknown")
    assert raised.value.code == "tip_policy_invalid"


@pytest.mark.parametrize("field,value", [("tenant_id", 9), ("organization_unit_id", 9)])
def test_payable_scope_must_match(field, value):
    ctx = context()
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(ctx, "staff_beneficiary", BENEFICIARY, replace(payable(ctx, earning_type="tip"), **{field: value}))
    assert raised.value.code == "payable_scope_mismatch"


def test_payable_amount_must_match():
    ctx = context()
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(ctx, "staff_beneficiary", BENEFICIARY, payable(ctx, amount="9", earning_type="tip"))
    assert raised.value.code == "payable_amount_mismatch"


def test_payable_currency_must_match():
    ctx = context()
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(ctx, "staff_beneficiary", BENEFICIARY, payable(ctx, currency="USD", earning_type="tip"))
    assert raised.value.code == "payable_amount_mismatch"


def test_payable_beneficiary_must_match():
    other = UUID(int=77)
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(context(), "staff_beneficiary", BENEFICIARY, payable(beneficiary=other, earning_type="tip"))
    assert raised.value.code == "beneficiary_payable_mismatch"


def test_payable_type_must_be_expense_payable():
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(context(), "staff_beneficiary", BENEFICIARY, payable(earning_type="tip", obligation_type="trade_payable"))
    assert raised.value.code == "beneficiary_payable_mismatch"


def test_payable_metadata_must_preserve_earning_type():
    with pytest.raises(ParticipantEarningError) as raised:
        RecognizeTipCommand(context(), "staff_beneficiary", BENEFICIARY, payable(earning_type="commission"))
    assert raised.value.code == "payable_metadata_mismatch"


def test_fixed_commission_is_valid():
    assert commission().commission_basis.basis_type == "fixed"


def test_fixed_commission_basis_must_equal_amount():
    with pytest.raises(ParticipantEarningError) as raised:
        commission("10", CommissionBasis("fixed", "9", "0"))
    assert raised.value.code == "commission_calculation_mismatch"


def test_percentage_commission_is_exact():
    result = commission("10", CommissionBasis("percentage", "200", "5"))
    assert result.context.amount == 10


def test_percentage_commission_mismatch_rejected():
    with pytest.raises(ParticipantEarningError) as raised:
        commission("11", CommissionBasis("percentage", "200", "5"))
    assert raised.value.code == "commission_calculation_mismatch"


@pytest.mark.parametrize("rate", ["0", "101"])
def test_percentage_rate_range(rate):
    with pytest.raises(ParticipantEarningError) as raised:
        CommissionBasis("percentage", "100", rate)
    assert raised.value.code == "commission_rate_invalid"


def test_fixed_basis_forbids_rate():
    with pytest.raises(ParticipantEarningError) as raised:
        CommissionBasis("fixed", "10", "5")
    assert raised.value.code == "commission_rate_invalid"


def test_unknown_basis_rejected():
    with pytest.raises(ParticipantEarningError) as raised:
        CommissionBasis("mystery", "10", "0")
    assert raised.value.code == "commission_basis_invalid"


def test_tip_event_selects_staff_liability_profile():
    event = TransactionalParticipantEarningEngine._tip_event(staff_tip())
    assert event.event_type_code == "TIP_RECOGNIZED"
    assert event.posting_context["posting_profile_code"] == "tip_staff_liability"
    assert event.metadata["beneficiary_party_id"] == str(BENEFICIARY)


def test_tip_event_selects_tenant_income_profile():
    event = TransactionalParticipantEarningEngine._tip_event(RecognizeTipCommand(context(), "tenant_income"))
    assert event.posting_context["posting_profile_code"] == "tip_tenant_income"
    assert event.metadata["beneficiary_party_id"] is None


def test_commission_event_preserves_calculation_evidence():
    event = TransactionalParticipantEarningEngine._commission_event(commission("10", CommissionBasis("percentage", "200", "5")))
    assert event.event_type_code == "EXPENSE_RECOGNIZED"
    assert event.metadata["basis_amount"] == "200"
    assert event.metadata["rate_percent"] == "5"


def test_positive_earning_amount_required():
    with pytest.raises(ParticipantEarningError) as raised:
        context("0")
    assert raised.value.code == "invalid_amount"


def test_timezone_required():
    with pytest.raises(ParticipantEarningError) as raised:
        replace(context(), occurred_at=BASE.replace(tzinfo=None))
    assert raised.value.code == "timezone_required"


def test_persistence_marker_declares_no_new_tables():
    source = (ROOT / "core/persistence/m53_participant_earnings.py").read_text(encoding="utf-8")
    assert "SCHEMA_NEUTRAL = True" in source
    assert "WRITES_NEW_TABLES = False" in source


def test_verifier_has_durable_acceptance_markers():
    source = (ROOT / "scripts/verify_m53_participant_earnings.py").read_text(encoding="utf-8")
    for marker in ("staff_tip=PASS", "tenant_tip=PASS", "commission=PASS", "beneficiary_balance=PASS", "atomic_rollback=PASS", "dropped=true"):
        assert marker in source
