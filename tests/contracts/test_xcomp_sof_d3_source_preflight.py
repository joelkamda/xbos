"""SOF XCOMP D3 source-only nonoperative Finance negatives, no network/DB."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from shared_operations.xcomp_d3_source_preflight import (
    FinanceTrace, ServerPricedOrder, inspect_source_trace, inspect_vip_same_stock,
    replay_disposition, SOURCE_CONTRACT, NONEFFECTIVE,
)


def order(**changes):
    base = ServerPricedOrder(
        tenant_id=910001, organization_unit_id=5,
        order_public_id="synthetic-r1-order-001", item_public_id="guinness-stock-item",
        stock_identity="stock:guinness-original-single-identity",
        price_public_id="server-price-vip-44", price_code="VIP",
        selected_price_code="VIP", server_quote_ref="so1:quote:signed-server-ref-candidate",
        unit_price=Decimal("1500"), quantity=Decimal("2"), currency="XAF",
    )
    return replace(base, **changes)


def trace(**changes):
    base = FinanceTrace(
        tenant_id=910001, organization_unit_id=5,
        order_public_id="synthetic-r1-order-001",
        currency="XAF", obligation_amount=Decimal("3000"),
        settlement_amount=Decimal("0"), receivable_balance=Decimal("3000"),
        receivable_ref="m5:ar:synthetic001", payment_state="CREATED",
        idempotency_key="910001:5:synthetic-r1-order-001",
    )
    return replace(base, **changes)


def findings(o=None, f=None):
    return inspect_source_trace(o or order(), f or trace()).findings


def final_full(**changes):
    fields = dict(settlement_amount=Decimal("3000"), receivable_balance=Decimal("0"),
                  receivable_ref=None, payment_state="PROVIDER_FINAL_OBSERVED",
                  provider_event_ref="gw:test-only-event-1",
                  settlement_ref="m4:test-only-settlement-1",
                  journal_ref="m2:test-only-journal-1",
                  finance_readback_ref="m6:test-only-readback-1")
    fields.update(changes)
    return trace(**fields)


def test_01_default_unpaid_source_consistent_not_paid():
    r = inspect_source_trace(order(), trace())
    assert r.source_consistent and not r.findings
    assert r.source_grade == NONEFFECTIVE and r.contract == SOURCE_CONTRACT
    assert not r.paid_status_authorized and not r.ledger_write_authorized


def test_02_no_operative_authority_even_after_all_refs():
    r = inspect_source_trace(order(), final_full())
    assert r.source_consistent and not r.findings
    assert not any([r.runtime_effect_authorized, r.paid_status_authorized,
                    r.commission_or_payout_authorized, r.ledger_write_authorized,
                    r.close_authorized])


@pytest.mark.parametrize("override", [
    {"tenant_id": 910002}, {"organization_unit_id": 99},
    {"order_public_id": "other-order"},
])
def test_03_cross_tenant_org_order_denied(override):
    assert "TENANT_OR_ORDER_CROSSOVER" in findings(f=trace(**override))


def test_04_empty_or_negative_scope_denied():
    assert "INVALID_SCOPE" in findings(f=trace(tenant_id=0))


def test_05_missing_server_price_ref_denied():
    assert "MISSING_SERVER_PRICE_IDENTITY" in findings(o=order(server_quote_ref=""))


def test_06_caller_supplied_price_not_authority():
    assert "CLIENT_SUPPLIED_PRICE_FORBIDDEN" in findings(o=order(source_kind="CLIENT_CART_PRICE"))


def test_07_vip_caller_cheap_price_denied():
    assert "AREA_PRICE_CODE_MISMATCH" in findings(o=order(selected_price_code="STANDARD"))


def test_08_source_price_mismatch_denied():
    assert "SOURCE_PRICE_OBLIGATION_MISMATCH" in findings(o=order(unit_price=Decimal("1000")))


def test_09_currency_mismatch_denied():
    assert "CURRENCY_MISMATCH" in findings(f=trace(currency="USD"))


def test_10_bad_money_denied_even_in_source():
    with pytest.raises(ValueError, match="NONFINITE"):
        inspect_source_trace(order(unit_price=Decimal("NaN")), trace())
    with pytest.raises(ValueError, match="NEGATIVE_OR_ZERO"):
        inspect_source_trace(order(quantity=Decimal("0")), trace())


def test_11_checkout_created_is_not_paid():
    f = trace(settlement_amount=Decimal("3000"), receivable_balance=Decimal("0"),
              receivable_ref=None, payment_state="CREATED")
    assert "CHECKOUT_CREATED_OR_UNKNOWN_IS_NOT_SETTLEMENT" in findings(f=f)


@pytest.mark.parametrize("state", ["UNKNOWN", "FAILED"])
def test_12_timeout_failure_not_settlement(state):
    f = trace(settlement_amount=Decimal("1000"), receivable_balance=Decimal("2000"),
              payment_state=state)
    assert "CHECKOUT_CREATED_OR_UNKNOWN_IS_NOT_SETTLEMENT" in findings(f=f)


def test_13_final_observed_without_external_plus_m2_readback_denied():
    f = trace(payment_state="PROVIDER_FINAL_OBSERVED",
              settlement_amount=Decimal("3000"), receivable_balance=Decimal("0"),
              receivable_ref=None)
    assert "INDEPENDENT_PROVIDER_AND_FINANCE_PROOF_NOT_SUPPLIED" in findings(f=f)


def test_14_double_or_over_capacity_tender_denied():
    f = trace(settlement_amount=Decimal("3500"), receivable_balance=Decimal("0"),
              payment_state="PROVIDER_FINAL_OBSERVED")
    a = findings(f=f)
    assert "TENDER_OVER_CAPACITY" in a and "AR_NOT_OUTSTANDING_REMAINDER" in a


def test_15_unpaid_amount_must_be_ar_not_cash():
    assert "AR_NOT_OUTSTANDING_REMAINDER" in findings(
        f=trace(settlement_amount=Decimal("0"), receivable_balance=Decimal("0")))


def test_16_ar_must_have_reference():
    assert "AR_RECEIVABLE_REFERENCE_MISSING" in findings(f=trace(receivable_ref=None))


def test_17_partial_settlement_keeps_receivable():
    f = final_full(settlement_amount=Decimal("1000"), receivable_balance=Decimal("2000"),
                   receivable_ref="m5:partial-ar")
    assert inspect_source_trace(order(), f).source_consistent


def test_18_no_commission_on_created_or_partial_payment():
    assert "COMMISSION_BEFORE_FULL_VERIFIED_PAYMENT_DENIED" in findings(
        f=trace(commission_requested=True))
    assert "COMMISSION_BEFORE_FULL_VERIFIED_PAYMENT_DENIED" in findings(
        f=final_full(settlement_amount=Decimal("1000"),
                     receivable_balance=Decimal("2000"),
                     receivable_ref="ar:remaining", commission_requested=True))


def test_19_no_commission_source_effect_even_on_full():
    assert "COMMISSION_EFFECT_NOT_ADMITTED_BY_SOURCE_PREFLIGHT" in findings(
        f=final_full(commission_requested=True))


def test_20_refund_must_link_original_settlement():
    assert "UNLINKED_REFUND_FORBIDDEN" in findings(
        f=final_full(refund_amount=Decimal("200")))


def test_21_refund_cannot_exceed_paid():
    assert "REFUND_EXCEEDS_SETTLED_VALUE" in findings(
        f=final_full(refund_amount=Decimal("3500"),
                     refund_original_settlement_ref="m4:original-1"))


def test_22_linked_partial_refund_structurally_consistent_not_executed():
    f = final_full(refund_amount=Decimal("300"),
                   refund_original_settlement_ref="m4:original-1")
    r = inspect_source_trace(order(), f)
    assert r.source_consistent and not r.runtime_effect_authorized


def test_23_no_revenue_on_ar_repayment():
    assert "AR_REPAYMENT_IS_NOT_NEW_REVENUE" in findings(
        f=final_full(repayment_as_new_revenue=True))


def test_24_no_monthly_bank_ar_reset():
    assert "MONTHLY_BANK_OR_AR_RESET_FORBIDDEN" in findings(
        f=trace(monthly_reset_requested=True))


def test_25_no_payroll_or_payout():
    assert "PAYROLL_OR_PAYOUT_NOT_ADMITTED" in findings(
        f=final_full(payout_requested=True))


def test_26_missing_idempotency_key_denied():
    assert "MISSING_IDEMPOTENCY_KEY" in findings(f=trace(idempotency_key=""))


def test_27_exact_replay_and_conflict_are_distinct():
    r = inspect_source_trace(order(), trace())
    scoped = "910001:5:source-001"
    assert replay_disposition({}, scoped, r.fingerprint) == "FIRST_SOURCE_OBSERVATION_ONLY"
    assert replay_disposition({scoped: r.fingerprint}, scoped, r.fingerprint) == "EXACT_REPLAY_NO_NEW_EFFECT"
    assert replay_disposition({scoped: r.fingerprint}, scoped, "different") == "DENY_CONFLICTING_REPLAY"


def test_28_changed_fingerprint_same_key_denied():
    r = inspect_source_trace(order(), trace())
    assert "IDEMPOTENCY_KEY_CHANGED_PAYLOAD_DENIED" in findings(
        f=trace(prior_payload_fingerprint="different-blob"))
    assert len(r.fingerprint) == 64


def test_29_vip_standard_different_price_one_stock_identity():
    standard = order(price_code="STANDARD", selected_price_code="STANDARD",
                     price_public_id="standard-1", unit_price=Decimal("1000"))
    vip = order(price_code="VIP", selected_price_code="VIP",
                price_public_id="vip-1", unit_price=Decimal("1500"))
    assert inspect_vip_same_stock(standard, vip) == ()


def test_30_vip_duplicate_stock_identity_denied():
    vip = order(stock_identity="vip-second-stock-id")
    standard = order(price_code="STANDARD", selected_price_code="STANDARD")
    assert "VIP_DUPLICATE_STOCK_IDENTITY_DENIED" in inspect_vip_same_stock(standard, vip)


def test_31_vip_wrong_tenant_denied():
    vip = order(tenant_id=910002)
    standard = order(price_code="STANDARD", selected_price_code="STANDARD")
    assert "VIP_TENANT_CROSSOVER" in inspect_vip_same_stock(standard, vip)


def test_32_no_price_code_downshift():
    vip = order(selected_price_code="STANDARD")
    standard = order(price_code="STANDARD", selected_price_code="STANDARD")
    assert "VIP_CALLER_PRICE_DOWNGRADE_DENIED" in inspect_vip_same_stock(standard, vip)


def test_33_stale_close_window_denied():
    t0 = datetime(2026, 11, 9, 7, tzinfo=timezone.utc)
    f = final_full(close_requested=True, close_as_of=t0,
                   period_event_at=t0 + timedelta(minutes=10),
                   calendar_policy_ref="wnd:calendar:v1",
                   independent_actual_ref="cashcount:independent",
                   close_variance=Decimal("0"))
    assert "STALE_CLOSE_AS_OF" in findings(f=f)


def test_34_unverified_close_independent_actual_and_calendar_denied():
    t0 = datetime(2026, 11, 9, 7, tzinfo=timezone.utc)
    f = final_full(close_requested=True, close_as_of=t0,
                   period_event_at=t0, close_variance=Decimal("0"))
    r = findings(f=f)
    assert "MISSING_TENANT_CALENDAR" in r
    assert "CLOSE_MISSING_INDEPENDENT_ACTUAL" in r


def test_35_close_variance_never_auto_approved():
    t0 = datetime(2026, 11, 9, 7, tzinfo=timezone.utc)
    f = final_full(close_requested=True, close_as_of=t0,
                   period_event_at=t0, calendar_policy_ref="wnd:calendar:v1",
                   independent_actual_ref="cashcount:independent",
                   close_variance=Decimal("100"))
    r = findings(f=f)
    assert "CLOSE_VARIANCE_UNEXPLAINED" in r
    assert "CLOSE_EFFECT_NOT_ADMITTED_BY_SOURCE_PREFLIGHT" in r


def test_36_close_remains_nonoperative_even_consistent_source_refs():
    t0 = datetime(2026, 11, 9, 7, tzinfo=timezone.utc)
    f = final_full(close_requested=True, close_as_of=t0,
                   period_event_at=t0, calendar_policy_ref="wnd:calendar:v1",
                   independent_actual_ref="cashcount:independent",
                   close_variance=Decimal("0"))
    r = inspect_source_trace(order(), f)
    assert not r.close_authorized
    assert "CLOSE_EFFECT_NOT_ADMITTED_BY_SOURCE_PREFLIGHT" in r.findings


def test_37_existing_domain_source_anchors_present():
    root = Path(__file__).resolve().parents[2]
    for path in [
        "restaurant/r1/contracts.py", "restaurant/r3/service.py",
        "core/domain/finance/obligation_engine.py",
        "core/domain/finance/payment_tender_engine.py",
        "core/domain/finance/payment_settlement_engine.py",
        "core/domain/finance/transactional_event_engine.py",
        "core/domain/finance/receivable_engine.py",
        "core/domain/finance/reconciliation_close_engine.py",
        "shared_operations/so3/service.py",
        "contracts/finance/v1/m53_tips_and_commissions.json",
    ]:
        assert (root / path).is_file(), path


def test_38_r3_descriptive_finance_only():
    root = Path(__file__).resolve().parents[2]
    contract = json.loads((root / "contracts/restaurant/v1/r3_public_interfaces.json").read_text())
    assert contract["finance_execution"] == "FORBIDDEN"


def test_39_provider_uncertainty_contract_present():
    root = Path(__file__).resolve().parents[2]
    contract = json.loads((root / "contracts/finance/v1/m82_external_provider_and_infrastructure_failure_resilience.json").read_text())
    assert contract and isinstance(contract, dict)
    assert "m82" in "m82_external_provider_and_infrastructure_failure_resilience"


def test_40_stock_valuation_not_stock_quantity():
    root = Path(__file__).resolve().parents[2]
    authority = json.loads((root / "contracts/shared_operations/v1/so3_authority.json").read_text())
    assert authority["financial_valuation"] == "EXCLUDED"


def test_41_payments_only_cannot_enter_restaurant_r1():
    assert "PAYMENTS_ONLY_MUST_BYPASS_R1" in findings(
        o=order(merchant_profile="payments_only"))


def test_42_equivalent_decimal_repr_one_canonical_fingerprint():
    a = inspect_source_trace(order(unit_price=Decimal("1500.00")),
                             trace(obligation_amount=Decimal("3000.000")))
    b = inspect_source_trace(order(unit_price=Decimal("1500")),
                             trace(obligation_amount=Decimal("3000")))
    assert a.fingerprint == b.fingerprint
    assert a.source_consistent and b.source_consistent


def test_43_refund_replay_same_identity_read_only():
    f = final_full(refund_amount=Decimal("250"),
                   refund_original_settlement_ref="m4:original-1")
    a = inspect_source_trace(order(), f)
    b = inspect_source_trace(order(), f)
    assert a.fingerprint == b.fingerprint
    assert replay_disposition({f.idempotency_key: a.fingerprint}, f.idempotency_key,
                              b.fingerprint) == "EXACT_REPLAY_NO_NEW_EFFECT"


def test_44_stock_same_target_with_distinct_prices_cannot_be_secretly_second_item():
    standard = order(price_code="STANDARD", selected_price_code="STANDARD",
                     item_public_id="product-A")
    vip = order(item_public_id="product-B")
    assert "VIP_DIFFERENT_ITEM_CANNOT_COMPARE" in inspect_vip_same_stock(standard, vip)


def test_45_versioned_source_matrix_twelve_seams_preserved():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "shared_operations_contracts/xcomp_sof_d3_source_test_matrix_v1.json").read_text())
    assert data["schema"] == "xcomp.sof.d3.source_test_matrix.v1"
    assert data["base_source_commit"] == "47842917c102908e61e15318332eb5d55d50094c"
    assert len(data["seams"]) == 12
    assert [x["id"] for x in data["seams"]] == [f"S{i:02d}" for i in range(1, 13)]
    assert all(x["independent_hosted_proof"] == "NOT_ADMITTED" for x in data["seams"])


def test_46_every_seam_source_exists_and_negative_explicit():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "shared_operations_contracts/xcomp_sof_d3_source_test_matrix_v1.json").read_text())
    for seam in data["seams"]:
        assert (root / seam["source_path"]).is_file(), seam["id"]
        assert seam["negative_codes"]
        assert seam["producer"] and seam["consumer"] and seam["invariant"]


def test_47_matrix_does_not_promote_runtime():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "shared_operations_contracts/xcomp_sof_d3_source_test_matrix_v1.json").read_text())
    assert not any(data["effective"].values())
    assert "SYNTHETIC_910001_NOT_PRODUCTION_TENANT2" == data["merchant_policy"]["A"]
    assert "No money transfers" in data["no_side_effects"]


def test_48_source_inspection_cannot_set_paid_even_with_forged_strings():
    f = final_full(provider_event_ref="attacker-string-not-verified",
                   settlement_ref="attacker-string",
                   journal_ref="attacker-string",
                   finance_readback_ref="attacker-string")
    r = inspect_source_trace(order(), f)
    assert r.source_consistent
    assert r.runtime_effect_authorized is False
    assert r.paid_status_authorized is False
