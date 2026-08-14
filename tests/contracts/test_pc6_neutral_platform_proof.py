from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import ast
from uuid import UUID

import pytest

from core.platform.architecture_contract import PC0ArchitectureError, _validate_modules, validate_frozen_module_descendants, validate_pc0
from core.platform.neutral_proof import (
    NeutralProofError, bootstrap_profile, deterministic_export, load_profile,
    restore_export, validate_export, validate_profile,
)
from core.platform.neutral_proof.dependency_authority import parse_exact_pins, verify_dependency_authority
from core.platform.neutral_proof.leakage import scan_wnd_leakage


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "profiles/platform_core/pc6_second_tenant.json"
CONTRACTS = ROOT / "contracts/platform/v1"

FROZEN_PC6_MODULES = {
    "architecture": ("PC0", "platform_governance"),
    "structure": ("PC1", "platform_authority"),
    "party": ("PC2", "platform_authority"),
    "semantics": ("PC3", "platform_authority"),
    "operating_context": ("PC4", "platform_authority"),
    "security_authority": ("PC5", "platform_authority"),
    "neutral_proof": ("PC6", "platform_proof"),
    "application": ("PC0", "platform_composition"),
    "composition": ("PC0", "platform_composition"),
    "persistence": ("Neutral Finance / canonical persistence", "frozen_foundation"),
    "tenancy": ("PC1", "legacy_compatibility"),
    "identity": ("PC5", "legacy_compatibility"),
    "taxonomy": ("PC3", "adopted_compatibility"),
    "catalog": ("SO0/SO1", "legacy_operational"),
    "inventory": ("SO3", "legacy_operational"),
    "orders": ("Restaurant Pack", "legacy_industry"),
    "sales": ("Restaurant Pack / SO1", "legacy_industry"),
    "legacy_accounting": ("R6 retirement / Neutral Finance target", "legacy_financial"),
    "legacy_payments": ("R6 retirement / Neutral Finance target", "legacy_financial"),
    "reports": ("SO9 / Neutral Finance by report authority", "legacy_operational"),
    "commerce": ("SO1", "legacy_operational"),
    "finance": ("Neutral Finance", "frozen_authority"),
    "xafpay": ("Provider adapter / Neutral Finance interface", "adapter"),
    "shared": ("PC0 boundary pending named downstream owners", "legacy_shared"),
}


def _json(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _assert_frozen_pc6_module_coverage(module_map, authorities=None, migrations=None):
    validate_frozen_module_descendants(
        FROZEN_PC6_MODULES,
        module_map,
        authorities or _json("pc0_data_authority_register.json"),
        migrations or _json("pc0_reference_authority_migration_register.json"),
    )


class Facade:
    def __init__(self, kind):
        self.kind = kind; self.calls = []; self.next_id = 1
    def _record(self, name, value=None):
        self.calls.append((name, value)); self.next_id += 1
    def provision(self, command):
        self._record("provision", command)
        tenant=SimpleNamespace(id=41,code=command.tenant_code);organization=SimpleNamespace(id=42);legal=SimpleNamespace(id=43);location=SimpleNamespace(id=44)
        return SimpleNamespace(tenant=tenant,organization_unit=organization,legal_entity=legal,location=location)
    def create_organization(self, command):
        self._record("create_organization",command);return SimpleNamespace(party=SimpleNamespace(id=51,public_id=UUID(int=51)))
    def create_person(self, command):
        self._record("create_person",command);return SimpleNamespace(party=SimpleNamespace(id=52,public_id=UUID(int=52)))
    def link_legal_entity(self, command):self._record("link_legal_entity",command);return command.legal_entity_id,command.organization_party_id
    def create_relationship(self, command):self._record("create_relationship",command);return SimpleNamespace(id=53)
    def create_namespace(self, command):self._record("create_namespace",command);return command
    def create_concept(self, command):self._record("create_concept",command);return command
    def create_version(self, command):self._record("create_version",command);return command
    def define(self, command):self._record("define",command);return command
    def set_value(self, command):self._record("set_value",command);return command
    def register_module(self, command):self._record("register_module",command);return command
    def set_module_enablement(self, command):self._record("set_module_enablement",command);return command
    def grant_entitlement(self, command):self._record("grant_entitlement",command);return command
    def set_feature_flag(self, command):self._record("set_feature_flag",command);return command
    def register_calendar(self, command):self._record("register_calendar",command);return command.calendar
    def set_localization(self, command):self._record("set_localization",command);return command.profile
    def create_identity(self, **values):self._record("create_identity",values);return SimpleNamespace(id=61,public_id=UUID(int=61))
    def add_membership(self, **values):self._record("add_membership",values);return SimpleNamespace(id=62)
    def register_permission(self, **values):self._record("register_permission",values);return values["definition"]
    def create_role(self, **values):self._record("create_role",values);return 63
    def assign_role(self, **values):self._record("assign_role",values);return 64


def _facades():
    return {name:Facade(name) for name in ("structure","party","semantics","operating_context","security")}


def test_pc6_contract_covers_exact_twelve_obligations_and_no_migration():
    contract=_json("pc6_neutral_platform_proof.json")
    assert contract["scope"]==[f"PC6.{number}" for number in range(1,13)]
    assert contract["migration"]=="NONE"
    assert contract["previous_head"]==contract["accepted_head"]=="pc5_identity_policy_audit_025"
    assert not list((ROOT/"alembic_neutral/versions").glob("pc6_*.py"))
    assert len(contract["isolation_attacks"])==15 and contract["performance_bounds_seconds"]["complete_disposable_proof"]==120


def test_second_tenant_profile_is_deterministic_materially_different_and_secret_free():
    profile=load_profile(PROFILE_PATH)
    assert profile==load_profile(PROFILE_PATH) and len(profile.sha256)==64
    assert profile.payload["tenant"]=={"code":"NORTHSTAR","name":"Northstar Community Services Cooperative","country_code":"CA","currency":"CAD","locale":"en-CA","timezone":"America/Toronto"}
    assert profile.payload["structure"]["primary_location_kind"]=="virtual"
    assert profile.payload["calendar"]["business_day_boundary"]=="04:30:00"
    assert len(profile.payload["proof_dimensions"])>=6
    forbidden=("password","token","api_key","secret","credential")
    source=profile.canonical_bytes.lower()
    assert not any(item.encode() in source for item in forbidden)


def test_profile_rejects_secret_material_wnd_clone_and_hidden_defaults():
    payload=json.loads(PROFILE_PATH.read_text())
    with pytest.raises(NeutralProofError,match="credential_or_secret_field_forbidden"):
        validate_profile({**payload,"api_key":"not-allowed"})
    with pytest.raises(NeutralProofError,match="wnd_profile_forbidden"):
        validate_profile({**payload,"tenant":{**payload["tenant"],"code":"WND"}})
    with pytest.raises(NeutralProofError,match="tenant_calendar_not_independent"):
        validate_profile({**payload,"calendar":{**payload["calendar"],"business_day_boundary":"08:00:00"}})


def test_bootstrap_uses_only_public_facades_and_is_profile_deterministic():
    profile=load_profile(PROFILE_PATH);facades=_facades();result=bootstrap_profile(profile,facades)
    assert result["tenant_code"]=="NORTHSTAR" and result["profile_sha256"]==profile.sha256
    assert {name for name,_ in facades["structure"].calls}=={"provision"}
    assert {name for name,_ in facades["party"].calls}=={"create_organization","create_person","link_legal_entity","create_relationship"}
    assert {name for name,_ in facades["semantics"].calls}=={"create_namespace","create_concept","create_version"}
    assert {"define","set_value","register_calendar","set_localization","register_module","set_module_enablement","grant_entitlement","set_feature_flag"}<={name for name,_ in facades["operating_context"].calls}
    assert {"create_identity","add_membership","register_permission","create_role","assign_role"}=={name for name,_ in facades["security"].calls}
    with pytest.raises(NeutralProofError,match="public_authority_set_incomplete_or_private"):
        bootstrap_profile(profile,{**facades,"sql_repository":object()})


def test_export_is_deterministic_classified_and_restore_uses_stable_profile_identity():
    profile=load_profile(PROFILE_PATH)
    state={name:{"public_reference":f"{name}:northstar"} for name in ("structure","party","semantics","operating_context","identity")}
    first=deterministic_export(profile,state);assert first==deterministic_export(profile,state)
    payload=validate_export(first)
    assert payload["classification"]["tenant_profile"]=="PORTABLE"
    assert payload["classification"]["credentials_and_secrets"]=="SECRET"
    assert payload["classification"]["financial_data"]==payload["classification"]["sessions"]=="EXCLUDED"
    restored=restore_export(first,profile,lambda item:{"tenant_code":item.payload["tenant"]["code"],"profile_sha256":item.sha256,"tenant_id":999})
    assert restored["tenant_code"]=="NORTHSTAR" and restored["tenant_id"]==999
    with pytest.raises(NeutralProofError,match="profile_export_identity_mismatch"):
        restore_export(first,replace(profile,sha256="0"*64),lambda item:{})


def test_dependency_authority_has_exact_operator_pins_and_complete_import_mapping(tmp_path):
    contract=_json("pc6_dependency_authority.json")
    report=verify_dependency_authority(ROOT,contract)
    assert report["status"]=="PASS" and report["pin_count"]==14 and report["python"]=="3.13.3"
    pins=parse_exact_pins(ROOT/"requirements-prod.txt")
    assert pins["sqlalchemy"]=="2.0.41" and "pytest" not in pins and "pandas" not in pins
    bad=tmp_path/"requirements-prod.txt";bad.write_text("fastapi>=0.115.12\n")
    with pytest.raises(ValueError,match="not_exactly_pinned"):parse_exact_pins(bad)


def test_wnd_leakage_scan_distinguishes_exact_proof_guard_from_runtime_authority(tmp_path):
    policy=_json("pc6_wnd_leakage_policy.json")
    assert scan_wnd_leakage(ROOT,policy)["status"]=="PASS"
    candidate=tmp_path/"candidate";(candidate/"core/platform").mkdir(parents=True)
    (candidate/"core/platform/bad.py").write_text("DEFAULT_TENANT = 'WND'\n")
    for path in ("main.py","app.py","startup.py","database.py","settings.py"):(candidate/path).write_text("")
    with pytest.raises(ValueError,match="active_wnd_literal_leakage"):scan_wnd_leakage(candidate,{**policy,"allowed_active_references":[]})


def test_public_contract_inventory_exposes_facades_not_private_sql():
    inventory=_json("pc6_public_contract_inventory.json")
    assert {item["authority"] for item in inventory["interfaces"]}=={"PC1","PC2","PC3","PC4","PC5"}
    serialized=json.dumps(inventory)
    assert "sql_repository" not in serialized and "private table identity" in serialized


def test_pc0_architecture_covers_pc6_proof_module_and_stays_green():
    report=validate_pc0(ROOT)
    module_map=_json("pc0_module_map.json")
    _assert_frozen_pc6_module_coverage(module_map)
    codes={item["code"] for item in module_map["modules"]}
    assert report["status"]=="PASS"
    assert report["module_count"]==len(codes)>=len(FROZEN_PC6_MODULES)
    assert codes-set(FROZEN_PC6_MODULES)>={"crm_relationships"}


def test_pc6_frozen_module_inventory_allows_future_descendants_without_count_edits():
    module_map=deepcopy(_json("pc0_module_map.json"))
    policy=deepcopy(_json("pc0_dependency_policy.json"))
    interfaces=deepcopy(_json("pc0_public_private_interfaces.json"))
    module_map["modules"].append({"code":"future_shared_operations","owner":"SO3","kind":"shared_operations_authority","source_roots":["shared_operations/future"]})
    policy["allowed_directions"]["future_shared_operations"]=[]
    interfaces["interfaces"].append({"module":"future_shared_operations","public":[],"private":[]})
    _validate_modules(module_map,policy,interfaces)
    _assert_frozen_pc6_module_coverage(module_map)


def test_pc6_frozen_module_removal_or_conflicting_ownership_fails():
    module_map=deepcopy(_json("pc0_module_map.json"))
    module_map["modules"]=[item for item in module_map["modules"] if item["code"]!="neutral_proof"]
    with pytest.raises(PC0ArchitectureError,match="PC0-FROZEN-MODULE-MISSING"):
        _assert_frozen_pc6_module_coverage(module_map)

    module_map=deepcopy(_json("pc0_module_map.json"))
    conflicting={**module_map["modules"][0],"owner":"UNAUTHORIZED"}
    module_map["modules"].append(conflicting)
    with pytest.raises(PC0ArchitectureError,match="PC0-MODULE-MAP"):
        _validate_modules(module_map,_json("pc0_dependency_policy.json"),_json("pc0_public_private_interfaces.json"))


def test_so3_inventory_promotion_requires_exact_governed_registration():
    module_map=deepcopy(_json("pc0_module_map.json"))
    migrations=deepcopy(_json("pc0_reference_authority_migration_register.json"))
    _assert_frozen_pc6_module_coverage(module_map,migrations=migrations)
    migrations["entries"]=[item for item in migrations["entries"] if item.get("module_code")!="inventory"]
    with pytest.raises(PC0ArchitectureError,match="unregistered promotion=inventory"):
        _assert_frozen_pc6_module_coverage(module_map,migrations=migrations)


def test_unrelated_reassignment_fails_but_future_registered_promotion_passes():
    module_map=deepcopy(_json("pc0_module_map.json")); authorities=deepcopy(_json("pc0_data_authority_register.json")); migrations=deepcopy(_json("pc0_reference_authority_migration_register.json"))
    inventory=next(item for item in module_map["modules"] if item["code"]=="inventory")
    inventory["owner"]="UNRELATED"
    with pytest.raises(PC0ArchitectureError,match="authority transition mismatch=inventory"):
        _assert_frozen_pc6_module_coverage(module_map,authorities,migrations)

    module_map=deepcopy(_json("pc0_module_map.json")); catalog=next(item for item in module_map["modules"] if item["code"]=="catalog")
    catalog.update(owner="SO4",kind="shared_operations_authority")
    authorities["authorities"].append({"code":"catalog_fulfilment","module":"catalog","owner":"SO4","current_store":"future","boundary":"future governed authority"})
    migrations["entries"].append({"reference":"future_catalog","module_code":"catalog","previous_module_owner":"SO0/SO1","previous_module_kind":"legacy_operational","target_module_owner":"SO4","target_module_kind":"shared_operations_authority","target_data_authority":"catalog_fulfilment","current_authority":"legacy catalog","target_authority":"SO4 catalog authority","compatibility_path":"explicit bridge","retirement_owner":"SO4","retirement_milestone":"SO4 exit"})
    _assert_frozen_pc6_module_coverage(module_map,authorities,migrations)


def test_canonical_entrypoint_and_finance_freeze_remain_unchanged():
    composition=_json("pc0_composition_baseline.json")
    assert composition["facts"]["canonical_entrypoint"]=="main:app"
    assert composition["facts"]["compatibility_entrypoint"]=="app:app"
    assert composition["facts"]["production_dependency_authority"]=="requirements-prod.txt"
    baseline=_json("pc0_frozen_finance_baseline.json")
    assert baseline["canonical_head"]==baseline["lineage"][-1]=="m64_reconciliation_controls_020"


def test_active_settings_and_profile_have_no_default_credentials_or_secrets():
    settings=(ROOT/"settings.py").read_text(encoding="utf-8")
    assert "JWT_SECRET: str\n" in settings and "DATABASE_URL: str\n" in settings
    assert "supersecretkey_change_me" not in settings and "Becky@" not in settings
    example=(ROOT/".env.example").read_text(encoding="utf-8").splitlines()
    assert all(not line.split("=",1)[1] for line in example if "=" in line)
    validate_profile(json.loads(PROFILE_PATH.read_text()))


def test_canonical_application_factory_has_no_implicit_schema_or_legacy_rbac_writes():
    source=(ROOT/"startup.py").read_text(encoding="utf-8")
    tree=ast.parse(source)
    factory=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="create_app")
    calls={node.func.id for node in ast.walk(factory) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
    assert {"validate_permissions","register_middlewares","register_routes"}<=calls
    assert not {"init_database","seed_rbac"}&calls


def test_canonical_permission_validation_is_quiet_and_ascii_compatible():
    tree=ast.parse((ROOT/"startup.py").read_text(encoding="utf-8"))
    functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    for name in ("validate_permissions","create_app"):
        function=functions[name]
        assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="print" for node in ast.walk(function))
        assert all(not isinstance(node,ast.Constant) or not isinstance(node.value,str) or node.value.isascii() for node in ast.walk(function))
    assert any(isinstance(node,ast.Return) for node in functions["validate_permissions"].body)


def test_entrypoint_failure_diagnostic_preserves_captured_stdout_and_stderr():
    verifier=(ROOT/"scripts/verify_pc6_neutral_platform.py").read_text(encoding="utf-8")
    assert "returncode={entrypoint.returncode}" in verifier
    assert "STDOUT:\\n{entrypoint.stdout}" in verifier
    assert "STDERR:\\n{entrypoint.stderr}" in verifier
    assert "entrypoint_roles_after != entrypoint_roles_before" in verifier
    assert "encoding='ascii',errors='strict'" in verifier
