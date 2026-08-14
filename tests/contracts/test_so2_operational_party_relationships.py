from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts.verify_so2_operational_party_relationships import HEAD, PREVIOUS, _development_action, _focused_test_paths, _verify_snapshot
from shared_operations.so2 import (
    ChangeRelationshipStatus,
    ClassifyRelationship,
    EstablishRelationship,
    RelationshipStatus,
    SO2Authority,
    SO2AuthorityError,
    UpdateRelationshipPreferences,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/shared_operations/v1"
NOW = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


class MemoryRepository:
    def __init__(self):
        self.items = {}
        self.events = {}
        self.next_id = 1

    def establish(self, command, party_id, public_id, fingerprint):
        if any(item.tenant_id == command.tenant_id and item.party_public_id == command.party_public_id and item.relationship_type_code == command.relationship_type_code for item in self.items.values()):
            raise SO2AuthorityError("SO2_RELATIONSHIP_CONFLICT", "conflict", "duplicate")
        from shared_operations.so2.contracts import OperationalRelationship, RelationshipHistory
        item = OperationalRelationship(self.next_id, public_id, command.tenant_id, command.party_public_id, command.relationship_type_code, command.initial_status, command.source_code, command.purpose, command.preferences or {}, command.organization_unit_id, command.location_id, command.effective_from, None, 1)
        self.next_id += 1
        self.items[(command.tenant_id, public_id)] = item
        self.events[(command.tenant_id, public_id)] = [RelationshipHistory(1, None, command.initial_status, "established", command.effective_from)]
        return item

    def relationship(self, tenant_id, public_id):
        return self.items.get((tenant_id, public_id))

    def list(self, tenant_id, party_public_id=None, relationship_type_code=None):
        return tuple(item for (tenant, _), item in self.items.items() if tenant == tenant_id and (party_public_id is None or item.party_public_id == party_public_id) and (relationship_type_code is None or item.relationship_type_code == relationship_type_code))

    def change_status(self, command, fingerprint):
        item = self.relationship(command.tenant_id, command.relationship_public_id)
        if item is None or item.row_version != command.expected_version:
            return None
        from shared_operations.so2.contracts import RelationshipHistory
        result = replace(item, status=command.to_status, effective_to=command.occurred_at if command.to_status is RelationshipStatus.ENDED else None, row_version=item.row_version + 1)
        self.items[(command.tenant_id, command.relationship_public_id)] = result
        history = self.events[(command.tenant_id, command.relationship_public_id)]
        history.append(RelationshipHistory(len(history) + 1, item.status, command.to_status, command.reason_code, command.occurred_at))
        return result

    def update_preferences(self, command, fingerprint):
        item = self.relationship(command.tenant_id, command.relationship_public_id)
        if item is None or item.row_version != command.expected_version:
            return None
        result = replace(item, preferences=command.preferences, row_version=item.row_version + 1)
        self.items[(command.tenant_id, command.relationship_public_id)] = result
        return result

    def history(self, tenant_id, public_id):
        return tuple(self.events.get((tenant_id, public_id), ()))

    def export(self, tenant_id):
        return {"tenant_id": tenant_id, "relationships": [str(item.public_id) for item in self.list(tenant_id)]}


def authority(*, authorized=True, parties=None, semantics=None):
    parties = parties or {(1, UUID(int=100)): SimpleNamespace(id=10, tenant_id=1, public_id=UUID(int=100)), (2, UUID(int=200)): SimpleNamespace(id=20, tenant_id=2, public_id=UUID(int=200))}
    ids = iter(UUID(int=value) for value in range(1, 100))
    observed = semantics if semantics is not None else []
    return SO2Authority(MemoryRepository(), party_resolver=lambda tenant, public_id: parties.get((tenant, public_id)), authorize=lambda *args: authorized, validate_scope=lambda tenant, scope, scope_id: scope_id != 999, semantic_assigner=lambda payload: observed.append(payload) or payload, public_id_factory=lambda: next(ids)), observed


def establish(service, key="one", tenant=1, party=UUID(int=100), relationship_type="customer", status=RelationshipStatus.PROSPECT):
    return service.establish(EstablishRelationship(key, tenant, party, relationship_type, status, NOW))


def test_party_identity_is_reused_and_no_customer_or_supplier_identity_table_exists():
    service, _ = authority()
    item = establish(service)
    assert item.party_public_id == UUID(int=100)
    sql = (ROOT / "alembic_neutral/sql/so2_operational_party_relationships_up.sql").read_text()
    assert "REFERENCES public.parties(tenant_id,id)" in sql
    assert "CREATE TABLE public.customers" not in sql and "CREATE TABLE public.suppliers" not in sql


def test_party_identity_authentication_and_operational_relationship_are_distinct():
    distinctions = set(load("so2_authority.json")["distinctions"])
    assert {"party_identity_is_PC2", "identity_authentication_is_PC5", "relationship_type_is_not_auth_role"} <= distinctions


def test_same_party_can_be_customer_supplier_and_partner_without_duplicate_party():
    service, _ = authority()
    customer = establish(service, "c", relationship_type="customer", status=RelationshipStatus.ACTIVE)
    supplier = establish(service, "s", relationship_type="supplier", status=RelationshipStatus.ACTIVE)
    partner = establish(service, "p", relationship_type="partner", status=RelationshipStatus.ACTIVE)
    assert {item.party_public_id for item in (customer, supplier, partner)} == {UUID(int=100)}
    assert len({item.public_id for item in (customer, supplier, partner)}) == 3


def test_tenant_participation_requires_explicit_pc2_party_and_cross_tenant_lookup_fails():
    service, _ = authority()
    first = establish(service, "a", 1, UUID(int=100), "client", RelationshipStatus.ACTIVE)
    second = establish(service, "b", 2, UUID(int=200), "client", RelationshipStatus.ACTIVE)
    assert first.party_public_id != second.party_public_id
    with pytest.raises(SO2AuthorityError, match="SO2_NOT_FOUND"):
        service.relationship(2, first.public_id)
    with pytest.raises(SO2AuthorityError, match="SO2_PARTY_NOT_FOUND"):
        establish(service, "cross", 1, UUID(int=200), "supplier")


def test_lifecycle_history_is_append_only_and_deterministic():
    service, _ = authority()
    item = establish(service)
    active = service.change_status(ChangeRelationshipStatus("activate", 1, item.public_id, 1, RelationshipStatus.ACTIVE, "qualified", NOW))
    ended = service.end("end", 1, item.public_id, 2, "contract_complete", NOW)
    reopened = service.reactivate("reopen", 1, item.public_id, 3, "renewed", NOW)
    history = service.history(1, item.public_id)
    assert [event.to_status for event in history] == [RelationshipStatus.PROSPECT, RelationshipStatus.ACTIVE, RelationshipStatus.ENDED, RelationshipStatus.ACTIVE]
    assert reopened.row_version == 4 and ended.effective_to == NOW and reopened.effective_to is None


def test_invalid_transition_and_stale_write_fail_closed():
    service, _ = authority()
    item = establish(service, status=RelationshipStatus.ACTIVE)
    with pytest.raises(SO2AuthorityError, match="SO2_INVALID_STATE_TRANSITION"):
        service.change_status(ChangeRelationshipStatus("bad", 1, item.public_id, 1, RelationshipStatus.PROSPECT, "rollback", NOW))
    with pytest.raises(SO2AuthorityError, match="SO2_STALE_VERSION"):
        service.update_preferences(UpdateRelationshipPreferences("stale", 1, item.public_id, 9, {"preferred_method":"phone"}))


def test_preferences_do_not_duplicate_pc2_contacts_or_invent_consent():
    service, _ = authority()
    item = establish(service)
    updated = service.update_preferences(UpdateRelationshipPreferences("pref", 1, item.public_id, 1, {"preferred_method":"phone", "contact_purpose":"service_updates"}))
    assert updated.preferences["preferred_method"] == "phone"
    for forbidden in ({"email":"x@example.test"}, {"marketing_consent":True}):
        with pytest.raises(SO2AuthorityError, match="SO2_PREFERENCE_AUTHORITY_VIOLATION"):
            service.update_preferences(UpdateRelationshipPreferences("bad", 1, item.public_id, 2, forbidden))


def test_semantic_segmentation_uses_pc3_assignment_subject():
    observed = []
    service, _ = authority(semantics=observed)
    item = establish(service)
    result = service.classify(ClassifyRelationship("segment", 1, item.public_id, "tenant.crm:high-touch", NOW))
    assert result["subject_type"] == "so2_operational_relationship" and result["subject_key"] == str(item.public_id)


def test_relationship_type_never_grants_server_permission():
    service, _ = authority(authorized=False)
    with pytest.raises(SO2AuthorityError, match="SO2_PERMISSION_DENIED"):
        establish(service, relationship_type="platform_admin", status=RelationshipStatus.ACTIVE)


def test_structural_scope_is_tenant_validated():
    service, _ = authority()
    command = EstablishRelationship("scoped", 1, UUID(int=100), "customer", RelationshipStatus.ACTIVE, NOW, organization_unit_id=999)
    with pytest.raises(SO2AuthorityError, match="SO2_SCOPE_MISMATCH"):
        service.establish(command)


def test_finance_has_no_so2_writer_or_integration_point():
    authority_contract = load("so2_authority.json")
    interfaces = load("so2_public_interfaces.json")
    assert authority_contract["financial_side_effects"] == "NONE" and interfaces["finance_integration_points"] == []
    sql = (ROOT / "alembic_neutral/sql/so2_operational_party_relationships_up.sql").read_text()
    assert "financial_events" not in sql and "financial_obligations" not in sql


def test_legacy_inventory_is_complete_and_non_destructive():
    decisions = {item["artifact"]: item["classification"] for item in load("so2_legacy_adoption_manifest.json")["decisions"]}
    assert {"ADOPT", "MAP", "BRIDGE", "PRESERVE", "RETIRE_LATER"} <= set(decisions.values())
    assert load("so2_legacy_adoption_manifest.json")["bulk_rewrite"] == "FORBIDDEN"


def test_two_profiles_change_terminology_and_semantics_without_source_change():
    retail = load("examples/retail_service_crm_profile.json")
    professional = load("examples/professional_service_crm_profile.json")
    assert retail["terminology"] != professional["terminology"]
    assert retail["semantic_segments"] != professional["semantic_segments"]
    assert retail["source_changes"] == professional["source_changes"] == "NONE"


def test_xa_hooks_do_not_infer_authorization_or_transitions():
    xa = load("so2_xa_metadata.json")
    assert not xa["navigation"][0]["visibility_is_authorization"]
    assert not xa["actions"][0]["frontend_infers_transition"]
    assert xa["frontend_implementation"] == "NONE"


def test_so0_public_private_boundary_and_stable_error_fields():
    interfaces = load("so2_public_interfaces.json")
    so0 = load("so0_module_contract.json")
    assert interfaces["cross_module_private_access"] == "FORBIDDEN"
    assert set(interfaces["errors"]["fields"]) == set(so0["error_contract"]["required"])


def test_development_adoption_is_resumable_and_fail_closed():
    assert _development_action(PREVIOUS) == "UPGRADE"
    assert _development_action(HEAD) == "VERIFY_IN_PLACE"
    with pytest.raises(RuntimeError, match="SO2_DEVELOPMENT_HEAD_UNSAFE"):
        _development_action("parallel_head")
    accepted = {"finance":{"financial_events":1}, "party":{"parties":2}, "so2":{"so2_operational_relationships":3}}
    _verify_snapshot("VERIFY_IN_PLACE", copy.deepcopy(accepted), copy.deepcopy(accepted))
    changed = copy.deepcopy(accepted)
    changed["so2"]["so2_operational_relationships"] += 1
    with pytest.raises(RuntimeError, match="SO2_DEVELOPMENT_REPEAT_MUTATED_DATA"):
        _verify_snapshot("VERIFY_IN_PLACE", accepted, changed)


def test_windows_acceptance_references_only_existing_focused_contracts():
    paths = _focused_test_paths()
    assert "tests/contracts/test_so0_shared_operations_constitution.py" in paths
    assert "tests/contracts/test_so0_shared_operations.py" not in paths


def test_migration_is_one_linear_descendant_and_future_tail_is_not_frozen():
    wrapper = (ROOT / "alembic_neutral/versions/so2_operational_party_relationships_027.py").read_text()
    assert f'revision = "{HEAD}"' in wrapper and f'down_revision = "{PREVIOUS}"' in wrapper
    architecture = (ROOT / "core/platform/architecture_contract.py").read_text()
    assert "heads != [lineage[-1]]" in architecture


def test_no_wnd_or_industry_default_in_active_so2_contracts():
    forbidden = (bytes((87, 78, 68)), b"Wine & Dine", b"Logpom", b"restaurant")
    for base in (ROOT / "shared_operations/so2",):
        for path in base.rglob("*"):
            if path.is_file():
                assert not any(token.lower() in path.read_bytes().lower() for token in forbidden)


def test_aggregate_descendant_scopes_so2_command_idempotency_by_tenant_when_present():
    hardening = ROOT / "alembic_neutral/sql/so_aggregate_conformance_hardening_up.sql"
    if not hardening.is_file():
        pytest.skip("aggregate descendant hardening not present in historical SO2 source")
    sql = hardening.read_text(encoding="utf-8")
    repository = (ROOT / "shared_operations/so2/sql_repository.py").read_text(encoding="utf-8")
    assert "UNIQUE(tenant_id,command_key)" in sql
    assert "FOREIGN KEY(tenant_id,result_id)" in sql
    assert "ON CONFLICT(tenant_id,command_key)" in repository
    assert "WHERE tenant_id=:tenant AND command_key=:key" in repository
