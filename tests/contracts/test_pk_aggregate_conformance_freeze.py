from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/packs/v1"
HEAD = "pk456_pack_conformance_templates_038"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in {".cmd", ".ini", ".json", ".md", ".py", ".sql", ".toml", ".txt", ".yaml", ".yml"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_pk_aggregate_is_schema_neutral_full_pk0_pk6_freeze():
    contract = _json(CONTRACTS / "pk_aggregate_conformance_freeze.json")
    assert contract["coverage"] == [f"PK{number}" for number in range(7)]
    assert contract["previous_head"] == HEAD
    assert contract["accepted_head"] == HEAD
    assert contract["migration"] == "NONE"
    assert contract["business_capability_change"] == "NONE"
    assert contract["constitutional_rule"] == "pack_is_composition_not_authority"


def test_pk_component_lineage_is_contiguous():
    pk0123 = _json(CONTRACTS / "pk0123_authority.json")
    pk456 = _json(CONTRACTS / "pk456_authority.json")
    assert pk0123["accepted_head"] == "pk0123_pack_manifest_lifecycle_037"
    assert pk456["previous_head"] == pk0123["accepted_head"]
    assert pk456["accepted_head"] == HEAD
    assert pk0123["scope"] + pk456["scope"] == [f"PK{number}" for number in range(7)]


def test_pk_migration_tail_has_one_head_and_no_aggregate_revision():
    revisions = {}
    for path in sorted((ROOT / "alembic_neutral/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        try:
                            values[target.id] = ast.literal_eval(node.value)
                        except (ValueError, TypeError):
                            pass
        if isinstance(values.get("revision"), str):
            revisions[values["revision"]] = values.get("down_revision")
    heads = sorted(set(revisions) - {parent for parent in revisions.values() if isinstance(parent, str)})
    assert len(heads) == 1
    current = heads[0]
    lineage = []
    while current is not None:
        lineage.append(current)
        current = revisions[current]
    lineage = list(reversed(lineage))
    assert HEAD in lineage
    assert revisions[HEAD] == "pk0123_pack_manifest_lifecycle_037"
    assert revisions["pk0123_pack_manifest_lifecycle_037"] == "so_aggregate_conformance_hardening_036"
    assert not any("aggregate" in revision and revision.startswith("pk") for revision in revisions)


def test_pack_platform_sql_writes_only_pk_persistence():
    pattern = re.compile(r"\b(?:insert\s+into|update|delete\s+from)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.I)
    found = []
    for path in sorted((ROOT / "pack_platform").glob("*.py")):
        found.extend((path.name, table) for table in pattern.findall(path.read_text(encoding="utf-8")))
    assert found
    assert all(table.startswith("pk_") for _, table in found)


def test_pc0_keeps_pack_composition_as_single_authority_with_no_private_dependencies():
    module_map = _json(ROOT / "contracts/platform/v1/pc0_module_map.json")
    packs = next(row for row in module_map["modules"] if row["code"] == "packs")
    assert packs["owner"] == "PK"
    assert packs["kind"] == "pack_composition_authority"
    policy = _json(ROOT / "contracts/platform/v1/pc0_dependency_policy.json")
    assert policy["allowed_directions"]["packs"] == []
    authorities = _json(ROOT / "contracts/platform/v1/pc0_data_authority_register.json")
    authority = next(row for row in authorities["authorities"] if row["code"] == "pack_composition")
    assert authority["owner"] == "PK"


def test_payments_only_template_hides_workspaces_not_finance_kernel():
    template = _json(CONTRACTS / "examples/payments_only_template.json")
    workspaces = template["configuration_defaults"]["workspaces"]
    assert template["finance_kernel_required"] is True
    assert template["finance_workspace_exposed"] is False
    assert workspaces["payments"] is True
    assert all(workspaces[name] is False for name in ("accounting", "sales", "inventory", "procurement"))
    assert template["financial_truth_owner"] == "Neutral Finance"
    assert template["provider_execution_owner"] == "product_integration_adapter"


def test_provider_connector_is_typed_nonfinancial_and_finality_aware():
    connector = _json(CONTRACTS / "examples/neutral_payment_provider_connector.json")
    assert connector["financial_truth"] == "NONE"
    assert connector["settlement_owner"] == "Neutral Finance"
    assert connector["external_reference_lookup"] is True
    assert set(connector["finality_policy"].values()) == {"submitted", "pending", "failed", "ambiguous", "provider_final"}
    assert connector["raw_payload_policy"] == "sanitized_or_encrypted_only"
    assert "blind" not in connector["ambiguous_outcome_policy"].lower()


def test_two_templates_are_materially_different_without_source_forks():
    payments = _json(CONTRACTS / "examples/payments_only_template.json")
    field = _json(CONTRACTS / "examples/neutral_field_service_template.json")
    assert payments["industry_semantic_ref"] != field["industry_semantic_ref"]
    assert payments["operating_model_semantic_ref"] != field["operating_model_semantic_ref"]
    assert payments["configuration_defaults"] != field["configuration_defaults"]
    assert payments["xa"] != field["xa"]
    assert payments["finance_kernel_required"] is True and field["finance_kernel_required"] is True


def test_xa_contract_is_consumed_not_redefined():
    xa = _json(ROOT / "contracts/experience/v1/xa_frontend_experience_contract.json")
    readiness = next(row for row in xa["contracts"] if row["id"] == "template_composition_readiness")
    assert readiness["rule"] == "consume_future_PK_composition_without_implementing_PK"
    assert set(readiness["required"]) == {"template_profile_reference", "terminology", "layout_regions", "module_slots"}


def test_dependency_authority_uses_canonical_git_text_fingerprints():
    contract = _json(CONTRACTS / "pk_aggregate_conformance_freeze.json")
    assert contract["dependency_fingerprint_mode"] == "sha256_git_canonical_lf"
    for relative, expected in contract["dependency_fingerprints"].items():
        path = ROOT / relative
        assert _canonical(path) == expected
        # Equivalent LF/CRLF checkout bytes must resolve to the same dependency truth.
        logical = path.read_bytes().replace(b"\r\n", b"\n")
        crlf = logical.replace(b"\n", b"\r\n")
        normalized = crlf.replace(b"\r\n", b"\n")
        assert hashlib.sha256(normalized).hexdigest() == expected


def test_component_and_aggregate_release_integrity():
    for name in ("pk0123_release_manifest.json", "pk456_release_manifest.json", "pk_aggregate_release_manifest.json"):
        manifest = _json(CONTRACTS / name)
        for item in manifest["artifacts"]:
            path = ROOT / item["path"]
            assert path.is_file(), item["path"]
            assert _canonical(path) == item["sha256"], item["path"]


def test_static_aggregate_verifier_passes():
    from scripts.verify_pk_aggregate_conformance_freeze import static_verify
    result = static_verify()
    assert result["status"] == "PASS"
    assert result["pk0_pk6_coverage"] == "PASS"
    assert result["finance"] == "UNCHANGED"
    assert result["shared_operations"] == "UNCHANGED"
    assert result["pa_readiness"] == "PASS"
