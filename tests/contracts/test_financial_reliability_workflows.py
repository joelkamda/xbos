import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
FINANCE_ROOT = ROOT / "contracts" / "finance" / "v1"
RELIABILITY_PATH = FINANCE_ROOT / "reliability_contracts.json"
WORKFLOW_PATH = FINANCE_ROOT / "workflow_contracts.json"
ENTITY_PATH = FINANCE_ROOT / "entity_contracts.json"
LIFECYCLE_PATH = FINANCE_ROOT / "lifecycle_contracts.json"
EVENT_PATH = FINANCE_ROOT / "financial_event_catalog.json"

LOWER_CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
UPPER_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")

EXPECTED_OPERATIONS = {
    "create_payment_intent",
    "process_provider_callback",
    "confirm_payment_settlement",
    "create_payment_allocation",
    "reverse_payment_allocation",
    "succeed_payment_refund",
    "close_reconciliation_window",
}

EXPECTED_WORKFLOW_EVENTS = {
    "PROVIDER_CALLBACK_AUTHENTICATED",
    "PROVIDER_CALLBACK_REJECTED",
    "PAYMENT_ACTION_REQUIRED",
    "PAYMENT_SETTLEMENT_VERIFIED",
    "PAYMENT_CONDITION_SATISFIED",
    "COMMERCIAL_TRANSACTION_CONFIRMED",
    "FULFILLMENT_REQUESTED",
    "FULFILLMENT_ACCEPTED",
    "FULFILLMENT_COMPLETED",
    "CUSTOMER_NOTIFICATION_REQUESTED",
}

EXPECTED_POLICIES = {
    "payment_required",
    "credit_allowed",
    "complimentary_zero_value",
    "deposit_threshold",
    "approval_only",
}

EXPECTED_FLOWS = {
    "external_payment_required_order",
    "immediate_cash_payment_required_order",
    "credit_allowed_order",
    "fully_complimentary_order",
    "duplicate_provider_callback",
    "offline_command_replay",
}


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


@pytest.fixture(scope="module")
def reliability() -> dict:
    return _load(RELIABILITY_PATH)


@pytest.fixture(scope="module")
def workflows() -> dict:
    return _load(WORKFLOW_PATH)


@pytest.fixture(scope="module")
def entities() -> dict:
    return _load(ENTITY_PATH)


@pytest.fixture(scope="module")
def lifecycles() -> dict:
    return _load(LIFECYCLE_PATH)


@pytest.fixture(scope="module")
def events() -> dict:
    return _load(EVENT_PATH)


def _by_code(items: list[dict], field: str) -> dict:
    return {item[field]: item for item in items}


def _flow(workflows: dict, code: str) -> dict:
    return _by_code(workflows["flows"], "flow_code")[code]


def _operation(reliability: dict, code: str) -> dict:
    return _by_code(
        reliability["concurrency_contract"]["operations"],
        "operation_code",
    )[code]


def test_contract_identities_are_approved_v1(reliability, workflows):
    assert reliability["catalog_code"] == "XBOS_FINANCIAL_EXECUTION_RELIABILITY"
    assert workflows["catalog_code"] == "XBOS_PAYMENT_TO_FULFILLMENT_WORKFLOWS"
    for contract in (reliability, workflows):
        assert contract["catalog_version"] == 1
        assert contract["contract_revision"] == 1
        assert contract["status"] == "approved"
        assert contract["approved_at"] == "2026-08-06T00:00:00Z"


def test_failure_vocabulary_is_unique_and_canonical(reliability):
    failures = reliability["failure_vocabulary"]
    assert len(failures) == len(set(failures))
    assert all(LOWER_CODE.fullmatch(code) for code in failures)
    assert {
        "idempotent_replay",
        "idempotency_conflict",
        "concurrent_modification",
        "authentication_failed",
        "quarantined",
    } <= set(failures)


def test_idempotency_identity_is_tenant_scoped(reliability):
    contract = reliability["idempotency_contract"]
    assert contract["identity_fields"] == [
        "tenant_id",
        "idempotency_scope",
        "idempotency_key",
    ]
    assert contract["key_reuse_rule"] == (
        "never_reuse_key_for_different_semantic_command"
    )


def test_request_fingerprint_is_stable_and_semantic(reliability):
    fingerprint = reliability["idempotency_contract"]["request_fingerprint"]
    assert fingerprint["algorithm"] == "sha256"
    assert fingerprint["input"] == (
        "canonical_json_of_semantically_material_command_fields"
    )
    assert set(fingerprint["excludes"]) == {
        "transport_retry_count",
        "received_at",
        "trace_sampling_metadata",
    }


def test_idempotency_decision_table_is_complete(reliability):
    decisions = _by_code(
        reliability["idempotency_contract"]["decisions"],
        "condition",
    )
    assert set(decisions) == {
        "identity_absent",
        "identity_present_same_fingerprint_completed",
        "identity_present_same_fingerprint_processing",
        "identity_present_same_fingerprint_failed_retryable",
        "identity_present_same_fingerprint_failed_terminal",
        "identity_present_different_fingerprint",
    }
    assert decisions[
        "identity_present_same_fingerprint_completed"
    ]["result"] == "return_original_result_without_side_effect"
    assert decisions[
        "identity_present_different_fingerprint"
    ]["result"] == "reject_idempotency_conflict"


def test_idempotency_result_commits_with_business_effect(reliability):
    contract = reliability["idempotency_contract"]
    assert contract["transaction_rule"] == (
        "idempotency_result_and_authoritative_business_writes_commit_atomically"
    )
    assert contract["response_rule"] == (
        "replay_returns_same_public_ids_and_semantically_identical_result"
    )


def test_idempotency_scopes_cover_money_and_reconciliation(reliability):
    scopes = set(reliability["idempotency_contract"]["scope_examples"])
    assert {
        "payment_intent.create",
        "payment_settlement.confirm",
        "payment_allocation.create",
        "payment_refund.request",
        "reconciliation_window.close",
        "offline_command.replay",
    } <= scopes


def test_concurrency_lock_order_is_unique_and_stable(reliability):
    order = reliability["concurrency_contract"]["lock_order"]
    assert len(order) == len(set(order))
    assert order.index("idempotency_record") < order.index("payment_intent")
    assert order.index("payment_settlement_or_value_source") < order.index(
        "financial_obligation"
    )
    assert order.index("reconciliation_series") < order.index(
        "reconciliation_window"
    )


def test_exact_high_risk_operations_have_concurrency_policies(reliability):
    operations = reliability["concurrency_contract"]["operations"]
    codes = [item["operation_code"] for item in operations]
    assert len(codes) == len(set(codes))
    assert set(codes) == EXPECTED_OPERATIONS
    assert all(LOWER_CODE.fullmatch(code) for code in codes)
    for operation in operations:
        assert operation["strategy"].strip()
        assert operation["locked_resources"]
        assert operation["postconditions"]


def test_allocation_locks_value_before_obligation(reliability):
    operation = _operation(reliability, "create_payment_allocation")
    assert operation["locked_resources"] == [
        "value_source",
        "financial_obligation",
    ]
    assert set(operation["postconditions"]) == {
        "active_allocations_lte_available_value",
        "active_allocations_lte_allocatable_obligation",
    }


def test_refund_success_is_atomic_across_cash_out_and_deallocation(reliability):
    operation = _operation(reliability, "succeed_payment_refund")
    assert set(operation["locked_resources"]) == {
        "payment_refund",
        "payment_settlement",
        "payment_allocation",
    }
    assert "cash_out_and_deallocation_recorded_atomically" in (
        operation["postconditions"]
    )


def test_reconciliation_close_locks_continuity_chain(reliability):
    operation = _operation(reliability, "close_reconciliation_window")
    assert operation["locked_resources"] == [
        "reconciliation_series",
        "predecessor_window",
        "reconciliation_window",
    ]
    assert {
        "required_predecessor_is_closed",
        "opening_equals_predecessor_actual",
        "server_totals_recomputed",
    } == set(operation["postconditions"])


def test_retry_policy_is_bounded_and_preserves_identity(reliability):
    retry = reliability["concurrency_contract"]["retry_policy"]
    assert retry["maximum_automatic_attempts"] == 3
    assert retry["requires_same_idempotency_identity"] is True
    assert set(retry["never_retry"]) == {
        "idempotency_conflict",
        "authentication_failed",
        "invalid_transition",
        "invariant_violation",
    }


def test_provider_ingress_uses_provider_auth_not_user_bearer_auth(reliability):
    inbox = reliability["provider_inbox_contract"]
    assert inbox["ingress_is_publicly_reachable"] is True
    assert inbox["ingress_uses_user_bearer_auth"] is False
    assert set(inbox["ingress_authentication"]) == {
        "provider_signature_or_mtls",
        "configured_provider_account",
        "timestamp_or_nonce_policy",
    }


def test_provider_inbox_identity_and_routing_never_guess_tenant(reliability):
    inbox = reliability["provider_inbox_contract"]
    assert inbox["identity_fields"] == [
        "tenant_id",
        "provider_account_id",
        "provider_event_reference",
    ]
    assert inbox["routing_priority"][0] == "provider_account_reference"
    assert "default_to_a_tenant" in inbox["forbidden_actions"]
    assert "trust_tenant_id_from_unsigned_payload" in inbox[
        "forbidden_actions"
    ]


def test_provider_inbox_state_graph_is_closed(reliability):
    inbox = reliability["provider_inbox_contract"]
    states = set(inbox["processing_states"])
    assert states == {
        "received",
        "authenticated",
        "processing",
        "processed",
        "rejected",
        "quarantined",
    }
    for transition in inbox["transitions"]:
        assert transition["from"] in states
        assert transition["to"] in states
        assert transition["requires"]


def test_provider_callback_acknowledges_capture_not_financial_success(reliability):
    inbox = reliability["provider_inbox_contract"]
    assert inbox["response_policy"] == (
        "acknowledge_durable_capture_not_financial_success"
    )
    assert inbox["duplicate_policy"] == (
        "return_accepted_without_repeating_business_side_effects"
    )
    assert "post_financial_event_directly_from_raw_callback" in inbox[
        "forbidden_actions"
    ]


def test_transactional_outbox_is_atomic_and_at_least_once(reliability):
    outbox = reliability["transactional_outbox_contract"]
    assert outbox["write_rule"] == (
        "message_and_authoritative_business_change_commit_in_same_database_transaction"
    )
    assert outbox["delivery_guarantee"] == "at_least_once"
    assert outbox["consumer_requirement"] == (
        "deduplicate_before_applying_side_effect"
    )


def test_outbox_envelope_is_tenant_version_and_causation_aware(reliability):
    required = set(
        reliability["transactional_outbox_contract"]["required_envelope"]
    )
    assert {
        "message_id",
        "tenant_id",
        "organization_unit_id",
        "event_type",
        "event_version",
        "message_key",
        "correlation_id",
        "causation_id",
        "payload",
    } <= required


def test_outbox_states_match_m03_lifecycle(reliability, lifecycles):
    outbox_states = set(
        reliability["transactional_outbox_contract"]["delivery_states"]
    )
    machine = _by_code(
        lifecycles["state_machines"], "machine_code"
    )["outbox_message"]
    assert outbox_states == {item["code"] for item in machine["states"]}


def test_consumer_inbox_deduplicates_atomically(reliability):
    inbox = reliability["consumer_inbox_contract"]
    assert inbox["identity_fields"] == [
        "consumer_name",
        "tenant_id",
        "message_id",
    ]
    assert inbox["duplicate_policy"] == (
        "completed_duplicate_returns_recorded_result_without_side_effect"
    )
    assert inbox["transaction_rule"] == (
        "consumer_result_and_local_side_effect_commit_atomically"
    )


def test_offline_commands_preserve_identity_time_and_configuration(reliability):
    offline = reliability["offline_replay_contract"]
    required = set(offline["required_command_envelope"])
    assert {
        "command_id",
        "tenant_id",
        "organization_unit_id",
        "actor_id",
        "device_id",
        "idempotency_scope",
        "idempotency_key",
        "occurred_at",
        "client_sequence",
        "configuration_version",
    } <= required
    assert offline["time_rule"] == (
        "preserve_occurred_at_and_assign_server_recorded_at"
    )


def test_offline_money_and_stock_never_use_silent_last_write_wins(reliability):
    offline = reliability["offline_replay_contract"]
    assert offline["money_and_stock_rule"] == (
        "never_silently_last_write_wins"
    )
    assert "require_operator_resolution" in offline["conflict_policies"]
    assert offline["authorization_rule"] == (
        "revalidate_actor_device_permission_and_tenant_at_replay"
    )


def test_observability_covers_replay_provider_and_delivery_failure(reliability):
    observed = reliability["observability_contract"]
    assert {
        "idempotent_replays",
        "idempotency_conflicts",
        "concurrency_retries",
        "provider_callbacks_quarantined",
        "outbox_lag_seconds",
        "outbox_dead_letters",
        "offline_conflicts",
    } <= set(observed["required_metrics"])
    assert "correlation_id" in observed["required_dimensions"]
    assert "dead_letter_created" in observed["required_alerts"]


def test_workflow_event_catalog_is_exact_unique_and_nonfinancial(workflows):
    event_types = workflows["workflow_event_types"]
    codes = [item["event_type"] for item in event_types]
    assert len(codes) == len(set(codes))
    assert set(codes) == EXPECTED_WORKFLOW_EVENTS
    assert all(UPPER_CODE.fullmatch(code) for code in codes)
    assert all(item["event_version"] == 1 for item in event_types)
    assert all(item["financial"] is False for item in event_types)


def test_workflow_envelope_is_immutable_and_outbox_delivered(workflows):
    envelope = workflows["workflow_event_envelope"]
    assert envelope["immutable"] is True
    assert envelope["delivery"] == "transactional_outbox"
    assert envelope["consumer_delivery_assumption"] == "at_least_once"
    assert {
        "tenant_id",
        "organization_unit_id",
        "correlation_id",
        "causation_id",
        "payload",
    } <= set(envelope["required_fields"])


def test_confirmation_policies_are_exact_and_explicit(workflows):
    policies = workflows["confirmation_policies"]
    codes = [item["policy_code"] for item in policies]
    assert len(codes) == len(set(codes))
    assert set(codes) == EXPECTED_POLICIES
    for policy in policies:
        assert policy["confirmation_requirements"]
        assert isinstance(policy["allows_zero_value"], bool)
        assert isinstance(policy["allows_credit"], bool)


def test_payment_required_policy_requires_settlement_allocation_and_condition(
    workflows,
):
    policy = _by_code(
        workflows["confirmation_policies"], "policy_code"
    )["payment_required"]
    assert policy["confirmation_requirements"] == [
        "confirmed_settlement",
        "sufficient_allocation",
        "payment_condition_satisfied",
    ]
    assert policy["allows_credit"] is False


def test_xafpay_is_one_adapter_and_not_a_hardcoded_rail(workflows):
    adapter = workflows["orchestrator_adapter_contract"]
    assert adapter["xafpay_role"] == "one_supported_orchestrator_adapter"
    assert adapter["direct_provider_supported"] is True
    assert adapter["additional_orchestrators_supported"] is True
    assert set(adapter["required_dimensions"]) >= {
        "payment_method",
        "payment_rail",
        "orchestrator",
        "underlying_provider",
    }


def test_adapter_cannot_write_finance_confirm_or_fulfill(workflows):
    adapter = workflows["orchestrator_adapter_contract"]
    assert adapter["adapter_may_write_financial_event_directly"] is False
    assert adapter["adapter_may_confirm_commercial_transaction_directly"] is False
    assert adapter["adapter_may_dispatch_fulfillment_directly"] is False


def test_exact_flows_have_contiguous_sequences_and_known_policies(workflows):
    flows = workflows["flows"]
    codes = [item["flow_code"] for item in flows]
    assert len(codes) == len(set(codes))
    assert set(codes) == EXPECTED_FLOWS
    for flow in flows:
        assert flow["confirmation_policy"] in EXPECTED_POLICIES
        sequences = [step["sequence"] for step in flow["steps"]]
        assert sequences == list(range(1, len(sequences) + 1))
        assert flow["postconditions"]


def test_external_order_flow_cannot_skip_settlement_allocation_or_confirmation(
    workflows,
):
    flow = _flow(workflows, "external_payment_required_order")
    actions = [step["action"] for step in flow["steps"]]
    assert actions.index("verify_finality_and_confirm_settlement") < actions.index(
        "allocate_confirmed_value"
    )
    assert actions.index("allocate_confirmed_value") < actions.index(
        "evaluate_payment_condition_and_confirm_commercial_transaction"
    )
    assert actions.index(
        "evaluate_payment_condition_and_confirm_commercial_transaction"
    ) < actions.index("deliver_fulfillment_request")


def test_credit_and_complimentary_flows_are_valid_nonpayment_paths(workflows):
    credit = _flow(workflows, "credit_allowed_order")
    complimentary = _flow(workflows, "fully_complimentary_order")
    credit_outputs = {
        output for step in credit["steps"] for output in step["produces"]
    }
    comp_outputs = {
        output
        for step in complimentary["steps"]
        for output in step["produces"]
    }
    assert "OBLIGATION_OPENED" in credit_outputs
    assert "PAYMENT_SETTLED" not in credit_outputs
    assert "COMPLIMENTARY_GRANTED" in comp_outputs
    assert "PAYMENT_SETTLED" not in comp_outputs


def test_duplicate_callback_flow_has_exactly_one_financial_effect(workflows):
    flow = _flow(workflows, "duplicate_provider_callback")
    outputs = [output for step in flow["steps"] for output in step["produces"]]
    assert outputs.count("PAYMENT_SETTLED") == 1
    assert "idempotent_replay_result" in outputs
    assert set(flow["postconditions"]) == {
        "one_settlement",
        "one_payment_settled_event",
        "no_duplicate_allocation",
        "no_duplicate_fulfillment",
    }


def test_offline_flow_returns_explicit_accept_or_conflict_receipt(workflows):
    flow = _flow(workflows, "offline_command_replay")
    outputs = {output for step in flow["steps"] for output in step["produces"]}
    assert "accepted_or_conflict_result" in outputs
    assert "offline_replay_receipt" in outputs
    assert "conflicts_are_explicit" in flow["postconditions"]


def test_flow_financial_outputs_resolve_to_m01_event_catalog(workflows, events):
    approved = {item["event_type_code"] for item in events["event_types"]}
    workflow_events = EXPECTED_WORKFLOW_EVENTS
    uppercase_outputs = {
        output
        for flow in workflows["flows"]
        for step in flow["steps"]
        for output in step["produces"]
        if UPPER_CODE.fullmatch(output)
    }
    financial_outputs = uppercase_outputs - workflow_events
    assert financial_outputs == {
        "PAYMENT_SETTLED",
        "PAYMENT_ALLOCATED",
        "OBLIGATION_OPENED",
        "COMPLIMENTARY_GRANTED",
    }
    assert financial_outputs <= approved


def test_flow_entity_outputs_resolve_to_m03_entity_contracts(workflows, entities):
    entity_codes = {item["entity_code"] for item in entities["entities"]}
    entity_outputs = {
        output
        for flow in workflows["flows"]
        for step in flow["steps"]
        for output in step["produces"]
        if output in entity_codes
    }
    assert {
        "commercial_transaction",
        "financial_obligation",
        "payment_intent",
        "payment_attempt",
        "payment_settlement",
        "value_source",
        "payment_allocation",
    } <= entity_outputs


def test_forbidden_shortcuts_cover_provider_delivery_offline_and_reconciliation(
    workflows,
):
    forbidden = set(workflows["forbidden_shortcuts"])
    assert {
        "raw_callback_to_payment_settled_event",
        "raw_callback_to_commercial_confirmation",
        "payment_attempt_succeeded_to_fulfillment",
        "provider_adapter_to_financial_tables",
        "provider_adapter_to_pack_queue",
        "outbox_publish_before_business_commit",
        "consumer_side_effect_without_inbox_deduplication",
        "offline_last_write_wins_for_money_or_stock",
        "reconciliation_correction_by_rewriting_financial_events",
    } <= forbidden
