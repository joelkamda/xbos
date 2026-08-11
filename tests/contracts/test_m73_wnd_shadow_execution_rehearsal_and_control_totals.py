from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_financial_mapping_service import WndFinancialMappingService
from core.domain.finance.wnd_inventory_document_service import WndInventoryFinancialHandoffService
from core.domain.finance.wnd_shadow_rehearsal_contract import (
    CONTROL_NAMES, FinancialControlTotals, ProductionShapedRehearsal, ShadowCase,
    WndShadowRehearsalError, assert_rehearsal_replay,
)
from core.domain.finance.wnd_shadow_rehearsal_service import WndShadowRehearsalService

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)


def envelope(family, kind, payload, source_id="1"):
    return LegacyFinancialEnvelope(
        tenant_id=2, organization_unit_id=1, source_family=family,
        source_record_type=kind, source_record_id=source_id,
        source_updated_at=BASE, business_date=date(2026, 8, 11),
        payload={"kind": kind, **payload},
        correlation_id=UUID("73000000-0000-0000-0000-000000000001"),
    )


def sale(source_id="1"):
    return WndFinancialMappingService.map(envelope(LegacySourceFamily.COMMERCIAL, "commercial_sale", {
        "gross_amount": "100", "discount_amount": "10", "complimentary_amount": "5",
        "collected_amount": "60", "unpaid_amount": "25", "currency_code": "XAF",
        "revenue_nature": "food", "discount_reason": "promotion",
        "complimentary_reason": "service_recovery", "complimentary_policy": "service_recovery",
    }, source_id))


def inventory(*, status="verified", unit_cost="5"):
    return WndInventoryFinancialHandoffService.map(envelope(LegacySourceFamily.INVENTORY, "inventory_fulfillment", {
        "movement_type": "sale", "inventory_movement_id": "91", "atomic_unit_id": "4",
        "sale_id": "1", "quantity_delta": "-3", "unit_cost": unit_cost,
        "currency_code": "XAF", "cost_basis_status": status,
        "cost_basis_provenance": "stock_receipt", "cost_basis_evidence_hash": "a" * 64,
        "fulfillment_nature": "restaurant_inventory",
    }))


def case(sequence=1):
    return WndShadowRehearsalService.financial_case(sequence, sale(str(sequence)))


def test_contract_freezes_schema_neutral_r6_boundary():
    value = json.loads((ROOT / "contracts/finance/v1/m73_wnd_shadow_execution_rehearsal_and_control_totals.json").read_text())
    assert value["canonical_head"] == "m64_reconciliation_controls_020"
    assert value["source_commit"] == "beab542"
    assert value["migration"] is False
    assert value["execution_environment"] == "isolated_disposable"
    assert value["writer_routing"] == "unchanged"
    assert value["production_writes_allowed"] is False
    assert value["live_cutover_owner"] == "R6"


def test_sale_control_totals_are_exact():
    selected = case()
    assert selected.expected.values["commercial_revenue"] == Decimal("100")
    assert selected.expected.values["customer_allowances"] == Decimal("15")
    assert selected.expected.values["receivables_opened"] == Decimal("25")
    assert selected.expected.values["cash_collections"] == 0


def test_payment_and_receivable_repayment_are_not_revenue():
    common = {
        "amount": "40", "fee_amount": "0", "currency_code": "XAF",
        "payment_method_code": "cash", "payment_rail_code": "cash",
        "finality_status": "final", "evidence_hash": "b" * 64, "evidence_verified": True,
        "operational_account_public_id": "73000000-0000-0000-0001-000000000001",
    }
    payment = WndFinancialMappingService.map(envelope(LegacySourceFamily.PAYMENT, "payment_settlement", common))
    payment_case = WndShadowRehearsalService.financial_case(1, payment)
    assert payment_case.expected.values["cash_collections"] == 40
    assert payment_case.expected.values["commercial_revenue"] == 0
    repayment = WndFinancialMappingService.map(envelope(
        LegacySourceFamily.RECEIVABLE, "receivable_repayment",
        {**common, "financial_obligation_public_id": "73000000-0000-0000-0002-000000000001"}, "2"
    ))
    repayment_case = WndShadowRehearsalService.financial_case(2, repayment)
    assert repayment_case.expected.values["cash_collections"] == 40
    assert repayment_case.expected.values["receivables_satisfied"] == 40
    assert repayment_case.expected.values["commercial_revenue"] == 0


def test_refund_is_correction_not_negative_revenue_rewrite():
    plan = WndFinancialMappingService.map(envelope(LegacySourceFamily.ADJUSTMENT, "refund", {
        "amount": "20", "currency_code": "XAF", "evidence_hash": "c" * 64,
        "original_settlement_public_id": "73000000-0000-0000-0003-000000000001",
        "refund_settlement_public_id": "73000000-0000-0000-0004-000000000001",
        "refund_reason": "customer_return", "document_number": "CN-1",
    }))
    selected = WndShadowRehearsalService.financial_case(1, plan)
    assert selected.expected.values["refunds"] == 20
    assert selected.expected.values["commercial_revenue"] == 0


def test_verified_inventory_cost_is_included():
    selected = WndShadowRehearsalService.inventory_case(1, inventory())
    assert selected.disposition == "ready"
    assert selected.expected.values["fulfillment_cost"] == 15


def test_missing_historical_cost_remains_withheld():
    selected = WndShadowRehearsalService.inventory_case(
        1, inventory(status="missing", unit_cost="0"), withheld_currency_code="XAF"
    )
    assert selected.disposition == "withheld"
    assert selected.expected.values["fulfillment_cost"] == 0
    with pytest.raises(WndShadowRehearsalError) as raised:
        WndShadowRehearsalService.compare(selected, selected.expected)
    assert raised.value.code == "withheld_case_not_executable"


def test_withheld_case_requires_explicit_currency_from_source_snapshot():
    with pytest.raises(WndShadowRehearsalError) as raised:
        WndShadowRehearsalService.inventory_case(1, inventory(status="missing", unit_cost="0"))
    assert raised.value.code == "withheld_case_currency_required"


def test_control_total_shape_is_complete_and_decimal():
    totals = FinancialControlTotals("xaf", {"commercial_revenue": "1.25"})
    assert tuple(totals.values) == CONTROL_NAMES
    assert totals.currency_code == "XAF"
    assert all(isinstance(value, Decimal) for value in totals.values.values())


@pytest.mark.parametrize("currency", ["", "XA", "XAF1", "12F"])
def test_invalid_currency_fails_closed(currency):
    with pytest.raises(WndShadowRehearsalError):
        FinancialControlTotals(currency, {})


def test_unknown_control_fails_closed():
    with pytest.raises(WndShadowRehearsalError) as raised:
        FinancialControlTotals("XAF", {"forced_balance": 1})
    assert raised.value.code == "unsupported_control"


def test_case_and_source_snapshot_fingerprints_are_sha256():
    selected = case()
    with pytest.raises(WndShadowRehearsalError):
        ShadowCase(1, 2, 1, "sale:1", "invalid", "m71", selected.mapping_plan_fingerprint, selected.expected)
    with pytest.raises(WndShadowRehearsalError) as raised:
        ProductionShapedRehearsal("batch", "invalid", (selected,))
    assert raised.value.code == "invalid_source_snapshot_fingerprint"


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "0.000000001"])
def test_invalid_control_amount_fails_closed(value):
    with pytest.raises(WndShadowRehearsalError):
        FinancialControlTotals("XAF", {"cash_collections": value})


def test_assembly_normalizes_deterministic_order():
    assembled = WndShadowRehearsalService.assemble("batch-1", "d" * 64, (case(4), case(9)))
    assert [item.sequence for item in assembled.cases] == [1, 2]
    assert assembled.execution_environment == "isolated_disposable"
    assert assembled.writer_routing == "unchanged"
    assert assembled.live_cutover_owner == "R6"


def test_duplicate_source_in_rehearsal_fails_closed():
    selected = case()
    with pytest.raises(WndShadowRehearsalError) as raised:
        ProductionShapedRehearsal("batch", "d" * 64, (selected, ShadowCase(
            sequence=2, tenant_id=selected.tenant_id, organization_unit_id=selected.organization_unit_id,
            source_identity=selected.source_identity, source_fingerprint=selected.source_fingerprint,
            mapping_package=selected.mapping_package,
            mapping_plan_fingerprint=selected.mapping_plan_fingerprint, expected=selected.expected,
        )))
    assert raised.value.code == "duplicate_source_case"


@pytest.mark.parametrize("field,value", [
    ("execution_environment", "production"), ("writer_routing", "canonical"),
    ("migration_authority", "m73"), ("live_cutover_owner", "M7"),
])
def test_unsafe_rehearsal_boundaries_fail_closed(field, value):
    kwargs = {field: value}
    with pytest.raises(WndShadowRehearsalError) as raised:
        ProductionShapedRehearsal("batch", "d" * 64, (case(),), **kwargs)
    assert raised.value.code == "unsafe_rehearsal_boundary"


def test_matched_comparison_is_deterministic():
    selected = case()
    result = WndShadowRehearsalService.compare(selected, selected.expected)
    assert result.status == "matched"
    assert not any(result.deltas.values())
    again = WndShadowRehearsalService.compare(selected, selected.expected)
    assert again.comparison_fingerprint == result.comparison_fingerprint


def test_variance_is_exposed_not_forced_to_balance():
    selected = case()
    observed = FinancialControlTotals("XAF", {"commercial_revenue": "99", "customer_allowances": "15",
                                                        "receivables_opened": "25"})
    result = WndShadowRehearsalService.compare(selected, observed)
    assert result.status == "variance"
    assert result.deltas["commercial_revenue"] == Decimal("-1")


def test_cross_currency_comparison_fails_closed():
    selected = case()
    with pytest.raises(WndShadowRehearsalError) as raised:
        WndShadowRehearsalService.compare(selected, FinancialControlTotals("USD", {}))
    assert raised.value.code == "control_currency_mismatch"


def test_rehearsal_replay_returns_existing_and_conflict_fails():
    first = WndShadowRehearsalService.assemble("batch", "d" * 64, (case(),))
    same = WndShadowRehearsalService.assemble("batch", "d" * 64, (case(),))
    assert assert_rehearsal_replay(first, same) is first
    changed = WndShadowRehearsalService.assemble("batch", "e" * 64, (case(),))
    with pytest.raises(WndShadowRehearsalError) as raised:
        assert_rehearsal_replay(first, changed)
    assert raised.value.code == "rehearsal_idempotency_conflict"


def test_no_schema_writer_or_cutover_authority_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m73_*.py"))
    marker = (ROOT / "core/persistence/m73_wnd_shadow_rehearsal.py").read_text()
    assert "SCHEMA_NEUTRAL = True" in marker
    assert "PRODUCTION_WRITES_ALLOWED = False" in marker
    assert "REROUTES_LEGACY_WRITERS = False" in marker
    assert "PERFORMS_LIVE_CUTOVER = False" in marker


def test_package_and_gate_artifacts_exist():
    assert (ROOT / "XBOS_M7_3_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M7_3_INSTALL_AND_VERIFY.txt").is_file()
