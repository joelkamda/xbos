"""PC7 neutral-interaction authority registration-foundation contract."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from core.platform import interaction
from core.platform.interaction import contracts

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/platform/v1"

def _json(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))

def _sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

def test_pc7_owner_module_facade_and_ten_primitives_are_exact():
    authority = _json("pc7_neutral_interaction_authority.json")
    assert authority["authority"] == "PC7"
    assert authority["authority_identity"] == "NEUTRAL_INTERACTION_AUTHORITY"
    assert authority["module"] == "interaction"
    assert authority["public_facade"] == "core.platform.interaction"
    assert authority["source_checkpoint"] == "b067d0a"
    assert authority["platform_release_predecessor_head"] == "pc5_identity_policy_audit_025"
    assert authority["accepted_schema_head"] == "ia0_neutral_interaction_authority_045"
    assert authority["alembic_parent"] == "r63_legacy_inventory_writer_compat_044"
    assert authority["canonical_primitives"] == list(contracts.CANONICAL_PRIMITIVES)
    assert len(authority["canonical_primitives"]) == 10
    assert authority["internal_persistence_support"] == {
        "table": "ia0_commands",
        "classification": "INTERNAL_COMMAND_LEDGER",
        "public_business_primitive": False,
    }

def test_pc7_preserves_a1_authority_boundaries_and_ai_non_authority_laws():
    authority = _json("pc7_neutral_interaction_authority.json")
    assert authority["authority_boundaries"] == contracts.AUTHORITY_BOUNDARIES == {
        "party": "PC2", "authentication": "PC5", "employee_membership": "PC5",
        "workflow_task": "SO6", "document_file": "SO7", "transport_delivery": "SO8",
        "payment_economic_truth": "NEUTRAL_FINANCE",
        "provider_execution": "XAFPAY_GATEWAY",
        "domain_business_truth": "DOMAIN_OWNER", "frontend_business_truth": "NONE",
    }
    assert authority["ai"]["role"] == "PROPOSER_NON_AUTHORITY"
    assert authority["ai"]["allowed_actions"] == sorted(contracts.AI_ALLOWED_ACTIONS)
    assert authority["ai"]["forbidden_actions"] == sorted(contracts.AI_FORBIDDEN_ACTIONS)
    assert authority["constitutional_laws"] == sorted(contracts.CONSTITUTIONAL_LAWS)
def test_pc7_data_authority_and_required_authority_are_registered_once():
    data = _json("pc0_data_authority_register.json")
    rows = [row for row in data["authorities"] if row.get("code") == "neutral_interaction"]
    assert len(rows) == 1 and rows[0]["owner"] == "PC7" and rows[0]["module"] == "interaction"
    for table in (
        "ia0_external_channel_identities", "ia0_conversations",
        "ia0_conversation_participants", "ia0_interaction_sessions",
        "ia0_interaction_messages", "ia0_interaction_intents",
        "ia0_interaction_handoffs", "ia0_interaction_capability_grants",
        "ia0_interaction_context_bindings", "ia0_interaction_events", "ia0_commands",
    ):
        assert table in rows[0]["current_store"]
    assert data["required_authorities"].count("neutral_interaction") == 1
    assert set(data["required_authorities"]) == {row["code"] for row in data["authorities"]}

def test_pc7_module_and_dependency_policy_are_exact_and_dependency_free():
    module_map = _json("pc0_module_map.json")
    rows = [row for row in module_map["modules"] if row.get("code") == "interaction"]
    assert rows == [{
        "code": "interaction", "kind": "platform_authority", "owner": "PC7",
        "source_roots": ["core/platform/interaction"],
    }]
    policy = _json("pc0_dependency_policy.json")
    assert policy["allowed_directions"]["interaction"] == []
    assert all(
        "interaction" not in targets
        for source, targets in policy["allowed_directions"].items() if source != "interaction"
    )
def test_pc7_public_interface_contract_and_pc0_registry_match_actual_package_exports():
    contract = _json("pc7_public_interfaces.json")
    expected = [f"core.platform.interaction.{name}" for name in interaction.__all__]
    assert len(expected) == 62 == contract["public_symbol_count"]
    assert contract["public"] == expected
    groups = contract["classifications"]
    classified = [item for values in groups.values() for item in values]
    assert set(groups) == {
        "PUBLIC_VALUE_CONTRACT", "PUBLIC_AUTHORITY_INTERFACE",
        "PUBLIC_REPOSITORY_INTERFACE",
    }
    assert len(classified) == len(set(classified)) == 62
    assert set(classified) == set(expected)
    registry = _json("pc0_public_private_interfaces.json")
    rows = [row for row in registry["interfaces"] if row.get("module") == "interaction"]
    assert len(rows) == 1
    assert rows[0]["public"] == expected
    assert rows[0]["private"] == contract["private"]

def test_pc7_migration_is_existing_045_with_ten_roots_and_one_internal_command_table():
    version = ROOT / "alembic_neutral/versions/ia0_neutral_interaction_authority_045.py"
    tree = ast.parse(version.read_text(encoding="utf-8"))
    assigns = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}
    }
    assert assigns == {
        "revision": "ia0_neutral_interaction_authority_045",
        "down_revision": "r63_legacy_inventory_writer_compat_044",
    }
    assert _sha(version) == "6f969e236c9a8b9d382a272369a317ed53f887a2aeb89e6d20534157fe10836d"
    sql = (ROOT / "alembic_neutral/sql/ia0_neutral_interaction_authority_up.sql").read_text(
        encoding="utf-8"
    )
    tables = set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?([a-zA-Z0-9_]+)", sql, re.I))
    assert len(tables) == 11
    assert "ia0_commands" in tables
    assert len(tables - {"ia0_commands"}) == 10

def test_pc6_public_contract_inventory_remains_frozen_pc1_through_pc5_only():
    inventory = _json("pc6_public_contract_inventory.json")
    assert {item["authority"] for item in inventory["interfaces"]} == {
        "PC1", "PC2", "PC3", "PC4", "PC5",
    }
    assert "PC7" not in json.dumps(inventory)

def test_pc7_full_registration_preserves_undefined_a3():
    authority = _json("pc7_neutral_interaction_authority.json")
    assert authority["a3_definition"] == "NOT_YET_REPOSITORY_AUTHORITY"
    assert authority["registration"] == {
        "class": "FULL_PLATFORM_REGISTRATION",
        "release_manifest": "pc7_release_manifest.json",
        "release_freeze": True,
    }
    assert (CONTRACTS / "pc7_release_manifest.json").is_file()
