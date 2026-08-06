import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = (
    ROOT / "contracts" / "finance" / "v1" / "financial_event_catalog.json"
)

EXPECTED_EVENT_CODES = {
    "COMMERCIAL_REVENUE_RECOGNIZED",
    "TAX_LIABILITY_RECOGNIZED",
    "DISCOUNT_GRANTED",
    "COMPLIMENTARY_GRANTED",
    "TIP_RECOGNIZED",
    "COMMERCIAL_RETURN_RECOGNIZED",
    "COST_OF_FULFILLMENT_RECOGNIZED",
    "EXPENSE_RECOGNIZED",
    "OBLIGATION_OPENED",
    "OBLIGATION_WRITTEN_OFF",
    "PAYMENT_SETTLED",
    "PAYMENT_SETTLEMENT_REVERSED",
    "PAYMENT_ALLOCATED",
    "PAYMENT_ALLOCATION_REVERSED",
    "CUSTOMER_CREDIT_RECOGNIZED",
    "REFUND_SETTLED",
    "VALUE_TRANSFERRED",
    "PROVIDER_FEE_RECOGNIZED",
    "PROVIDER_SETTLEMENT_ADJUSTED",
    "FINANCIAL_FACT_REVERSED",
}

EVENT_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

REQUIRED_EVENT_FIELDS = {
    "event_type_code",
    "event_version",
    "display_name",
    "definition",
    "amount_policy",
    "default_economic_role",
    "allowed_economic_roles",
    "posting_eligible",
    "requires_original_event",
    "source_record_kinds",
    "required_classification_roles",
    "operational_account_policy",
    "reconciliation_policy",
    "posting_profiles",
}

REVERSAL_EVENT_CODES = {
    "COMMERCIAL_RETURN_RECOGNIZED",
    "PAYMENT_SETTLEMENT_REVERSED",
    "PAYMENT_ALLOCATION_REVERSED",
    "FINANCIAL_FACT_REVERSED",
}


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def events(catalog):
    return catalog["event_types"]


def test_catalog_is_approved_version_one(catalog):
    assert catalog["catalog_code"] == "XBOS_CANONICAL_FINANCIAL_EVENTS"
    assert catalog["catalog_version"] == 1
    assert catalog["contract_revision"] == 2
    assert catalog["supersedes_contract_revision"] == 1
    assert catalog["status"] == "approved"
    assert catalog["approved_at"] == "2026-08-05T00:00:00Z"
    assert catalog["last_reviewed_at"] == "2026-08-06T00:00:00Z"


def test_universal_event_envelope_is_explicit(catalog):
    envelope = catalog["event_envelope_contract"]

    assert set(envelope["required_fields"]) == {
        "public_id",
        "tenant_id",
        "organization_unit_id",
        "event_type_code",
        "event_version",
        "amount",
        "currency_code",
        "economic_role",
        "source_record_id",
        "occurred_at",
        "recorded_at",
        "business_date",
        "calendar_policy_version",
        "idempotency_scope",
        "idempotency_key",
        "correlation_id",
        "classification_snapshot",
        "posting_context",
        "metadata",
    }
    assert envelope["actor_rule"] == {
        "at_least_one_of": ["actor_user_id", "actor_service"]
    }
    assert envelope["idempotency_identity"] == [
        "tenant_id",
        "idempotency_scope",
        "idempotency_key",
    ]
    assert envelope["immutable"] is True
    assert envelope["replay_policy"] == (
        "return_identical_event_or_reject_conflict"
    )


def test_external_settlement_keeps_rail_orchestrator_and_accounts_distinct(
    catalog,
):
    policy = catalog["external_settlement_policy"]

    assert policy["provider_callback_is_financial_event"] is False
    assert policy["payment_attempt_success_is_settlement"] is False
    assert policy["requires_authenticated_provider_evidence"] is True
    assert policy["requires_verified_finality_before_payment_settled"] is True
    assert policy["orchestrator_is_distinct_from_payment_rail"] is True
    assert policy["provider_account_is_distinct_from_operational_account"] is True
    assert policy["required_source_record_kind"] == "payment_settlement"
    assert set(policy["required_external_source_fields"]) == {
        "payment_method",
        "payment_rail",
        "orchestrator",
        "provider_account_public_id",
        "operational_account_public_id",
        "gateway_intent_reference",
        "provider_event_reference",
        "finality_status",
        "evidence_hash",
    }
    assert set(policy["optional_external_source_fields"]) == {
        "underlying_provider",
        "merchant_reference",
        "customer_reference",
    }


def test_payment_success_cannot_bypass_confirmation_and_fulfillment_policy(
    catalog,
):
    boundary = catalog["workflow_boundary"]

    assert boundary[
        "raw_provider_success_may_confirm_commercial_transaction"
    ] is False
    assert boundary["confirmation_authority"] == (
        "configured_confirmation_policy"
    )
    assert boundary["payment_required_path"] == [
        "authenticated_provider_evidence",
        "verified_payment_settlement",
        "payment_allocation",
        "payment_condition_satisfied",
    ]
    assert "zero_value_complimentary" in boundary[
        "allowed_non_payment_confirmation_paths"
    ]
    assert boundary["fulfillment_trigger"] == (
        "commercial_transaction_confirmed"
    )
    assert boundary["fulfillment_delivery"] == "transactional_outbox"
    assert set(boundary["workflow_events_not_financial"]) == {
        "PAYMENT_CONDITION_SATISFIED",
        "COMMERCIAL_TRANSACTION_CONFIRMED",
        "FULFILLMENT_REQUESTED",
        "CUSTOMER_NOTIFICATION_REQUESTED",
    }


def test_catalog_contains_exactly_the_approved_event_types(events):
    actual_codes = {event["event_type_code"] for event in events}

    assert len(events) == len(EXPECTED_EVENT_CODES)
    assert actual_codes == EXPECTED_EVENT_CODES


def test_event_identities_are_unique_and_versioned(events):
    identities = [
        (event["event_type_code"], event["event_version"])
        for event in events
    ]

    assert len(identities) == len(set(identities))
    assert all(version == 1 for _, version in identities)
    assert all(EVENT_CODE_PATTERN.fullmatch(code) for code, _ in identities)


def test_every_event_has_the_complete_contract_shape(events):
    for event in events:
        assert set(event) == REQUIRED_EVENT_FIELDS, event["event_type_code"]
        assert event["display_name"].strip()
        assert event["definition"].strip().endswith(".")
        assert isinstance(event["posting_eligible"], bool)
        assert isinstance(event["requires_original_event"], bool)
        assert isinstance(event["allowed_economic_roles"], list)
        assert event["allowed_economic_roles"]
        assert isinstance(event["source_record_kinds"], list)
        assert event["source_record_kinds"]
        assert isinstance(event["required_classification_roles"], list)
        assert isinstance(event["operational_account_policy"], dict)
        assert isinstance(event["reconciliation_policy"], dict)
        assert isinstance(event["posting_profiles"], list)


def test_amount_and_economic_role_vocabulary_is_governed(catalog, events):
    amount_policies = set(catalog["amount_policies"])
    economic_roles = set(catalog["economic_roles"])

    for event in events:
        assert event["amount_policy"] in amount_policies
        assert event["default_economic_role"] in event["allowed_economic_roles"]
        assert set(event["allowed_economic_roles"]) <= economic_roles


def test_classification_and_account_roles_use_canonical_names(events):
    for event in events:
        classifications = event["required_classification_roles"]
        assert len(classifications) == len(set(classifications))
        assert all(ROLE_PATTERN.fullmatch(role) for role in classifications)

        for profile in event["posting_profiles"]:
            for field in ("debit_account_roles", "credit_account_roles"):
                roles = profile.get(field, [])
                assert len(roles) == len(set(roles))
                assert all(ROLE_PATTERN.fullmatch(role) for role in roles)


def test_every_event_restricts_its_authoritative_source_record_kinds(events):
    for event in events:
        source_kinds = event["source_record_kinds"]
        assert len(source_kinds) == len(set(source_kinds))
        assert all(ROLE_PATTERN.fullmatch(kind) for kind in source_kinds)

    payment_settled = next(
        event
        for event in events
        if event["event_type_code"] == "PAYMENT_SETTLED"
    )
    assert payment_settled["source_record_kinds"] == ["payment_settlement"]


def test_reconciliation_policy_is_executable(catalog, events):
    allowed_effects = set(catalog["reconciliation_effects"])
    allowed_modes = {
        "fixed",
        "by_economic_role",
        "classification_dependent",
        "inverse_original",
    }

    for event in events:
        policy = event["reconciliation_policy"]
        mode = policy["mode"]
        assert mode in allowed_modes

        if mode == "fixed":
            assert set(policy) == {"mode", "effect"}
            assert policy["effect"] in allowed_effects
        elif mode == "by_economic_role":
            assert set(policy) == {"mode", "mappings"}
            assert set(policy["mappings"]) == set(
                event["allowed_economic_roles"]
            )
            assert set(policy["mappings"].values()) <= allowed_effects
        elif mode == "classification_dependent":
            assert set(policy) == {"mode", "classification_role"}
            assert policy["classification_role"] in event[
                "required_classification_roles"
            ]
        else:
            assert set(policy) == {"mode"}
            assert event["requires_original_event"] is True


def test_operational_account_policy_is_explicit(events):
    allowed_requirements = {"required", "forbidden", "conditional"}
    allowed_modes = {
        "none",
        "fixed",
        "by_economic_role",
        "classification_dependent",
        "inverse_original",
    }

    for event in events:
        policy = event["operational_account_policy"]
        mode = policy["mode"]
        assert mode in allowed_modes

        if mode == "none":
            assert set(policy) == {"mode"}
        elif mode == "fixed":
            assert policy["source"] in allowed_requirements
            assert policy["target"] in allowed_requirements
        elif mode == "by_economic_role":
            assert set(policy["mappings"]) == set(
                event["allowed_economic_roles"]
            )
            for requirements in policy["mappings"].values():
                assert requirements["source"] in allowed_requirements
                assert requirements["target"] in allowed_requirements
        elif mode == "classification_dependent":
            assert policy["at_least_one_of_source_or_target"] is True
        else:
            assert set(policy) == {"mode"}
            assert event["requires_original_event"] is True


def test_only_control_event_is_non_posting(events):
    non_posting = {
        event["event_type_code"]
        for event in events
        if not event["posting_eligible"]
    }

    assert non_posting == {"OBLIGATION_OPENED"}

    for event in events:
        if event["posting_eligible"]:
            assert event["posting_profiles"], event["event_type_code"]
        else:
            assert event["posting_profiles"] == []


def test_posting_profiles_are_unique_balanced_templates_or_inverses(events):
    allowed_modes = {"template", "inverse_original"}

    for event in events:
        profile_codes = [
            profile["profile_code"] for profile in event["posting_profiles"]
        ]
        assert len(profile_codes) == len(set(profile_codes))

        for profile in event["posting_profiles"]:
            assert ROLE_PATTERN.fullmatch(profile["profile_code"])
            assert profile["condition"].strip()
            assert profile["mode"] in allowed_modes

            if profile["mode"] == "template":
                debits = profile["debit_account_roles"]
                credits = profile["credit_account_roles"]
                assert debits
                assert credits
                assert set(debits).isdisjoint(credits)
            else:
                assert set(profile) == {
                    "profile_code",
                    "condition",
                    "mode",
                }
                assert event["requires_original_event"] is True


def test_reversal_types_require_original_events(events):
    actual = {
        event["event_type_code"]
        for event in events
        if event["requires_original_event"]
    }

    assert actual == REVERSAL_EVENT_CODES


def test_payment_settlement_direction_controls_accounts_and_reconciliation(
    events,
):
    payment_settled = next(
        event
        for event in events
        if event["event_type_code"] == "PAYMENT_SETTLED"
    )

    assert payment_settled["operational_account_policy"]["mappings"] == {
        "settlement_in": {"source": "forbidden", "target": "required"},
        "settlement_out": {"source": "required", "target": "forbidden"},
    }
    assert payment_settled["reconciliation_policy"]["mappings"] == {
        "settlement_in": "inflow",
        "settlement_out": "outflow",
    }


def test_value_transfer_requires_distinct_source_and_target(events):
    transfer = next(
        event
        for event in events
        if event["event_type_code"] == "VALUE_TRANSFERRED"
    )
    account_policy = transfer["operational_account_policy"]

    assert account_policy["source"] == "required"
    assert account_policy["target"] == "required"
    assert account_policy["different_accounts"] is True
    assert transfer["reconciliation_policy"] == {
        "mode": "fixed",
        "effect": "movement",
    }


def test_obligation_opened_cannot_double_post_the_economic_fact(events):
    obligation_opened = next(
        event
        for event in events
        if event["event_type_code"] == "OBLIGATION_OPENED"
    )

    assert obligation_opened["posting_eligible"] is False
    assert obligation_opened["posting_profiles"] == []
    assert obligation_opened["reconciliation_policy"] == {
        "mode": "fixed",
        "effect": "control_increase",
    }
