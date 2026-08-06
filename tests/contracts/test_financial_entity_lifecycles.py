import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
FINANCE_ROOT = ROOT / "contracts" / "finance" / "v1"
ENTITY_PATH = FINANCE_ROOT / "entity_contracts.json"
LIFECYCLE_PATH = FINANCE_ROOT / "lifecycle_contracts.json"
EVENT_PATH = FINANCE_ROOT / "financial_event_catalog.json"

LOWER_CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
UPPER_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")

EXPECTED_ENTITIES = {
    "commercial_transaction",
    "commercial_transaction_line",
    "financial_obligation",
    "payment_intent",
    "payment_attempt",
    "payment_provider_account",
    "provider_callback_event",
    "payment_settlement",
    "operational_financial_account",
    "value_source",
    "payment_allocation",
    "allocation_reversal",
    "payment_refund",
    "financial_event",
    "journal_entry",
    "journal_line",
    "reconciliation_series",
    "reconciliation_window",
    "reconciliation_line",
    "outbox_message",
}

EXPECTED_MACHINES = {
    "commercial_transaction",
    "financial_obligation",
    "payment_intent",
    "payment_attempt",
    "payment_settlement",
    "payment_allocation",
    "payment_refund",
    "journal_entry",
    "reconciliation_window",
    "outbox_message",
}

ENTITY_FIELDS = {
    "entity_code",
    "display_name",
    "bounded_context",
    "aggregate_root",
    "authority",
    "mutation_policy",
    "required_fields",
    "money_fields",
    "state_machine",
    "relationships",
    "idempotency_identity",
    "invariants",
}

MACHINE_FIELDS = {
    "machine_code",
    "state_field",
    "states",
    "transitions",
    "invariants",
}

TRANSITION_FIELDS = {"command", "from", "to", "requires", "emits"}


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


@pytest.fixture(scope="module")
def entities() -> dict:
    return _load(ENTITY_PATH)


@pytest.fixture(scope="module")
def lifecycles() -> dict:
    return _load(LIFECYCLE_PATH)


@pytest.fixture(scope="module")
def events() -> dict:
    return _load(EVENT_PATH)


@pytest.fixture(scope="module")
def entities_by_code(entities) -> dict:
    return {item["entity_code"]: item for item in entities["entities"]}


@pytest.fixture(scope="module")
def machines_by_code(lifecycles) -> dict:
    return {
        item["machine_code"]: item
        for item in lifecycles["state_machines"]
    }


def _transition(machine: dict, command: str) -> dict:
    matches = [
        item for item in machine["transitions"]
        if item["command"] == command
    ]
    assert len(matches) == 1, (machine["machine_code"], command, matches)
    return matches[0]


def test_contract_identity_and_exact_approved_sets(entities, lifecycles):
    assert entities["catalog_code"] == "XBOS_CANONICAL_FINANCIAL_ENTITIES"
    assert lifecycles["catalog_code"] == "XBOS_CANONICAL_FINANCIAL_LIFECYCLES"
    for contract in (entities, lifecycles):
        assert contract["catalog_version"] == 1
        assert contract["contract_revision"] == 1
        assert contract["status"] == "approved"
        assert contract["approved_at"] == "2026-08-06T00:00:00Z"

    assert {item["entity_code"] for item in entities["entities"]} == (
        EXPECTED_ENTITIES
    )
    assert {
        item["machine_code"] for item in lifecycles["state_machines"]
    } == EXPECTED_MACHINES


def test_entity_codes_are_unique_and_canonical(entities):
    codes = [item["entity_code"] for item in entities["entities"]]
    assert len(codes) == len(set(codes))
    assert all(LOWER_CODE.fullmatch(code) for code in codes)


def test_every_entity_has_the_complete_contract_shape(entities):
    for entity in entities["entities"]:
        assert set(entity) == ENTITY_FIELDS, entity["entity_code"]
        assert entity["display_name"].strip()
        assert entity["authority"].strip()
        assert isinstance(entity["aggregate_root"], bool)
        assert entity["required_fields"]
        assert entity["idempotency_identity"]
        assert entity["invariants"]


def test_bounded_contexts_are_governed(entities):
    allowed = {
        "commercial",
        "obligation",
        "payment_orchestration",
        "settled_value",
        "allocation",
        "refund",
        "financial_event",
        "journal",
        "reconciliation",
        "integration",
    }
    assert {item["bounded_context"] for item in entities["entities"]} <= allowed


def test_money_fields_are_explicit_and_currency_scoped(entities):
    for entity in entities["entities"]:
        required = set(entity["required_fields"])
        assert set(entity["money_fields"]) <= required
        if entity["money_fields"]:
            assert "currency_code" in required
    assert entities["common_context"]["money_representation"] == (
        "decimal_string_plus_iso_4217_currency"
    )


def test_idempotency_identities_are_required_and_tenant_scoped(entities):
    for entity in entities["entities"]:
        identity = entity["idempotency_identity"]
        assert len(identity) == len(set(identity))
        assert "tenant_id" in identity
        assert set(identity) <= set(entity["required_fields"])


def test_relationship_targets_are_canonical_and_tenant_safe(entities):
    codes = {item["entity_code"] for item in entities["entities"]}
    cardinalities = {
        "one_to_one",
        "many_to_one",
        "one_to_many",
        "many_to_many",
    }
    for entity in entities["entities"]:
        for relationship in entity["relationships"]:
            assert relationship["target"] in codes
            assert relationship["cardinality"] in cardinalities
            assert relationship["field"] in entity["required_fields"] or not (
                relationship["required"]
            )
            assert relationship["tenant_match"] is True


def test_mutation_policies_are_governed_and_committed_facts_are_append_only(
    entities,
    entities_by_code,
):
    policies = set(entities["mutation_policies"])
    assert all(item["mutation_policy"] in policies for item in entities["entities"])
    for code in {
        "provider_callback_event",
        "value_source",
        "payment_allocation",
        "allocation_reversal",
        "financial_event",
    }:
        assert entities_by_code[code]["mutation_policy"] == "append_only"


def test_entity_state_fields_resolve_to_one_machine(
    entities,
    machines_by_code,
):
    for entity in entities["entities"]:
        machine_code = entity["state_machine"]
        if machine_code is None:
            continue
        assert machine_code in machines_by_code
        state_field = machines_by_code[machine_code]["state_field"]
        if state_field is not None:
            assert state_field in entity["required_fields"]


def test_lifecycle_catalog_enforces_command_boundary(lifecycles):
    transition = lifecycles["transition_contract"]
    assert transition["arbitrary_status_assignment_allowed"] is False
    assert transition["cross_tenant_transition_allowed"] is False
    assert transition["idempotency_replay"] == (
        "return_identical_result_or_reject_conflict"
    )
    assert "expected_version" in transition["required_command_context"]
    assert transition["execution_order"][-1] == "commit"


def test_every_machine_has_the_complete_contract_shape(lifecycles):
    for machine in lifecycles["state_machines"]:
        assert set(machine) == MACHINE_FIELDS
        assert LOWER_CODE.fullmatch(machine["machine_code"])
        assert machine["states"]
        assert machine["transitions"]
        assert machine["invariants"]


def test_state_and_transition_graphs_are_closed(lifecycles):
    for machine in lifecycles["state_machines"]:
        states = [state["code"] for state in machine["states"]]
        assert len(states) == len(set(states))
        assert all(LOWER_CODE.fullmatch(state) for state in states)
        for transition in machine["transitions"]:
            assert set(transition) == TRANSITION_FIELDS
            assert transition["from"] in states
            assert transition["to"] in states
            assert transition["requires"]
            assert transition["emits"]


def test_transition_commands_are_unique_within_each_machine(lifecycles):
    for machine in lifecycles["state_machines"]:
        commands = [item["command"] for item in machine["transitions"]]
        assert len(commands) == len(set(commands))
        assert all(LOWER_CODE.fullmatch(command) for command in commands)


def test_terminal_states_have_no_outbound_transitions(lifecycles):
    for machine in lifecycles["state_machines"]:
        terminal = {
            state["code"] for state in machine["states"] if state["terminal"]
        }
        outbound = {item["from"] for item in machine["transitions"]}
        assert terminal.isdisjoint(outbound), machine["machine_code"]


def test_commercial_lifecycle_never_overloads_payment(
    machines_by_code,
    entities_by_code,
):
    machine = machines_by_code["commercial_transaction"]
    states = {item["code"] for item in machine["states"]}
    assert states == {"draft", "confirmed", "cancelled", "reversed"}
    assert "paid" not in states
    assert "payment_is_not_a_commercial_state" in (
        entities_by_code["commercial_transaction"]["invariants"]
    )


def test_obligation_remeasurement_requires_compensating_evidence(
    machines_by_code,
):
    machine = machines_by_code["financial_obligation"]
    to_partial = _transition(machine, "remeasure_satisfied_to_partial")
    to_open = _transition(machine, "remeasure_satisfied_to_open")
    assert "explicit_allocation_or_allowance_reversal" in to_partial["requires"]
    assert "explicit_full_satisfaction_reversal" in to_open["requires"]
    assert "balance_is_derived" in machine["invariants"]


def test_payment_intent_failure_and_success_semantics_are_explicit(
    machines_by_code,
):
    machine = machines_by_code["payment_intent"]
    retry = _transition(machine, "return_intent_to_pending")
    failure = _transition(machine, "fail_processing_intent")
    success = _transition(machine, "succeed_processing_intent")
    assert "retry_allowed" in retry["requires"]
    assert "no_retry_remains" in failure["requires"]
    assert "confirmed_settlement_target_reached" in success["requires"]
    assert "success_is_collection_target_not_allocation" in machine["invariants"]


def test_attempt_success_preserves_provider_finality_boundary(
    machines_by_code,
    entities_by_code,
):
    attempt = machines_by_code["payment_attempt"]
    immediate = _transition(attempt, "succeed_immediate_attempt")
    provider = _transition(attempt, "succeed_processing_attempt")
    assert "immediate_channel_confirmation" in immediate["requires"]
    assert "provider_or_channel_success_evidence" in provider["requires"]
    assert "succeeded_is_not_universally_settled" in attempt["invariants"]
    relationships = entities_by_code["payment_attempt"]["relationships"]
    provider_link = next(
        item for item in relationships if item["field"] == "provider_account_id"
    )
    assert provider_link["target"] == "payment_provider_account"


def test_settlement_and_allocation_reversals_are_append_only(
    machines_by_code,
    entities_by_code,
):
    settlement = machines_by_code["payment_settlement"]
    confirm = _transition(settlement, "confirm_pending_settlement")
    assert "authenticated_evidence_when_external" in confirm["requires"]
    assert confirm["emits"] == ["PAYMENT_SETTLED"]
    assert "original_settlement_evidence_is_immutable" in settlement["invariants"]

    allocation = machines_by_code["payment_allocation"]
    assert allocation["state_field"] is None
    assert "condition_is_derived" in allocation["invariants"]
    assert entities_by_code["allocation_reversal"]["mutation_policy"] == (
        "append_only"
    )


def test_refund_success_requires_cash_out_and_deallocation_evidence(
    machines_by_code,
):
    machine = machines_by_code["payment_refund"]
    success = _transition(machine, "succeed_refund")
    assert set(success["requires"]) == {
        "confirmed_outgoing_settlement",
        "refund_applications_recorded",
        "allocated_value_reversed_when_applicable",
    }
    assert success["emits"] == ["REFUND_SETTLED"]
    assert "success_has_cash_out_and_deallocation_evidence" in (
        machine["invariants"]
    )


def test_posted_journal_is_balanced_immutable_and_reversed_separately(
    machines_by_code,
    entities_by_code,
):
    machine = machines_by_code["journal_entry"]
    posting = _transition(machine, "approve_and_post_journal")
    reversing = _transition(machine, "reverse_posted_journal")
    assert "balanced_per_currency" in posting["requires"]
    assert "separate_balanced_reversing_entry" in reversing["requires"]
    assert entities_by_code["journal_line"]["mutation_policy"] == (
        "immutable_after_posting"
    )


def test_reconciliation_keeps_workflow_readiness_variance_and_provenance_separate(
    lifecycles,
    machines_by_code,
):
    derived = lifecycles["derived_conditions"]
    assert derived["reconciliation_readiness"]["values"] == [
        "blocked",
        "ready_to_close",
    ]
    assert derived["reconciliation_variance"]["formula"] == (
        "actual_closing - expected_closing"
    )
    assert set(derived["reconciliation_actual_provenance"]["values"]) == {
        "system_prefilled",
        "operator_confirmed",
        "external_confirmed",
    }
    close = _transition(
        machines_by_code["reconciliation_window"],
        "close_reconciliation_window",
    )
    assert "readiness_is_ready_to_close" in close["requires"]
    assert "actual_is_operator_or_external_confirmed" in close["requires"]


def test_reconciliation_continuity_and_correction_rules_are_executable(
    machines_by_code,
    entities_by_code,
):
    machine = machines_by_code["reconciliation_window"]
    assert {
        "middle_window_cannot_be_skipped",
        "previous_close_comes_from_same_series",
        "next_opening_equals_previous_actual",
        "correction_does_not_overwrite_later_actuals",
    } <= set(machine["invariants"])
    line_invariants = set(
        entities_by_code["reconciliation_line"]["invariants"]
    )
    assert "expected_equals_opening_plus_inflows_minus_outflows_plus_adjustments" in (
        line_invariants
    )
    assert "variance_equals_actual_minus_expected" in line_invariants


def test_derived_conditions_are_not_lifecycle_states(lifecycles):
    for condition in lifecycles["derived_conditions"].values():
        assert condition["persisted_as_lifecycle_state"] is False
        assert condition["values"]
    assert lifecycles["derived_conditions"]["payment_condition"]["values"] == [
        "unpaid",
        "partially_paid",
        "paid",
        "overpaid",
        "partially_refunded",
        "refunded",
    ]


def test_cross_machine_rules_cover_the_required_neutral_boundaries(lifecycles):
    codes = {item["rule_code"] for item in lifecycles["cross_machine_rules"]}
    assert codes == {
        "provider_callback_is_evidence_not_financial_event",
        "attempt_success_not_universal_settlement",
        "settlement_precedes_allocation",
        "payment_condition_is_derived",
        "refund_is_multi_record_workflow",
        "financial_event_is_recorded_once",
        "journal_is_projection_of_events",
        "reconciliation_does_not_rewrite_finance",
        "fulfillment_trigger_is_policy_governed",
        "tenant_scope_is_end_to_end",
    }
    assert all(item["assertion"].strip() for item in lifecycles["cross_machine_rules"])


def test_canonical_financial_emissions_resolve_to_event_catalog(
    lifecycles,
    events,
):
    approved_events = {
        item["event_type_code"] for item in events["event_types"]
    }
    emitted_financial = set()
    for machine in lifecycles["state_machines"]:
        for transition in machine["transitions"]:
            emitted_financial.update(
                code for code in transition["emits"]
                if UPPER_CODE.fullmatch(code)
            )
    assert emitted_financial == {
        "PAYMENT_SETTLED",
        "PAYMENT_SETTLEMENT_REVERSED",
        "PAYMENT_ALLOCATION_REVERSED",
        "REFUND_SETTLED",
    }
    assert emitted_financial <= approved_events
