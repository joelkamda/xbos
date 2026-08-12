from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from core.platform.structure.contracts import LegalEntity, Location, LocationKind, OrganizationUnit, ProvisionTenant, StructuralContext, Tenant, TenantLifecycle
from core.platform.structure.service import StructuralAuthority, StructuralAuthorityError
from scripts.verify_pc1_structural_authority import validate_structural_distinction

ROOT = Path(__file__).resolve().parents[2]
UP = (ROOT / "alembic_neutral/sql/pc1_structural_context_up.sql").read_text(encoding="utf-8")
DOWN = (ROOT / "alembic_neutral/sql/pc1_structural_context_down.sql").read_text(encoding="utf-8")


class MemoryRepository:
    def __init__(self):
        self.tenants = {1: Tenant(1,"T1","Tenant",TenantLifecycle.ACTIVE,"CM","XAF","fr-CM","Africa/Douala")}
        self.organizations = {
            (1,10): OrganizationUnit(10,UUID(int=10),1,"ROOT","Root","root",None,100),
            (1,11): OrganizationUnit(11,UUID(int=11),1,"OPS","Operations","department",10,100),
            (2,20): OrganizationUnit(20,UUID(int=20),2,"OTHER","Other","root"),
        }
        self.legals = {(1,100): LegalEntity(100,UUID(int=100),1,"LE","Legal Entity")}
        self.places = {(1,200): Location(200,UUID(int=200),1,"HQ","HQ",LocationKind.PHYSICAL,100)}
        self.mappings = {(1,7):(11,200)}
        self.replays = {}

    def tenant(self, tenant_id): return self.tenants.get(tenant_id)
    def organization_unit(self, tenant_id, item_id): return self.organizations.get((tenant_id,item_id))
    def legal_entity(self, tenant_id, item_id): return self.legals.get((tenant_id,item_id))
    def location(self, tenant_id, item_id): return self.places.get((tenant_id,item_id))
    def organization_units(self, tenant_id): return tuple(v for (t,_),v in self.organizations.items() if t==tenant_id)
    def legal_entities(self, tenant_id): return tuple(v for (t,_),v in self.legals.items() if t==tenant_id)
    def locations(self, tenant_id): return tuple(v for (t,_),v in self.places.items() if t==tenant_id)
    def branch_mapping(self, tenant_id, branch_id): return self.mappings.get((tenant_id,branch_id))
    def transition_tenant(self, tenant_id, expected_version, target):
        current=self.tenants[tenant_id]
        if current.row_version != expected_version: raise StructuralAuthorityError("tenant_concurrent_change")
        result=replace(current,lifecycle=target,row_version=current.row_version+1);self.tenants[tenant_id]=result;return result
    def provision(self, command, fingerprint):
        prior=self.replays.get(command.command_key)
        if prior and prior[0] != fingerprint: raise StructuralAuthorityError("conflicting_provisioning_replay")
        if prior: return prior[1]
        result=StructuralContext(self.tenants[1],self.organizations[(1,10)],self.legals[(1,100)],self.places[(1,200)],(10,))
        self.replays[command.command_key]=(fingerprint,result);return result


def test_pc1_contract_covers_all_ten_obligations_and_distinct_authorities():
    contract=json.loads((ROOT/"contracts/platform/v1/pc1_structural_authority.json").read_text())
    assert contract["scope"] == [f"PC1.{n}" for n in range(1,11)]
    assert list(contract["authorities"]) == ["tenant","organization_unit","legal_entity","location"]
    assert len(set(contract["authorities"].values())) == 4


def test_context_resolution_is_deterministic_and_branch_is_only_a_bridge():
    authority=StructuralAuthority(MemoryRepository())
    context=authority.resolve(tenant_id=1,legacy_branch_id=7)
    assert context.ancestry == (10,11)
    assert context.organization_unit.id == 11 and context.location.id == 200 and context.legal_entity.id == 100


def test_distinct_authorities_may_share_table_local_numeric_id():
    shared_id = 1
    context = StructuralContext(
        Tenant(shared_id,"T1","Tenant",TenantLifecycle.ACTIVE,"CM","XAF","fr-CM","Africa/Douala"),
        OrganizationUnit(shared_id,UUID(int=11),shared_id,"ROOT","Root","root",None,shared_id),
        LegalEntity(shared_id,UUID(int=12),shared_id,"LE","Legal Entity"),
        Location(shared_id,UUID(int=13),shared_id,"HQ","HQ",LocationKind.PHYSICAL,shared_id),
        (shared_id,),
    )
    validate_structural_distinction(context)


def test_cross_tenant_ambiguous_and_conflicting_context_fail_closed():
    authority=StructuralAuthority(MemoryRepository())
    with pytest.raises(StructuralAuthorityError,match="organization_not_found_or_cross_tenant"):
        authority.resolve(tenant_id=1,organization_unit_id=20)
    authority.repository.places[(1,201)] = replace(authority.repository.places[(1,200)],id=201,legal_entity_id=101)
    with pytest.raises(StructuralAuthorityError,match="ambiguous_legal_entity_context"):
        authority.resolve(tenant_id=1,organization_unit_id=11,location_id=201)
    with pytest.raises(StructuralAuthorityError,match="conflicting_structural_context"):
        authority.resolve(tenant_id=1,legacy_branch_id=7,organization_unit_id=10)


def test_cycle_and_missing_parent_fail_closed():
    repo=MemoryRepository();authority=StructuralAuthority(repo)
    repo.organizations[(1,10)] = replace(repo.organizations[(1,10)],parent_id=11)
    with pytest.raises(StructuralAuthorityError,match="organization_cycle"): authority.ancestry(1,11)
    repo=MemoryRepository();repo.organizations[(1,11)] = replace(repo.organizations[(1,11)],parent_id=99)
    with pytest.raises(StructuralAuthorityError,match="organization_not_found_or_cross_tenant"): StructuralAuthority(repo).ancestry(1,11)


def test_provisioning_replay_is_stable_and_conflict_fails():
    authority=StructuralAuthority(MemoryRepository())
    command=ProvisionTenant("cmd-1","NEW","New","CM","XAF","fr-CM","Africa/Douala","LE","New Legal","ROOT","Root")
    assert authority.provision(command) == authority.provision(command)
    with pytest.raises(StructuralAuthorityError,match="conflicting_provisioning_replay"):
        authority.provision(replace(command,tenant_name="Different"))


def test_lifecycle_has_no_destructive_delete_and_uses_optimistic_version():
    authority=StructuralAuthority(MemoryRepository())
    suspended=authority.transition_tenant(1,1,TenantLifecycle.SUSPENDED)
    assert suspended.lifecycle == TenantLifecycle.SUSPENDED and suspended.row_version == 2
    with pytest.raises(StructuralAuthorityError,match="tenant_unavailable"): authority.resolve(tenant_id=1)
    active=authority.transition_tenant(1,2,TenantLifecycle.ACTIVE)
    assert active.lifecycle == TenantLifecycle.ACTIVE and active.row_version == 3


def test_export_is_deterministic_tenant_scoped_and_has_no_financial_effect():
    authority=StructuralAuthority(MemoryRepository())
    first=authority.export(1);second=authority.export(1)
    assert first == second and first.endswith(b"\n")
    payload=json.loads(first)
    assert payload["schema"] == "xbos.pc1.structural-export.v1"
    assert {row["tenant_id"] for row in payload["organization_units"]} == {1}
    assert all(word not in first.lower() for word in (b"journal",b"payment",b"outbox"))


def test_migration_promotes_existing_org_preserves_finance_and_guards_cycles():
    assert "ALTER TABLE public.organization_units ADD COLUMN legal_entity_id" in UP
    assert "fk_organization_units_parent" not in UP
    assert "pc1_reject_organization_cycle" in UP
    assert "legacy_branch_structural_mappings" in UP
    assert "REFERENCES public.branches(tenant_id,id) ON DELETE RESTRICT" in UP
    assert "UPDATE public.organization_units ou SET legal_entity_id" in UP
    assert "WITH inserted_org AS" not in UP
    assert UP.index("INSERT INTO public.organization_units") < UP.index("INSERT INTO public.locations") < UP.index("INSERT INTO public.legacy_branch_structural_mappings")
    assert "DROP TABLE IF EXISTS public.organization_units" not in DOWN
    assert "DROP TABLE IF EXISTS public.tenants" not in DOWN


def test_migration_is_single_canonical_child_and_no_finance_source_changed():
    version=(ROOT/"alembic_neutral/versions/pc1_structural_context_021_tenant_organization_legal_location.py").read_text()
    assert 'revision = "pc1_structural_context_021"' in version
    assert 'down_revision = "m64_reconciliation_controls_020"' in version
    assert not list((ROOT/"alembic_neutral/versions").glob("pc1_*.py"))[1:]


def test_verifier_builds_one_complete_clean_fixture_and_diagnoses_missing_mapping():
    source=(ROOT/"scripts/verify_pc1_structural_authority.py").read_text()
    for marker in (
        "legacy branch fixture was not mapped after PC1 migration",
        "incomplete clean-replay fixture",
        "StructuralAuthority(SQLStructuralRepository(session)).provision",
        "legacy_branch_id=9101",
        "organization_not_found_or_cross_tenant",
        "organization_cycle",
        "ThreadPoolExecutor(max_workers=2)",
        "tenant structural export is nondeterministic",
        "DROP DATABASE",
    ):
        assert marker in source
    assert ".one()" not in source
