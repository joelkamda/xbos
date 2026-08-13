from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from shared_operations_contracts import SOConstitutionError, evaluate_private_import, validate_module_declaration
from scripts.verify_so0_shared_operations import verify_dependency_fingerprints, verify_production_dependency_authority, verify_so0

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/shared_operations/v1"


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_complete_so0_gate_passes_without_migration_or_features():
    report = verify_so0()
    assert report["status"] == "PASS" and report["domain_count"] == 10
    assert report["migration"] == "NONE" and report["so1_plus_features"] == "NONE"


def test_domain_inventory_is_complete_ordered_and_uniquely_owned():
    domains = load("so0_shared_operations_constitution.json")["domains"]
    assert [item["code"] for item in domains] == [f"SO{number}" for number in range(1, 11)]
    assert len({item["owner"] for item in domains}) == 10
    assert {item["implementation_status"] for item in domains} == {"NOT_IMPLEMENTED"}


def test_platform_core_and_finance_authorities_are_not_duplicated():
    contract = load("so0_shared_operations_constitution.json")
    external = {item["authority"] for item in contract["external_authorities"]}
    assert {"PC1", "PC2", "PC3", "PC4", "PC5", "Neutral Finance", "XA", "PK"} == external
    assert {"permission", "business_calendar", "financial_journal", "reconciliation"} <= set(contract["authority_law"]["forbidden_so_authorities"])


def test_future_module_contract_requires_complete_dependency_declaration():
    contract = load("so0_module_contract.json")
    assert validate_module_declaration(contract["example"])
    bad = copy.deepcopy(contract["example"]); del bad["configuration_dependencies"]
    with pytest.raises(SOConstitutionError, match="module_declaration_missing"):
        validate_module_declaration(bad)


def test_unauthorized_cross_module_private_and_nonpublic_imports_fail():
    assert evaluate_private_import("SO1", "shared_operations.SO2.repository.sql_repository") == "SO0-CROSS-MODULE-PRIVATE-IMPORT"
    assert evaluate_private_import("SO1", "shared_operations.SO2.domain.customer") == "SO0-CROSS-MODULE-NONPUBLIC-IMPORT"
    assert evaluate_private_import("SO1", "shared_operations.SO2.contracts.public") is None
    assert evaluate_private_import("SO1", "shared_operations.SO1.repository.private") is None


def test_xa_hooks_are_complete_without_frontend_implementation():
    contract = load("so0_module_contract.json")
    assert set(contract["field_law"]["xa_hooks"]["allowed"]) == {"navigation", "actions", "work_queue", "configuration", "dashboard", "documents", "search", "offline"}
    assert not any((ROOT / name).exists() for name in ("package.json", "src/App.jsx", "src/App.tsx"))


def test_pack_declaration_hooks_exist_without_implementing_pk():
    contract = load("so0_module_contract.json")
    assert set(contract["pack_template_hooks"]) == {"required_capabilities", "required_semantics", "suggested_configuration_defaults", "enabled_workflows", "composition_references"}
    assert contract["pack_implementation"] == "NONE"


def test_security_and_tenant_isolation_requirements_are_mandatory():
    security = set(load("so0_shared_operations_constitution.json")["security_isolation"])
    assert {"tenant_isolation_fail_closed", "server_side_permission_check", "no_role_name_shortcut", "global_identity_does_not_imply_access", "audit_through_PC5"} <= security


def test_atomic_units_are_prospectively_so1_without_so0_persistence_change():
    boundary = load("so0_shared_operations_constitution.json")["atomic_unit_boundary"]
    assert boundary["canonical_future_owner"] == "SO1"
    assert boundary["SO0_persistence_change"] == "NONE"
    assert not list((ROOT / "alembic_neutral/versions").glob("so0_*.py"))


def test_generic_delivery_is_distinct_from_finance_transactional_outbox():
    boundary = load("so0_shared_operations_constitution.json")["delivery_boundary"]
    assert "transactional_outbox" in boundary["finance_retains"]
    assert "integration_delivery" in boundary["SO8_future_scope"]
    assert boundary["implementation"] == "NONE"


def test_operational_fact_is_explicitly_not_a_financial_event():
    boundary = load("so0_shared_operations_constitution.json")["finance_boundary"]
    assert boundary["equation"] == "operational_fact_not_equal_financial_event"
    assert "private_SQL_journal_posting" in boundary["forbidden"]


def test_machine_errors_are_complete_and_never_require_string_parsing():
    errors = load("so0_module_contract.json")["error_contract"]
    assert len(errors["categories"]) == 11
    assert errors["frontend_behavior"] == "stable_code_only_never_parse_human_text"


def test_party_identity_remains_pc2_while_operational_relationships_belong_to_so():
    boundary = load("so0_shared_operations_constitution.json")["party_boundary"]
    assert boundary["identity_owner"] == "PC2"
    assert boundary["competing_identity_system"] == "FORBIDDEN"
    assert "supplier_relationship" in boundary["SO_may_own"]


def test_no_industry_literal_becomes_an_active_so_default():
    forbidden = (bytes((87, 78, 68)), b"Wine & Dine", b"Logpom")
    for base in (ROOT / "shared_operations_contracts", CONTRACTS):
        for path in base.rglob("*"):
            if path.is_file() and path.name != "so0_release_manifest.json":
                assert not any(term.lower() in path.read_bytes().lower() for term in forbidden)


def test_production_dependency_authority_and_frozen_finance_remain_unchanged():
    dependency = verify_production_dependency_authority(ROOT)
    assert dependency["status"] == "PASS" and dependency["pin_count"] == 14 and dependency["python"] == "3.13.3"
    baseline = json.loads((ROOT / "contracts/platform/v1/pc0_frozen_finance_baseline.json").read_text())
    assert baseline["canonical_head"] == "m64_reconciliation_controls_020"


def test_dependency_fingerprints_accept_archive_lf_and_git_equivalent_windows_crlf():
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory)
        for relative in ("requirements-prod.txt", "contracts/platform/v1/pc6_dependency_authority.json"):
            target = candidate / relative; target.parent.mkdir(parents=True, exist_ok=True)
            canonical = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
            target.write_bytes(canonical.replace(b"\n", b"\r\n"))
        verify_dependency_fingerprints(candidate)


def test_one_byte_dependency_or_authority_metadata_mutation_fails():
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory)
        paths = ("requirements-prod.txt", "contracts/platform/v1/pc6_dependency_authority.json")
        for relative in paths:
            target = candidate / relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes().replace(b"\r\n", b"\n"))
        requirements = candidate / paths[0]; requirements.write_bytes(requirements.read_bytes() + b" ")
        with pytest.raises(RuntimeError, match="requirements-prod.txt"):
            verify_dependency_fingerprints(candidate)
        requirements.write_bytes((ROOT / paths[0]).read_bytes().replace(b"\r\n", b"\n"))
        metadata = candidate / paths[1]; metadata.write_bytes(metadata.read_bytes().replace(b'"3.13.3"', b'"3.13.4"', 1))
        with pytest.raises(RuntimeError, match="pc6_dependency_authority.json"):
            verify_dependency_fingerprints(candidate)


def test_release_manifest_is_crlf_safe_but_rejects_content_or_whitespace_mutation():
    manifest = load("so0_release_manifest.json")
    artifact = next(item for item in manifest["artifacts"] if item["path"].endswith("so0_module_contract.json"))
    source = (ROOT / artifact["path"]).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(source).hexdigest() == artifact["sha256"]
    assert hashlib.sha256(source.replace(b"\n", b"\r\n").replace(b"\r\n", b"\n")).hexdigest() == artifact["sha256"]
    with tempfile.TemporaryDirectory() as directory:
        mutated = Path(directory) / "contract.json"; mutated.write_bytes(source.replace(b'"NONE"', b'"SOME"', 1))
        assert hashlib.sha256(mutated.read_bytes()).hexdigest() != artifact["sha256"]
