from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_financial_mapping_contract import WndFinancialMappingError, assert_replay
from core.domain.finance.wnd_financial_mapping_service import WndFinancialMappingService

ROOT = Path(__file__).resolve().parents[2]
BASE_TIME = datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc)


def envelope(family, kind, payload, *, source_id="1"):
    return LegacyFinancialEnvelope(
        tenant_id=2, organization_unit_id=1, source_family=family,
        source_record_type=kind, source_record_id=source_id,
        source_updated_at=BASE_TIME, business_date=date(2026, 8, 11),
        payload={"kind": kind, **payload},
        correlation_id=UUID("71000000-0000-0000-0000-000000000001"),
    )


def sale(**changes):
    payload = {
        "gross_amount": "10000", "discount_amount": "500", "complimentary_amount": "500",
        "collected_amount": "7000", "unpaid_amount": "2000", "currency_code": "XAF",
        "revenue_nature": "restaurant_sale", "discount_reason": "approved_discount",
        "complimentary_reason": "service_recovery", "complimentary_policy": "service_recovery",
    }
    payload.update(changes)
    return envelope(LegacySourceFamily.COMMERCIAL, "commercial_sale", payload)


def payment(kind="payment_settlement", family=LegacySourceFamily.PAYMENT, **changes):
    payload = {
        "amount": "2000", "fee_amount": "0", "currency_code": "XAF", "payment_method_code": "cash",
        "payment_rail_code": "cash", "operational_account_public_id": "71000000-0000-0000-0001-000000000001",
        "finality_status": "final", "evidence_verified": True, "evidence_hash": "a" * 64,
    }
    if kind == "receivable_repayment":
        payload["financial_obligation_public_id"] = "71000000-0000-0000-0002-000000000001"
    payload.update(changes)
    return envelope(family, kind, payload)


def test_contract_is_schema_neutral_and_keeps_r6_cutover():
    contract = json.loads((ROOT / "contracts/finance/v1/m71_wnd_source_to_canonical_financial_mapping.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == "m64_reconciliation_controls_020"
    assert contract["migration"] is False
    assert contract["execution_mode"] == "mapping_plan_only"
    assert contract["writer_routing"] == "unchanged"
    assert contract["live_cutover_owner"] == "R6"


def test_commercial_sale_maps_revenue_terms_and_receivable_in_order():
    plan = WndFinancialMappingService.map(sale())
    assert [item.command_type for item in plan.commands] == [
        "CanonicalFinancialEventCommand", "RecognizeCommercialTermsCommand", "OpenReceivableCommand"
    ]
    assert plan.commands[0].payload["amount"] == Decimal("10000")
    assert plan.commands[1].payload["customer_collectible_amount"] == Decimal("9000")
    assert plan.commands[2].payload["original_amount"] == Decimal("2000")


def test_fully_paid_sale_does_not_open_receivable():
    plan = WndFinancialMappingService.map(sale(collected_amount="9000", unpaid_amount="0"))
    assert "OpenReceivableCommand" not in [item.command_type for item in plan.commands]


def test_sale_without_allowances_skips_commercial_terms_component_command():
    plan = WndFinancialMappingService.map(sale(discount_amount="0", complimentary_amount="0", collected_amount="8000"))
    assert [item.command_type for item in plan.commands] == ["CanonicalFinancialEventCommand", "OpenReceivableCommand"]


@pytest.mark.parametrize("field,value", [
    ("discount_amount", "10001"), ("complimentary_amount", "10001"), ("collected_amount", "8000"),
])
def test_invalid_commercial_capacity_or_totals_fail_closed(field, value):
    with pytest.raises(WndFinancialMappingError):
        WndFinancialMappingService.map(sale(**{field: value}))


@pytest.mark.parametrize("policy", ["", "gift", "manager_choice"])
def test_unapproved_complimentary_policy_fails_closed(policy):
    with pytest.raises(WndFinancialMappingError) as raised:
        WndFinancialMappingService.map(sale(complimentary_policy=policy))
    assert raised.value.code in {"required_field_missing", "complimentary_policy_invalid"}


def test_payment_maps_intent_then_verified_settlement_without_revenue():
    plan = WndFinancialMappingService.map(payment())
    assert [item.command_type for item in plan.commands] == ["CreatePaymentIntentCommand", "CreatePaymentSettlementCommand"]
    effects = {effect for item in plan.commands for effect in item.economic_effects}
    assert "no_revenue" in effects
    assert "revenue_recognition" not in effects


def test_receivable_repayment_adds_allocation_and_never_revenue():
    plan = WndFinancialMappingService.map(payment("receivable_repayment", LegacySourceFamily.RECEIVABLE))
    assert [item.command_type for item in plan.commands] == [
        "CreatePaymentIntentCommand", "CreatePaymentSettlementCommand", "ReceiveReceivablePaymentCommand"
    ]
    assert all("revenue_recognition" not in item.economic_effects for item in plan.commands)


@pytest.mark.parametrize("finality,verified", [("pending", True), ("final", False), ("pending", False)])
def test_raw_or_unverified_provider_success_is_not_settlement(finality, verified):
    with pytest.raises(WndFinancialMappingError) as raised:
        WndFinancialMappingService.map(payment(finality_status=finality, evidence_verified=verified))
    assert raised.value.code == "verified_finality_required"


def test_non_cash_requires_external_provider_transaction_identity():
    with pytest.raises(WndFinancialMappingError) as raised:
        WndFinancialMappingService.map(payment(payment_method_code="mtn_mobile_money", payment_rail_code="mobile_money"))
    assert raised.value.code == "external_settlement_identity_required"


def test_verified_non_cash_settlement_is_supported():
    plan = WndFinancialMappingService.map(payment(
        payment_method_code="mtn_mobile_money", payment_rail_code="mobile_money",
        external_settlement_reference="M71-TXN-1",
    ))
    assert plan.commands[1].payload["external_settlement_reference"] == "M71-TXN-1"


def test_offline_cash_uses_governed_evidence_without_fake_provider_reference():
    plan = WndFinancialMappingService.map(payment())
    assert plan.commands[1].payload["payment_method_code"] == "cash"
    assert plan.commands[1].payload["external_settlement_reference"] is None


@pytest.mark.parametrize("evidence", ["A" * 64, "a" * 63, "x" * 64, ""])
def test_invalid_evidence_hash_fails_closed(evidence):
    with pytest.raises(WndFinancialMappingError) as raised:
        WndFinancialMappingService.map(payment(evidence_hash=evidence))
    assert raised.value.code == "evidence_hash_required"


def test_refund_is_append_only_correction_plan():
    plan = WndFinancialMappingService.map(envelope(LegacySourceFamily.ADJUSTMENT, "refund", {
        "amount": "500", "currency_code": "XAF",
        "original_settlement_public_id": "71000000-0000-0000-0003-000000000001",
        "refund_settlement_public_id": "71000000-0000-0000-0003-000000000002",
        "refund_reason": "customer_return", "document_number": "RN-1", "evidence_hash": "b" * 64,
    }))
    assert [item.command_type for item in plan.commands] == ["RecognizeRefundCommand"]
    assert plan.commands[0].economic_effects == ("settlement_out", "correction_append", "original_revenue_immutable")


def test_identical_replay_returns_original_plan():
    first = WndFinancialMappingService.map(sale())
    second = WndFinancialMappingService.map(sale())
    assert first.plan_fingerprint == second.plan_fingerprint
    assert assert_replay(first, second) is first


def test_changed_payload_under_same_source_identity_conflicts():
    first = WndFinancialMappingService.map(sale())
    changed = WndFinancialMappingService.map(sale(gross_amount="11000", collected_amount="8000"))
    with pytest.raises(WndFinancialMappingError) as raised:
        assert_replay(first, changed)
    assert raised.value.code == "mapping_idempotency_conflict"


def test_command_identities_are_stable_and_unique():
    first = WndFinancialMappingService.map(sale())
    second = WndFinancialMappingService.map(sale())
    assert [item.public_id for item in first.commands] == [item.public_id for item in second.commands]
    assert len({item.public_id for item in first.commands}) == len(first.commands)


def test_wrong_source_family_fails_closed():
    with pytest.raises(WndFinancialMappingError) as raised:
        WndFinancialMappingService.map(payment(family=LegacySourceFamily.COMMERCIAL))
    assert raised.value.code == "source_family_mismatch"


def test_plan_and_commands_cannot_enable_execution():
    plan = WndFinancialMappingService.map(sale())
    assert plan.execution_allowed is False
    assert all(item.execution_allowed is False for item in plan.commands)
    assert plan.writer_routing == "unchanged"


def test_no_m71_migration_or_writer_routing_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m71_*.py"))
    marker = (ROOT / "core/persistence/m71_wnd_financial_mapping.py").read_text(encoding="utf-8")
    assert "SCHEMA_NEUTRAL = True" in marker
    assert "EXECUTES_CANONICAL_COMMANDS = False" in marker
    assert "REROUTES_LEGACY_WRITERS = False" in marker


def test_gate_and_install_artifacts_exist():
    assert (ROOT / "XBOS_M7_1_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M7_1_INSTALL_AND_VERIFY.txt").is_file()
