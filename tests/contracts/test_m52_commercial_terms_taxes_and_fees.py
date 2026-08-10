from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.commercial_terms_contract import (
    CommercialTermComponent, CommercialTermsError, RecognizeCommercialTermsCommand,
)
from core.domain.finance.commercial_terms_engine import EVENT_POLICY, TransactionalCommercialTermsEngine
from core.domain.finance.commercial_terms_repository import EXPECTED_SOURCE_KINDS
from core.domain.finance.commercial_terms_service import CommercialTermsService


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m52_commercial_terms_taxes_and_fees.json"
BASE = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)


def component(kind="discount", number=1, amount="10", profile=None, classification=None):
    defaults = {
        "discount": {"discount_reason": {"code": "seasonal"}},
        "complimentary": {"complimentary_reason": {"code": "guest_recovery"}, "complimentary_policy": {"code": "promotion"}},
        "customer_service_fee": {"revenue_nature": {"code": "service_fee"}},
        "output_tax": {"tax_jurisdiction": {"code": "CM"}, "tax_code": {"code": "VAT"}},
    }
    selected = defaults.get(kind, {}) if classification is None else classification
    return CommercialTermComponent(UUID(f"52000000-0000-0000-0001-{number:012d}"), number, kind, amount, selected, profile)


def command(components=None, gross="100", collectible=None):
    components = tuple(components or (component(),))
    reductions = sum((x.amount for x in components if x.component_type in {"discount", "complimentary"}), Decimal("0"))
    additions = sum((x.amount for x in components if x.component_type in {"customer_service_fee", "output_tax"}), Decimal("0"))
    collectible = Decimal(gross) - reductions + additions if collectible is None else collectible
    return RecognizeCommercialTermsCommand(1, 2, gross, collectible, "xaf", BASE, date(2026, 8, 10), 1, UUID(int=99), "m52.terms", "tests", components)


def test_contract_is_valid_and_schema_neutral():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["contract_code"] == "XBOS_M52_COMMERCIAL_TERMS_TAXES_AND_FEES"
    assert data["canonical_head"] == "m46_provider_financials_015"
    assert data["migration"] is False


def test_contract_covers_all_grouped_components():
    assert set(json.loads(CONTRACT.read_text())["component_types"]) == {"discount", "complimentary", "customer_service_fee", "output_tax"}


@pytest.mark.parametrize("kind,profile", [
    ("discount", "discount_contra_revenue"),
    ("customer_service_fee", "commercial_recognition"),
    ("output_tax", "output_tax_recognition"),
])
def test_fixed_component_profiles(kind, profile):
    assert component(kind).posting_profile_code == profile


@pytest.mark.parametrize("policy,profile", [
    ("contra_revenue", "complimentary_contra_revenue"),
    ("promotion", "complimentary_promotion"),
    ("service_recovery", "complimentary_service_recovery"),
])
def test_complimentary_policy_selects_profile(policy, profile):
    item = component("complimentary", classification={"complimentary_reason": {"code": "approved"}, "complimentary_policy": {"code": policy}})
    assert item.posting_profile_code == profile


@pytest.mark.parametrize("kind", ["discount", "complimentary", "customer_service_fee", "output_tax"])
def test_positive_component_amount_required(kind):
    with pytest.raises(CommercialTermsError, match="invalid amount"):
        component(kind, amount="0")


def test_provider_fee_cannot_impersonate_customer_fee():
    with pytest.raises(CommercialTermsError) as raised:
        component("provider_fee")
    assert raised.value.code == "provider_fee_authority"


def test_unknown_component_rejected():
    with pytest.raises(CommercialTermsError) as raised:
        component("mystery")
    assert raised.value.code == "unsupported_component_type"


@pytest.mark.parametrize("kind", ["discount", "complimentary", "customer_service_fee", "output_tax"])
def test_required_classification_enforced(kind):
    with pytest.raises(CommercialTermsError) as raised:
        component(kind, classification={})
    assert raised.value.code == "classification_required"


def test_profile_override_mismatch_rejected():
    with pytest.raises(CommercialTermsError) as raised:
        component("discount", profile="commercial_recognition")
    assert raised.value.code == "posting_profile_mismatch"


def test_invalid_complimentary_policy_rejected():
    with pytest.raises(CommercialTermsError) as raised:
        component("complimentary", classification={"complimentary_reason": {"code": "x"}, "complimentary_policy": {"code": "unknown"}})
    assert raised.value.code == "complimentary_policy_invalid"


def test_collectible_formula_and_summary():
    items = (component("discount", 1, "10"), component("complimentary", 2, "15"), component("customer_service_fee", 3, "5"), component("output_tax", 4, "18"))
    result = CommercialTermsService.summarize(command(items))
    assert result == result.__class__(Decimal("100"), Decimal("10"), Decimal("15"), Decimal("5"), Decimal("18"), Decimal("98"), "XAF")


def test_collectible_mismatch_rejected():
    with pytest.raises(CommercialTermsError) as raised:
        command(collectible="99")
    assert raised.value.code == "collectible_mismatch"


def test_allowance_capacity_rejected():
    with pytest.raises(CommercialTermsError) as raised:
        command((component("discount", 1, "60"), component("complimentary", 2, "50")), collectible="0")
    assert raised.value.code == "allowance_capacity_exceeded"


def test_fully_complimentary_zero_collectible_is_valid():
    assert command((component("complimentary", amount="100"),)).customer_collectible_amount == 0


def test_duplicate_component_id_rejected():
    item = component()
    with pytest.raises(CommercialTermsError) as raised:
        command((item, replace(item, source_record_id=2)))
    assert raised.value.code == "duplicate_component"


def test_duplicate_source_id_rejected():
    with pytest.raises(CommercialTermsError) as raised:
        command((component("discount", 1), component("output_tax", 1)))
    assert raised.value.code == "duplicate_component"


def test_timezone_required():
    with pytest.raises(CommercialTermsError) as raised:
        replace(command(), occurred_at=BASE.replace(tzinfo=None))
    assert raised.value.code == "timezone_required"


def test_event_and_source_policy_are_canonical():
    assert EVENT_POLICY["discount"][0] == "DISCOUNT_GRANTED"
    assert EVENT_POLICY["complimentary"][0] == "COMPLIMENTARY_GRANTED"
    assert EVENT_POLICY["customer_service_fee"][0] == "COMMERCIAL_REVENUE_RECOGNIZED"
    assert EVENT_POLICY["output_tax"][0] == "TAX_LIABILITY_RECOGNIZED"
    assert EXPECTED_SOURCE_KINDS["customer_service_fee"] == "commercial_transaction_line"


def test_event_builder_preserves_explanation_metadata():
    cmd = command()
    event = TransactionalCommercialTermsEngine._event(cmd, cmd.components[0])
    assert event.metadata["gross_sales_amount"] == "100"
    assert event.metadata["customer_collectible_amount"] == "90"
    assert event.idempotency_key == str(cmd.components[0].public_id)


def test_persistence_marker_declares_no_new_tables():
    source = (ROOT / "core/persistence/m52_commercial_terms.py").read_text(encoding="utf-8")
    assert 'SCHEMA_NEUTRAL = True' in source
    assert 'WRITES_NEW_TABLES = False' in source


def test_verifier_contains_fail_fast_acceptance_markers():
    source = (ROOT / "scripts/verify_m52_commercial_terms.py").read_text(encoding="utf-8")
    for marker in ("formula=PASS", "allowances=PASS", "fees=PASS", "tax=PASS", "tenant_scope=PASS", "atomic_rollback=PASS", "dropped=true"):
        assert marker in source
