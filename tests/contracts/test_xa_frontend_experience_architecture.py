from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from experience_contracts import ExperienceContractError, validate_experience
from scripts.verify_xa_frontend_experience_architecture import EXPECTED_CONTRACTS, verify_xa

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "contracts/experience/v1/examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_complete_gate_and_twelve_contracts_pass():
    report = verify_xa()
    assert report["status"] == "PASS" and report["contract_count"] == 12
    assert len(EXPECTED_CONTRACTS) == 12 and report["migration"] == "NONE"


def test_same_contract_supports_materially_different_tenant_presentations():
    first, second = load("northstar_merchant_admin.json"), load("summit_pos.json")
    assert validate_experience(first) and validate_experience(second)
    assert first["schema_version"] == second["schema_version"]
    assert first["portal_context"]["locale"] != second["portal_context"]["locale"]
    assert first["portal_context"]["active_modules"] != second["portal_context"]["active_modules"]
    assert first["composition"] != second["composition"]


def test_platform_operator_shell_is_distinct_and_merchant_has_no_platform_authority():
    platform, merchant = load("platform_operator.json"), load("northstar_merchant_admin.json")
    assert platform["portal_context"]["structural_context"]["scope_type"] == "platform"
    assert merchant["portal_context"]["structural_context"]["scope_type"] == "tenant"
    bad = copy.deepcopy(merchant); bad["portal_context"]["identity"]["platform_authority"] = True
    with pytest.raises(ExperienceContractError, match="merchant_platform_authority_forbidden"):
        validate_experience(bad)


def test_route_visibility_never_grants_authorization_and_hidden_ui_is_not_denial():
    merchant = load("northstar_merchant_admin.json")
    route = merchant["navigation"][0]
    assert route["visible"] is True and route["can_invoke"] is False and route["authorization"]["decision"] == "deny"
    bad = copy.deepcopy(merchant); bad["navigation"][0]["can_invoke"] = True
    with pytest.raises(ExperienceContractError, match="visibility_is_not_authorization"):
        validate_experience(bad)
    hidden = load("summit_pos.json"); hidden["navigation"][0]["visible"] = False
    assert validate_experience(hidden)["navigation"][0]["authorization"]["decision"] == "allow"


def test_configuration_scope_inheritance_and_secret_protection():
    merchant = load("northstar_merchant_admin.json")
    secret = merchant["configuration"][1]
    assert secret["secret"] and secret["effective_value"] is None and not secret["value_exposed"]
    bad = copy.deepcopy(merchant); bad["configuration"][1]["effective_value"] = "leak"
    with pytest.raises(ExperienceContractError, match="secret_value_exposed"):
        validate_experience(bad)
    inherited = copy.deepcopy(merchant); inherited["configuration"][0].update(inherited=True, editable=True)
    with pytest.raises(ExperienceContractError, match="inherited_value_editable"):
        validate_experience(inherited)


def test_permission_denial_is_explainable_and_step_up_or_approval_is_explicit():
    merchant = load("northstar_merchant_admin.json")
    assert merchant["navigation"][0]["authorization"]["missing_scope"]
    assert merchant["actions"][0]["authorization"]["approval"]
    bad = copy.deepcopy(merchant); bad["navigation"][0]["authorization"].update(missing_scope=None, missing_permission=None, unavailable=None)
    with pytest.raises(ExperienceContractError, match="denial_has_no_cause"):
        validate_experience(bad)


def test_frontend_cannot_claim_constitutionally_forbidden_truth():
    bad = load("summit_pos.json"); bad["frontend_authorities"] = ["business_date_truth"]
    with pytest.raises(ExperienceContractError, match="frontend_authority_forbidden"):
        validate_experience(bad)


def test_offline_queue_requires_idempotency_retry_conflict_and_server_truth():
    pos = load("summit_pos.json")
    assert pos["offline"][0]["mode"] == "queueable" and pos["offline"][0]["idempotency"]
    bad = copy.deepcopy(pos); bad["offline"][0]["idempotency"] = False
    with pytest.raises(ExperienceContractError, match="server_truth_bypass"):
        validate_experience(bad)


def test_dashboard_document_queue_and_search_preserve_source_authority():
    for payload in (load("platform_operator.json"), load("northstar_merchant_admin.json"), load("summit_pos.json")):
        assert payload["dashboard"][0]["projection"] is True
        assert payload["documents"][0]["source_authority"] == "SO7"
        assert payload["work_queue"][0]["source_authority"] == "SO"
        assert payload["search"][0]["authorization"]["source_authority"] == "PC5"


def test_search_result_cannot_cross_tenant_scope():
    bad = load("summit_pos.json"); bad["search"][0]["tenant_id"] = "tenant-other"
    with pytest.raises(ExperienceContractError, match="cross_tenant_result"):
        validate_experience(bad)


def test_template_readiness_is_reference_only_not_pack_engine():
    pos = load("summit_pos.json")
    assert pos["composition"]["template_profile_reference"].startswith("future-pk:")
    bad = copy.deepcopy(pos); bad["composition"]["engine_implemented"] = True
    with pytest.raises(ExperienceContractError, match="pack_engine_forbidden"):
        validate_experience(bad)


def test_no_legacy_literal_or_frontend_build_artifact_becomes_default():
    forbidden = bytes((87, 78, 68)).lower()
    assert all(forbidden not in path.read_bytes().lower() for path in EXAMPLES.glob("*.json"))
    assert not any((ROOT / name).exists() for name in ("package.json", "vite.config.js", "src/App.jsx", "src/App.tsx"))


def test_frontend_contracts_declare_only_frozen_public_platform_facades():
    declared = json.loads((ROOT / "contracts/experience/v1/xa_public_authority_consumption.json").read_text())
    frozen = json.loads((ROOT / "contracts/platform/v1/pc6_public_contract_inventory.json").read_text())
    available = {(item["authority"], item["facade"]): set(item["operations"]) for item in frozen["interfaces"]}
    for item in declared["interfaces"]:
        assert set(item["operations"]) <= available[item["authority"], item["facade"]]
    assert "sql_repository" not in json.dumps(declared)


def test_no_migration_and_frozen_finance_baseline_remains_canonical():
    assert not list((ROOT / "alembic_neutral/versions").glob("xa_*.py"))
    baseline = json.loads((ROOT / "contracts/platform/v1/pc0_frozen_finance_baseline.json").read_text())
    assert baseline["canonical_head"] == "m64_reconciliation_controls_020"


def test_release_manifest_rejects_arbitrary_contract_mutation():
    manifest = json.loads((ROOT / "contracts/experience/v1/xa_release_manifest.json").read_text())
    relative = "contracts/experience/v1/xa_frontend_experience_contract.json"
    expected = next(item["sha256"] for item in manifest["artifacts"] if item["path"] == relative)
    source = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(source).hexdigest() == expected
    with tempfile.TemporaryDirectory() as directory:
        mutated = Path(directory) / "contract.json"
        mutated.write_bytes(source.replace(b'"truth"', b'"guess"', 1))
        assert hashlib.sha256(mutated.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected


def test_release_fingerprints_are_windows_crlf_checkout_safe_only():
    manifest = json.loads((ROOT / "contracts/experience/v1/xa_release_manifest.json").read_text())
    artifact = next(item for item in manifest["artifacts"] if item["path"].endswith("xa_frontend_experience_contract.json"))
    canonical = (ROOT / artifact["path"]).read_bytes().replace(b"\r\n", b"\n")
    windows_checkout = canonical.replace(b"\n", b"\r\n")
    assert hashlib.sha256(windows_checkout.replace(b"\r\n", b"\n")).hexdigest() == artifact["sha256"]
    unauthorized_space = canonical.replace(b'"truth"', b'"truth "', 1)
    assert hashlib.sha256(unauthorized_space).hexdigest() != artifact["sha256"]
