#!/usr/bin/env python3
"""Verify immutable PC7 neutral-interaction authority through current successor release."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONTRACTS = ROOT / "contracts/platform/v1"

EXPECTED_PRIMITIVES = (
    "ExternalChannelIdentity", "Conversation", "ConversationParticipant",
    "InteractionSession", "InteractionMessage", "InteractionIntent",
    "InteractionHandoff", "InteractionEvent", "InteractionCapabilityGrant",
    "InteractionContextBinding",
)
EXPECTED_BOUNDARIES = {
    "party": "PC2", "authentication": "PC5", "employee_membership": "PC5",
    "workflow_task": "SO6", "document_file": "SO7", "transport_delivery": "SO8",
    "payment_economic_truth": "NEUTRAL_FINANCE",
    "provider_execution": "XAFPAY_GATEWAY",
    "domain_business_truth": "DOMAIN_OWNER", "frontend_business_truth": "NONE",
}
MIGRATION_HASHES = {
    "alembic_neutral/versions/ia0_neutral_interaction_authority_045.py":
        "6f969e236c9a8b9d382a272369a317ed53f887a2aeb89e6d20534157fe10836d",
    "alembic_neutral/sql/ia0_neutral_interaction_authority_up.sql":
        "06216457750089f12ab40ed9cfeda24114b795457ed1aeb8c08fe30e7e60642c",
    "alembic_neutral/sql/ia0_neutral_interaction_authority_down.sql":
        "ee09c224815105b77225b7bf08e9b0167beb77a50f021e9615b1f8f6a9c3c3c9",
}
EXPECTED_TABLES = {
    "ia0_commands", "ia0_external_channel_identities", "ia0_conversations",
    "ia0_conversation_participants", "ia0_interaction_sessions",
    "ia0_interaction_messages", "ia0_interaction_intents",
    "ia0_interaction_handoffs", "ia0_interaction_events",
    "ia0_interaction_capability_grants", "ia0_interaction_context_bindings",
}

def _json(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _sha(relative):
    data = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _literal_assign(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"missing assignment={name}")
def verify():
    from core.platform import interaction
    from core.platform.interaction import contracts
    from core.platform.release_integrity import (
        release_chain, verify_historical_release, verify_latest_release,
    )

    authority = _json("pc7_neutral_interaction_authority.json")
    interfaces = _json("pc7_public_interfaces.json")
    module_map = _json("pc0_module_map.json")
    data = _json("pc0_data_authority_register.json")
    registry = _json("pc0_public_private_interfaces.json")
    policy = _json("pc0_dependency_policy.json")
    pc6_inventory = _json("pc6_public_contract_inventory.json")

    identity = (
        authority.get("authority"), authority.get("authority_identity"),
        authority.get("module"), authority.get("public_facade"),
    )
    if identity != ("PC7", "NEUTRAL_INTERACTION_AUTHORITY", "interaction",
                    "core.platform.interaction"):
        raise RuntimeError("PC7 authority identity or facade mismatch")
    lineage = (
        authority.get("source_checkpoint"),
        authority.get("platform_release_predecessor_head"),
        authority.get("accepted_schema_head"), authority.get("alembic_parent"),
    )
    if lineage != (
        "b067d0a", "pc5_identity_policy_audit_025",
        "ia0_neutral_interaction_authority_045", "r63_legacy_inventory_writer_compat_044",
    ):
        raise RuntimeError("PC7 checkpoint or lineage distinction mismatch")
    if tuple(authority.get("canonical_primitives", ())) != EXPECTED_PRIMITIVES:
        raise RuntimeError("PC7 canonical primitive set changed")
    if tuple(contracts.CANONICAL_PRIMITIVES) != EXPECTED_PRIMITIVES:
        raise RuntimeError("A1 canonical primitive set changed")
    support = authority.get("internal_persistence_support", {})
    if support != {
        "table": "ia0_commands", "classification": "INTERNAL_COMMAND_LEDGER",
        "public_business_primitive": False,
    }:
        raise RuntimeError("PC7 internal command-ledger classification changed")
    if authority.get("authority_boundaries") != EXPECTED_BOUNDARIES:
        raise RuntimeError("PC7 authority boundary registration mismatch")
    if contracts.AUTHORITY_BOUNDARIES != EXPECTED_BOUNDARIES:
        raise RuntimeError("A1 PC7 authority boundaries changed")
    if authority.get("registration") != {
        "class": "FULL_PLATFORM_REGISTRATION",
        "release_manifest": "pc7_release_manifest.json",
        "release_freeze": True,
    }:
        raise RuntimeError("PC7 final registration lifecycle mismatch")
    if authority.get("a3_definition") != "NOT_YET_REPOSITORY_AUTHORITY":
        raise RuntimeError("A3 scope was invented under PC7")

    module_rows = [row for row in module_map["modules"] if row.get("code") == "interaction"]
    expected_module = {
        "code": "interaction", "kind": "platform_authority", "owner": "PC7",
        "source_roots": ["core/platform/interaction"],
    }
    if module_rows != [expected_module]:
        raise RuntimeError("PC7 module-map registration mismatch")
    data_rows = [row for row in data["authorities"] if row.get("code") == "neutral_interaction"]
    if len(data_rows) != 1 or data_rows[0].get("owner") != "PC7" or data_rows[0].get("module") != "interaction":
        raise RuntimeError("PC7 data-authority registration mismatch")
    if data["required_authorities"].count("neutral_interaction") != 1:
        raise RuntimeError("PC7 required-authority registration mismatch")
    if set(data["required_authorities"]) != {row["code"] for row in data["authorities"]}:
        raise RuntimeError("required-authority mirror mismatch")
    exported = [f"core.platform.interaction.{name}" for name in interaction.__all__]
    rows = [row for row in registry["interfaces"] if row.get("module") == "interaction"]
    if len(rows) != 1 or rows[0].get("public") != exported:
        raise RuntimeError("PC7 public/private registry does not match package exports")
    if policy["allowed_directions"].get("interaction") != []:
        raise RuntimeError("PC7 outbound dependency policy must be empty")
    if any("interaction" in targets for source, targets in policy["allowed_directions"].items()
           if source != "interaction"):
        raise RuntimeError("forbidden inbound PC7 code dependency registered")
    if interfaces.get("public") != exported or interfaces.get("public_symbol_count") != len(exported):
        raise RuntimeError("PC7 public-interface contract does not match package exports")
    groups = interfaces.get("classifications", {})
    classified = [item for group in groups.values() for item in group]
    if len(classified) != len(set(classified)) or set(classified) != set(exported):
        raise RuntimeError("PC7 public-interface classification mismatch")

    if {item["authority"] for item in pc6_inventory["interfaces"]} != {
        "PC1", "PC2", "PC3", "PC4", "PC5",
    }:
        raise RuntimeError("frozen PC6 public-contract inventory changed")
    if "PC7" in json.dumps(pc6_inventory):
        raise RuntimeError("PC7 inserted into frozen PC6 public-contract inventory")

    version = ROOT / "alembic_neutral/versions/ia0_neutral_interaction_authority_045.py"
    if _literal_assign(version, "revision") != "ia0_neutral_interaction_authority_045":
        raise RuntimeError("IA0 migration revision changed")
    if _literal_assign(version, "down_revision") != "r63_legacy_inventory_writer_compat_044":
        raise RuntimeError("IA0 migration parent changed")
    for relative, expected in MIGRATION_HASHES.items():
        if _sha(relative) != expected:
            raise RuntimeError(f"accepted IA0 migration bytes changed={relative}")
    sql = (ROOT / "alembic_neutral/sql/ia0_neutral_interaction_authority_up.sql").read_text(
        encoding="utf-8"
    )
    tables = set(re.findall(
        r"CREATE TABLE(?: IF NOT EXISTS)?\s+(?:public\.)?([a-zA-Z0-9_]+)", sql, re.I
    ))
    if tables != EXPECTED_TABLES or len(tables - {"ia0_commands"}) != 10:
        raise RuntimeError(f"IA0 table topology mismatch={sorted(tables)}")

    chain = release_chain(ROOT)
    if [number for number, _ in chain] != [1, 2, 3, 4, 5, 6, 7, 8]:
        raise RuntimeError("Platform release chain is not contiguous through PC8")
    release = _json("pc7_release_manifest.json")
    pc8_successor = _json("pc8_h1b_private_route_admission_successor.json")
    if _sha("contracts/platform/v1/pc7_release_manifest.json") != pc8_successor["historical_manifest_sha256"]["pc7"]:
        raise RuntimeError("immutable PC7 release manifest bytes changed")
    if (
        release.get("release") != "XBOS_PLATFORM_CORE_PC7"
        or release.get("source_checkpoint") != "b067d0a"
        or release.get("previous_head") != "pc5_identity_policy_audit_025"
        or release.get("accepted_head") != "ia0_neutral_interaction_authority_045"
        or release.get("migration_count") != 1
        or release.get("fingerprint_policy", {}).get("release_sequence") != 7
    ):
        raise RuntimeError("PC7 release metadata mismatch")

    pc8 = _json("pc8_release_manifest.json")
    for number in range(1, 8):
        report = verify_historical_release(ROOT, number)
        expected_count = len(pc8[f"historical_pc{number}_replacements"])
        if report["latest"] != 8 or report["replacement_count"] != expected_count:
            raise RuntimeError(f"PC{number} historical resolution through PC8 mismatch={report}")
    for relative in ("XBOS_PC7_INSTALL_AND_VERIFY.txt", "XBOS_PC7_RUN_ACCEPTANCE.cmd"):
        if not (ROOT / relative).is_file():
            raise RuntimeError(f"missing PC7 operator surface={relative}")

    release_sha = _sha("contracts/platform/v1/pc7_release_manifest.json")
    for artifact in release["artifacts"]:
        path = ROOT / artifact["path"]
        if path.suffix.casefold() in {
            ".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"
        }:
            if release_sha in path.read_text(encoding="utf-8", errors="ignore"):
                raise RuntimeError(f"PC7 release self-hash cycle={artifact['path']}")

    return {
        "status": "PASS",
        "authority": "PC7",
        "authority_identity": "NEUTRAL_INTERACTION_AUTHORITY",
        "public_symbol_count": len(exported),
        "canonical_primitive_count": 10,
        "internal_command_table_count": 1,
        "migration": "ia0_neutral_interaction_authority_045",
        "latest_platform_release": 8,
        "pc7_release_manifest": "PASS_HISTORICAL",
        "artifact_count": 33,
        "a3_definition": "NOT_YET_REPOSITORY_AUTHORITY",
    }


if __name__ == "__main__":
    result = verify()
    print("PC7_FULL_PLATFORM_REGISTRATION=PASS")
    print("PC7_HISTORICAL_RELEASE_THROUGH_PC8=PASS")
    print("PC7_RELEASE_MANIFEST_IMMUTABLE=PASS")
    for key, value in result.items():
        print(f"{key.upper()}={value}")
