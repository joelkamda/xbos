import json
import re
from decimal import Decimal
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
FINANCE_CONTRACT_ROOT = ROOT / "contracts" / "finance" / "v1"
EVENT_CATALOG_PATH = FINANCE_CONTRACT_ROOT / "financial_event_catalog.json"
ACCOUNT_ROLE_CATALOG_PATH = FINANCE_CONTRACT_ROOT / "account_role_catalog.json"
POSTING_SCENARIOS_PATH = FINANCE_CONTRACT_ROOT / "posting_scenarios.json"

CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

EXPECTED_SCENARIO_CODES = {
    "FULLY_PAID_SALE",
    "PARTIAL_PAYMENT_RECEIVABLE",
    "AR_REPAYMENT",
    "FULLY_COMPLIMENTARY_TRANSACTION",
    "OVERPAYMENT_CUSTOMER_CREDIT",
    "PARTIAL_REFUND",
    "OPERATIONAL_VALUE_TRANSFER",
    "XAFPAY_EXTERNAL_ORDER_PAYMENT",
    "PROVIDER_FEE_AND_RESERVE_ADJUSTMENT",
}


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


@pytest.fixture(scope="module")
def event_catalog() -> dict:
    return _load_json(EVENT_CATALOG_PATH)


@pytest.fixture(scope="module")
def account_role_catalog() -> dict:
    return _load_json(ACCOUNT_ROLE_CATALOG_PATH)


@pytest.fixture(scope="module")
def posting_contract() -> dict:
    return _load_json(POSTING_SCENARIOS_PATH)


@pytest.fixture(scope="module")
def events_by_code(event_catalog) -> dict:
    return {
        event["event_type_code"]: event
        for event in event_catalog["event_types"]
    }


@pytest.fixture(scope="module")
def scenarios_by_code(posting_contract) -> dict:
    return {
        scenario["scenario_code"]: scenario
        for scenario in posting_contract["scenarios"]
    }


def _profile(event_contract: dict, profile_code: str | None) -> dict | None:
    if profile_code is None:
        return None

    matches = [
        profile
        for profile in event_contract.get("posting_profiles", [])
        if profile["profile_code"] == profile_code
    ]
    assert len(matches) == 1, (
        event_contract["event_type_code"],
        profile_code,
        matches,
    )
    return matches[0]


def _event_codes(scenario: dict) -> list[str]:
    return [event["event_type_code"] for event in scenario["events"]]


def _ending_balances(scenario: dict) -> dict[str, Decimal]:
    balances = {
        account: Decimal(value)
        for account, value in scenario["opening_account_balances"].items()
    }
    bindings = scenario["account_role_bindings"]

    for event in scenario["events"]:
        for line in event["journal_lines"]:
            account = bindings[line["account_role"]]
            amount = Decimal(line["amount"])
            balances.setdefault(account, Decimal("0"))
            balances[account] += amount if line["side"] == "debit" else -amount

    return balances


def test_posting_contract_identity_and_exact_scenario_set(posting_contract):
    assert posting_contract["catalog_code"] == (
        "XBOS_CANONICAL_FINANCIAL_POSTING_SCENARIOS"
    )
    assert posting_contract["catalog_version"] == 1
    assert posting_contract["contract_revision"] == 1
    assert posting_contract["status"] == "approved"
    assert posting_contract["balance_sign_convention"] == (
        "debit_positive_credit_negative"
    )

    codes = [scenario["scenario_code"] for scenario in posting_contract["scenarios"]]
    assert len(codes) == len(set(codes))
    assert set(codes) == EXPECTED_SCENARIO_CODES
    assert all(CODE_PATTERN.fullmatch(code) for code in codes)


def test_account_role_catalog_is_exactly_the_event_catalog_vocabulary(
    account_role_catalog,
    event_catalog,
):
    assert account_role_catalog["catalog_code"] == "XBOS_CANONICAL_ACCOUNT_ROLES"
    assert account_role_catalog["catalog_version"] == 1
    assert account_role_catalog["contract_revision"] == 1
    assert account_role_catalog["status"] == "approved"

    roles = account_role_catalog["account_roles"]
    role_codes = [role["account_role"] for role in roles]
    assert len(role_codes) == len(set(role_codes))
    assert all(ROLE_PATTERN.fullmatch(role) for role in role_codes)

    roles_used_by_events = set()
    for event in event_catalog["event_types"]:
        for profile in event.get("posting_profiles", []):
            roles_used_by_events.update(profile.get("debit_account_roles") or [])
            roles_used_by_events.update(profile.get("credit_account_roles") or [])

    assert set(role_codes) == roles_used_by_events


def test_account_roles_have_governed_account_constraints(account_role_catalog):
    allowed_account_types = {"asset", "liability", "equity", "income", "expense", "contra"}
    allowed_normal_balances = {"debit", "credit"}
    allowed_link_policies = {"required", "optional", "forbidden"}

    for role in account_role_catalog["account_roles"]:
        assert role["display_name"].strip()
        assert role["description"].strip()
        assert role["allowed_account_types"]
        assert set(role["allowed_account_types"]) <= allowed_account_types
        assert role["allowed_normal_balances"]
        assert set(role["allowed_normal_balances"]) <= allowed_normal_balances
        assert role["operational_account_link"] in allowed_link_policies


def test_scenario_events_resolve_to_approved_event_contracts(
    posting_contract,
    events_by_code,
):
    for scenario in posting_contract["scenarios"]:
        assert scenario["currency_code"] == "XAF"
        sequences = [event["sequence"] for event in scenario["events"]]
        assert sequences == list(range(1, len(sequences) + 1))

        for event in scenario["events"]:
            contract = events_by_code[event["event_type_code"]]
            assert event["source_record_kind"] in contract["source_record_kinds"]
            assert event["economic_role"] in contract["allowed_economic_roles"]
            assert Decimal(event["amount"]) > 0

            profile = _profile(contract, event["posting_profile_code"])
            if contract["posting_eligible"]:
                assert profile is not None
            else:
                assert profile is None
                assert event["journal_lines"] == []


def test_template_profiles_match_their_declared_journal_roles(
    posting_contract,
    events_by_code,
):
    for scenario in posting_contract["scenarios"]:
        for event in scenario["events"]:
            profile = _profile(
                events_by_code[event["event_type_code"]],
                event["posting_profile_code"],
            )
            if profile is None or profile["mode"] != "template":
                continue

            debit_roles = [
                line["account_role"]
                for line in event["journal_lines"]
                if line["side"] == "debit"
            ]
            credit_roles = [
                line["account_role"]
                for line in event["journal_lines"]
                if line["side"] == "credit"
            ]
            assert debit_roles == profile["debit_account_roles"]
            assert credit_roles == profile["credit_account_roles"]


def test_inverse_postings_are_exact_inverses_of_the_referenced_event(
    posting_contract,
    events_by_code,
):
    inverse_count = 0

    for scenario in posting_contract["scenarios"]:
        events_by_sequence = {
            event["sequence"]: event for event in scenario["events"]
        }

        for event in scenario["events"]:
            profile = _profile(
                events_by_code[event["event_type_code"]],
                event["posting_profile_code"],
            )
            if profile is None or profile["mode"] != "inverse_original":
                continue

            inverse_count += 1
            original = events_by_sequence[event["reverses_sequence"]]
            assert Decimal(event["amount"]) <= Decimal(original["amount"])

            original_debits = {
                line["account_role"]
                for line in original["journal_lines"]
                if line["side"] == "debit"
            }
            original_credits = {
                line["account_role"]
                for line in original["journal_lines"]
                if line["side"] == "credit"
            }
            inverse_debits = {
                line["account_role"]
                for line in event["journal_lines"]
                if line["side"] == "debit"
            }
            inverse_credits = {
                line["account_role"]
                for line in event["journal_lines"]
                if line["side"] == "credit"
            }
            assert inverse_debits == original_credits
            assert inverse_credits == original_debits

    assert inverse_count == 1


def test_events_requiring_originals_reference_earlier_scenario_events(
    posting_contract,
    events_by_code,
):
    for scenario in posting_contract["scenarios"]:
        events_by_sequence = {
            event["sequence"]: event for event in scenario["events"]
        }
        for event in scenario["events"]:
            if not events_by_code[event["event_type_code"]]["requires_original_event"]:
                continue
            reversed_sequence = event.get("reverses_sequence")
            assert reversed_sequence in events_by_sequence
            assert reversed_sequence < event["sequence"]


def test_every_posting_event_is_individually_balanced(posting_contract):
    posting_event_count = 0

    for scenario in posting_contract["scenarios"]:
        for event in scenario["events"]:
            if not event["journal_lines"]:
                continue

            posting_event_count += 1
            debits = sum(
                Decimal(line["amount"])
                for line in event["journal_lines"]
                if line["side"] == "debit"
            )
            credits = sum(
                Decimal(line["amount"])
                for line in event["journal_lines"]
                if line["side"] == "credit"
            )
            assert debits == credits == Decimal(event["amount"])

    assert posting_event_count == 26


def test_every_journal_role_is_defined_and_bound_to_an_account(
    posting_contract,
    account_role_catalog,
):
    known_roles = {
        role["account_role"]
        for role in account_role_catalog["account_roles"]
    }

    for scenario in posting_contract["scenarios"]:
        bindings = scenario["account_role_bindings"]
        known_accounts = set(scenario["opening_account_balances"])
        assert set(bindings.values()) <= known_accounts

        for event in scenario["events"]:
            for line in event["journal_lines"]:
                assert line["side"] in {"debit", "credit"}
                assert line["account_role"] in known_roles
                assert line["account_role"] in bindings
                assert Decimal(line["amount"]) > 0


def test_all_scenarios_reach_their_exact_ending_balances(posting_contract):
    for scenario in posting_contract["scenarios"]:
        expected = {
            account: Decimal(value)
            for account, value in scenario[
                "expected_ending_account_balances"
            ].items()
        }
        assert _ending_balances(scenario) == expected


def test_full_and_partial_sale_workflow_gates(scenarios_by_code):
    full = scenarios_by_code["FULLY_PAID_SALE"]
    partial = scenarios_by_code["PARTIAL_PAYMENT_RECEIVABLE"]
    complimentary = scenarios_by_code["FULLY_COMPLIMENTARY_TRANSACTION"]

    assert full["expected_workflow"] == {
        "payment_condition": "satisfied",
        "commercial_confirmation": "confirmed",
        "fulfillment_request": "requested",
    }
    assert partial["expected_workflow"] == {
        "payment_condition": "not_satisfied",
        "commercial_confirmation": "not_confirmed",
        "fulfillment_request": "not_requested",
    }
    assert complimentary["expected_workflow"]["payment_condition"] == "satisfied"
    assert "PAYMENT_SETTLED" not in _event_codes(complimentary)


def test_ar_repayment_settles_then_allocates_without_revenue_duplication(
    scenarios_by_code,
):
    scenario = scenarios_by_code["AR_REPAYMENT"]
    assert _event_codes(scenario) == ["PAYMENT_SETTLED", "PAYMENT_ALLOCATED"]
    assert scenario["expected_ending_account_balances"]["accounts_receivable"] == "0"
    assert scenario["expected_ending_account_balances"]["cash_on_hand"] == "6000"


def test_overpayment_becomes_a_customer_credit_liability(scenarios_by_code):
    scenario = scenarios_by_code["OVERPAYMENT_CUSTOMER_CREDIT"]
    assert _event_codes(scenario)[-1] == "CUSTOMER_CREDIT_RECOGNIZED"
    assert scenario["expected_ending_account_balances"]["unapplied_receipts"] == "0"
    assert scenario["expected_ending_account_balances"]["customer_credit_liability"] == "-2000"


def test_partial_refund_separates_return_deallocation_and_cash_out(
    scenarios_by_code,
):
    scenario = scenarios_by_code["PARTIAL_REFUND"]
    assert _event_codes(scenario)[-3:] == [
        "COMMERCIAL_RETURN_RECOGNIZED",
        "PAYMENT_ALLOCATION_REVERSED",
        "REFUND_SETTLED",
    ]
    assert scenario["expected_ending_account_balances"]["cash_on_hand"] == "6000"
    assert scenario["expected_ending_account_balances"]["sales_returns"] == "4000"
    assert scenario["expected_ending_account_balances"]["accounts_receivable"] == "0"


def test_value_transfer_preserves_combined_operational_value(scenarios_by_code):
    scenario = scenarios_by_code["OPERATIONAL_VALUE_TRANSFER"]
    opening = sum(Decimal(value) for value in scenario["opening_account_balances"].values())
    ending = sum(
        Decimal(value)
        for value in scenario["expected_ending_account_balances"].values()
    )
    assert _event_codes(scenario) == ["VALUE_TRANSFERRED"]
    assert opening == ending == Decimal("20000")


def test_xafpay_is_an_orchestrator_not_a_hard_coded_payment_rail(
    scenarios_by_code,
):
    scenario = scenarios_by_code["XAFPAY_EXTERNAL_ORDER_PAYMENT"]
    context = scenario["integration_context"]

    assert context["payment_orchestrator"] == "xafpay"
    assert context["payment_rail"] == "mtn_mobile_money"
    assert context["payment_method"] == "mobile_money"
    assert len(
        {
            context["payment_orchestrator"],
            context["payment_rail"],
            context["payment_method"],
        }
    ) == 3
    assert context["provider_account_public_id"]
    assert context["operational_account_public_id"]


def test_xafpay_external_order_requires_canonical_final_settlement_before_fulfillment(
    scenarios_by_code,
):
    scenario = scenarios_by_code["XAFPAY_EXTERNAL_ORDER_PAYMENT"]
    context = scenario["integration_context"]

    assert context["provider_evidence_authenticated"] is True
    assert context["finality_status"] == "final"
    assert context["raw_provider_success_used_as_confirmation_trigger"] is False
    assert context["fulfillment_delivery"] == "transactional_outbox"
    assert _event_codes(scenario) == [
        "COMMERCIAL_REVENUE_RECOGNIZED",
        "PAYMENT_SETTLED",
        "PAYMENT_ALLOCATED",
    ]
    assert scenario["expected_workflow"] == {
        "payment_condition": "satisfied",
        "commercial_confirmation": "confirmed",
        "fulfillment_request": "requested",
    }


def test_provider_fee_and_reserve_adjustments_do_not_restate_customer_payment(
    scenarios_by_code,
):
    scenario = scenarios_by_code["PROVIDER_FEE_AND_RESERVE_ADJUSTMENT"]
    assert _event_codes(scenario) == [
        "PROVIDER_FEE_RECOGNIZED",
        "PROVIDER_SETTLEMENT_ADJUSTED",
    ]
    assert "PAYMENT_SETTLED" not in _event_codes(scenario)
    assert scenario["expected_ending_account_balances"] == {
        "xafpay_clearing": "14200",
        "provider_fee_expense": "300",
        "provider_reserve": "500",
    }
