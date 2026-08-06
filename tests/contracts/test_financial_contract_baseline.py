import hashlib
import json
import re
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
FINANCE_ROOT = ROOT / "contracts" / "finance" / "v1"
MANIFEST_PATH = FINANCE_ROOT / "contract_baseline_manifest.json"

LOWER_CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
UPPER_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _semantic_sha256(document: dict) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _by_code(items: list[dict], field: str) -> dict:
    return {item[field]: item for item in items}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return _load(MANIFEST_PATH)


@pytest.fixture(scope="module")
def catalogs(manifest) -> dict[str, dict]:
    return {
        component["catalog_code"]: _load(ROOT / component["path"])
        for component in manifest["components"]
    }


def test_baseline_identity_is_approved_v1(manifest):
    assert manifest["baseline_code"] == "XBOS_NEUTRAL_FINANCIAL_CONTRACT_BASELINE"
    assert manifest["baseline_version"] == 1
    assert manifest["status"] == "approved"
    assert manifest["approved_at"] == "2026-08-06T00:00:00Z"


def test_baseline_starts_after_the_m04_checkpoint(manifest):
    checkpoint = manifest["source_checkpoint"]
    assert checkpoint == {
        "branch": "track-b/m0-executable-neutral-contracts",
        "parent_commit": "a9aacf0",
        "b2_tag": "track-b-b2-canonical-model-20260805",
    }


def test_semantic_fingerprint_policy_is_portable(manifest):
    policy = manifest["semantic_fingerprint"]
    assert policy["algorithm"] == "sha256"
    assert policy["canonicalization"] == (
        "utf8_json_sorted_keys_compact_separators_ensure_ascii_false"
    )
    assert policy["line_ending_independent"] is True


def test_manifest_has_exactly_seven_ordered_components(manifest):
    components = manifest["components"]
    assert len(components) == 7
    assert [item["sequence"] for item in components] == list(range(1, 8))
    assert len({item["path"] for item in components}) == 7
    assert len({item["catalog_code"] for item in components}) == 7


def test_manifest_component_paths_are_versioned_json(manifest):
    for component in manifest["components"]:
        assert component["path"].startswith("contracts/finance/v1/")
        assert component["path"].endswith(".json")
        assert ".." not in Path(component["path"]).parts


def test_every_manifest_component_exists(manifest):
    for component in manifest["components"]:
        assert (ROOT / component["path"]).is_file()


def test_component_metadata_matches_manifest(manifest, catalogs):
    for component in manifest["components"]:
        catalog = catalogs[component["catalog_code"]]
        assert catalog["catalog_code"] == component["catalog_code"]
        assert catalog["catalog_version"] == component["catalog_version"]
        assert catalog["contract_revision"] == component["contract_revision"]
        assert catalog["status"] == "approved"


def test_component_semantic_fingerprints_match(manifest, catalogs):
    for component in manifest["components"]:
        catalog = catalogs[component["catalog_code"]]
        assert _semantic_sha256(catalog) == component["semantic_sha256"]


def test_contract_test_suite_manifest_is_exact(manifest):
    suites = manifest["contract_test_suites"]
    assert [item["phase"] for item in suites] == [
        "M0.1",
        "M0.2",
        "M0.3",
        "M0.4",
        "M0.5",
    ]
    assert [item["expected_tests"] for item in suites] == [18, 18, 26, 38, 30]
    assert len({item["path"] for item in suites}) == 5


def test_contract_test_files_exist_and_have_declared_counts(manifest):
    for suite in manifest["contract_test_suites"]:
        path = ROOT / suite["path"]
        assert path.is_file()
        count = len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.M))
        assert count == suite["expected_tests"]


def test_expected_test_totals_are_arithmetically_consistent(manifest):
    contract_total = sum(
        suite["expected_tests"] for suite in manifest["contract_test_suites"]
    )
    assert contract_total == manifest["expected_contract_tests"] == 130
    assert manifest["expected_characterization_tests"] == 18
    assert manifest["expected_total_tests"] == contract_total + 18 == 148


def test_authority_chain_is_unique_canonical_and_ordered(manifest):
    chain = manifest["authority_chain"]
    assert len(chain) == len(set(chain)) == 12
    assert all(LOWER_CODE.fullmatch(item) for item in chain)
    assert chain.index("verified_payment_settlement") < chain.index("payment_allocation")
    assert chain.index("payment_allocation") < chain.index("commercial_confirmation")
    assert chain.index("commercial_confirmation") < chain.index(
        "industry_pack_fulfillment"
    )


def test_global_invariants_are_unique_and_canonical(manifest):
    invariants = manifest["global_invariants"]
    assert len(invariants) == len(set(invariants)) == 13
    assert all(LOWER_CODE.fullmatch(item) for item in invariants)
    assert "payment_attempt_is_not_payment_settlement" in invariants
    assert "commercial_confirmation_is_not_fulfillment" in invariants


def test_implementation_authority_prioritizes_contracts_over_code(manifest):
    priority = manifest["implementation_authority"][
        "normative_sources_in_priority_order"
    ]
    assert priority == [
        "executable_contract_tests",
        "machine_readable_contract_catalogs",
        "approved_B2_architecture_records",
        "implementation_code",
        "historical_behavior",
    ]


def test_wnd_is_migrated_without_constraining_the_kernel(manifest):
    authority = manifest["implementation_authority"]
    assert "WND is migrated into the neutral model" in authority["compatibility_rule"]
    assert "obsolete architecture" in authority["compatibility_rule"]
    assert "Industry packs" in authority["extension_rule"]


def test_release_gate_freezes_the_expected_tag(manifest):
    gate = manifest["release_gate"]
    assert gate["tag"] == "track-b-m0-neutral-contracts-20260806"
    assert len(gate["required"]) == len(set(gate["required"])) == 6
    assert "all_cross_catalog_references_resolve" in gate["required"]
    assert "annotated_baseline_tag_is_pushed" in gate["required"]


def test_event_posting_profiles_reference_known_account_roles(catalogs):
    events = catalogs["XBOS_CANONICAL_FINANCIAL_EVENTS"]
    roles = catalogs["XBOS_CANONICAL_ACCOUNT_ROLES"]
    known_roles = {item["account_role"] for item in roles["account_roles"]}
    referenced = set()
    for event in events["event_types"]:
        for profile in event["posting_profiles"]:
            referenced.update(profile.get("debit_account_roles", []))
            referenced.update(profile.get("credit_account_roles", []))
    assert referenced
    assert referenced <= known_roles


def test_posting_scenario_events_reference_known_event_types(catalogs):
    events = catalogs["XBOS_CANONICAL_FINANCIAL_EVENTS"]
    scenarios = catalogs["XBOS_CANONICAL_FINANCIAL_POSTING_SCENARIOS"]
    known_events = {item["event_type_code"] for item in events["event_types"]}
    referenced = {
        event["event_type_code"]
        for scenario in scenarios["scenarios"]
        for event in scenario["events"]
    }
    assert referenced <= known_events


def test_posting_scenario_bindings_reference_known_account_roles(catalogs):
    roles = catalogs["XBOS_CANONICAL_ACCOUNT_ROLES"]
    scenarios = catalogs["XBOS_CANONICAL_FINANCIAL_POSTING_SCENARIOS"]
    known_roles = {item["account_role"] for item in roles["account_roles"]}
    for scenario in scenarios["scenarios"]:
        assert set(scenario["account_role_bindings"]) <= known_roles


def test_scenario_journal_lines_use_bound_account_roles(catalogs):
    scenarios = catalogs["XBOS_CANONICAL_FINANCIAL_POSTING_SCENARIOS"]
    for scenario in scenarios["scenarios"]:
        bindings = set(scenario["account_role_bindings"])
        for event in scenario["events"]:
            assert {line["account_role"] for line in event["journal_lines"]} <= bindings


def test_scenario_posting_profiles_resolve_on_their_event_types(catalogs):
    events = catalogs["XBOS_CANONICAL_FINANCIAL_EVENTS"]
    scenarios = catalogs["XBOS_CANONICAL_FINANCIAL_POSTING_SCENARIOS"]
    event_map = _by_code(events["event_types"], "event_type_code")
    for scenario in scenarios["scenarios"]:
        for occurrence in scenario["events"]:
            event_contract = event_map[occurrence["event_type_code"]]
            profiles = {
                item["profile_code"]
                for item in event_contract["posting_profiles"]
            }
            if occurrence["posting_profile_code"] is None:
                assert event_contract["posting_eligible"] is False
                assert profiles == set()
                assert occurrence["journal_lines"] == []
            else:
                assert occurrence["posting_profile_code"] in profiles


def test_entity_relationship_targets_resolve(catalogs):
    entities = catalogs["XBOS_CANONICAL_FINANCIAL_ENTITIES"]
    known_entities = {item["entity_code"] for item in entities["entities"]}
    for entity in entities["entities"]:
        for relationship in entity["relationships"]:
            assert relationship["target"] in known_entities
            assert relationship["tenant_match"] is True


def test_entity_state_machine_references_resolve(catalogs):
    entities = catalogs["XBOS_CANONICAL_FINANCIAL_ENTITIES"]
    lifecycles = catalogs["XBOS_CANONICAL_FINANCIAL_LIFECYCLES"]
    machines = {item["machine_code"] for item in lifecycles["state_machines"]}
    references = {
        item["state_machine"]
        for item in entities["entities"]
        if item["state_machine"] is not None
    }
    assert references == machines


def test_lifecycle_transition_states_resolve(catalogs):
    lifecycles = catalogs["XBOS_CANONICAL_FINANCIAL_LIFECYCLES"]
    for machine in lifecycles["state_machines"]:
        states = {item["code"] for item in machine["states"]}
        for transition in machine["transitions"]:
            assert transition["from"] in states
            assert transition["to"] in states


def test_reliability_outbox_states_match_entity_lifecycle(catalogs):
    reliability = catalogs["XBOS_FINANCIAL_EXECUTION_RELIABILITY"]
    lifecycles = catalogs["XBOS_CANONICAL_FINANCIAL_LIFECYCLES"]
    machine = _by_code(lifecycles["state_machines"], "machine_code")[
        "outbox_message"
    ]
    lifecycle_states = [item["code"] for item in machine["states"]]
    assert reliability["transactional_outbox_contract"]["delivery_states"] == (
        lifecycle_states
    )


def test_provider_inbox_transition_endpoints_resolve(catalogs):
    reliability = catalogs["XBOS_FINANCIAL_EXECUTION_RELIABILITY"]
    inbox = reliability["provider_inbox_contract"]
    states = set(inbox["processing_states"])
    for transition in inbox["transitions"]:
        assert transition["from"] in states
        assert transition["to"] in states


def test_workflow_financial_outputs_resolve_to_event_catalog(catalogs):
    events = catalogs["XBOS_CANONICAL_FINANCIAL_EVENTS"]
    workflows = catalogs["XBOS_PAYMENT_TO_FULFILLMENT_WORKFLOWS"]
    known_events = {item["event_type_code"] for item in events["event_types"]}
    workflow_events = {
        item["event_type"] for item in workflows["workflow_event_types"]
    }
    uppercase_outputs = {
        output
        for flow in workflows["flows"]
        for step in flow["steps"]
        for output in step["produces"]
        if UPPER_CODE.fullmatch(output)
    }
    financial_outputs = uppercase_outputs - workflow_events
    assert financial_outputs
    assert financial_outputs <= known_events


def test_workflow_entity_outputs_resolve_to_entity_catalog(catalogs):
    entities = catalogs["XBOS_CANONICAL_FINANCIAL_ENTITIES"]
    workflows = catalogs["XBOS_PAYMENT_TO_FULFILLMENT_WORKFLOWS"]
    known_entities = {item["entity_code"] for item in entities["entities"]}
    expected = {
        "commercial_transaction",
        "financial_obligation",
        "payment_intent",
        "payment_attempt",
        "payment_settlement",
        "value_source",
        "payment_allocation",
    }
    outputs = {
        output
        for flow in workflows["flows"]
        for step in flow["steps"]
        for output in step["produces"]
    }
    assert expected <= outputs
    assert expected <= known_entities


def test_workflow_events_are_disjoint_from_financial_events(catalogs):
    events = catalogs["XBOS_CANONICAL_FINANCIAL_EVENTS"]
    workflows = catalogs["XBOS_PAYMENT_TO_FULFILLMENT_WORKFLOWS"]
    financial = {item["event_type_code"] for item in events["event_types"]}
    operational = {
        item["event_type"] for item in workflows["workflow_event_types"]
    }
    assert financial.isdisjoint(operational)
    assert all(item["financial"] is False for item in workflows["workflow_event_types"])


def test_payment_to_fulfillment_boundary_agrees_across_catalogs(catalogs):
    events = catalogs["XBOS_CANONICAL_FINANCIAL_EVENTS"]
    workflows = catalogs["XBOS_PAYMENT_TO_FULFILLMENT_WORKFLOWS"]
    reliability = catalogs["XBOS_FINANCIAL_EXECUTION_RELIABILITY"]
    boundary = events["workflow_boundary"]
    adapter = workflows["orchestrator_adapter_contract"]
    forbidden = set(reliability["provider_inbox_contract"]["forbidden_actions"])
    assert boundary["raw_provider_success_may_confirm_commercial_transaction"] is False
    declared_nonfinancial = set(boundary["workflow_events_not_financial"])
    workflow_event_codes = {
        item["event_type"] for item in workflows["workflow_event_types"]
    }
    assert declared_nonfinancial <= workflow_event_codes
    assert {
        "PAYMENT_CONDITION_SATISFIED",
        "COMMERCIAL_TRANSACTION_CONFIRMED",
        "FULFILLMENT_REQUESTED",
    } <= declared_nonfinancial
    assert adapter["adapter_may_write_financial_event_directly"] is False
    assert adapter["adapter_may_confirm_commercial_transaction_directly"] is False
    assert adapter["adapter_may_dispatch_fulfillment_directly"] is False
    assert "post_financial_event_directly_from_raw_callback" in forbidden
    assert "confirm_commercial_transaction_directly_from_raw_callback" in forbidden
