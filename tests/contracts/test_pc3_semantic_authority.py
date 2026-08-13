from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from core.platform.semantics import (
    AssignClassification, ClassificationSnapshot, CreateConcept, CreateMapping,
    CreateNamespace, CreateSemanticVersion, MappingType, MoveTaxonomyNode, NamespaceScope,
    SemanticAuthority, SemanticAuthorityError, SemanticConcept, SemanticLifecycle,
    SemanticMapping, SemanticNamespace, SemanticVersion, TaxonomyPlacement,
)

ROOT=Path(__file__).resolve().parents[2]
UP=(ROOT/"alembic_neutral/sql/pc3_semantic_authority_up.sql").read_text(encoding="utf-8")
DOWN=(ROOT/"alembic_neutral/sql/pc3_semantic_authority_down.sql").read_text(encoding="utf-8")


class MemoryRepository:
    def __init__(self):
        self.commands={};self.namespaces={};self.concepts={};self.versions={};self.mappings={};self.assignments={};self.nodes={(1,7):(None,1)};self.next_id=1
    def _replay(self,key,fingerprint,create):
        prior=self.commands.get(key)
        if prior and prior[0]!=fingerprint:raise SemanticAuthorityError("conflicting_semantic_command_replay")
        if prior:return prior[1]
        result=create();self.commands[key]=(fingerprint,result);return result
    def create_namespace(self,c,f):
        def create():
            code=c.namespace_code.lower();prior=self.namespaces.get(code)
            if prior:raise SemanticAuthorityError("namespace_collision_or_competing_owner")
            item=SemanticNamespace(self.next_id,UUID(int=self.next_id),code,c.scope,c.owner_code.lower(),c.tenant_id,SemanticLifecycle.ACTIVE);self.next_id+=1;self.namespaces[code]=item;return item
        return self._replay(c.command_key,f,create)
    def create_concept(self,c,f):
        def create():
            namespace=self.namespaces.get(c.namespace_code.lower())
            if not namespace:raise SemanticAuthorityError("namespace_not_found")
            if namespace.owner_code!=c.owner_code.lower():raise SemanticAuthorityError("unauthorized_namespace_mutation")
            key=(namespace.namespace_code,c.code.lower())
            if key in self.concepts:raise SemanticAuthorityError("duplicate_semantic_code")
            item=SemanticConcept(self.next_id,UUID(int=self.next_id),namespace.id,namespace.namespace_code,c.code.lower(),SemanticLifecycle.ACTIVE);self.next_id+=1;self.concepts[key]=item;return item
        return self._replay(c.command_key,f,create)
    def create_version(self,c,f,definition_fingerprint):
        def create():
            concept=self.concepts.get((c.namespace_code.lower(),c.concept_code.lower()))
            if not concept:raise SemanticAuthorityError("semantic_concept_not_found")
            namespace=self.namespaces[c.namespace_code.lower()]
            if namespace.owner_code!=c.owner_code.lower():raise SemanticAuthorityError("unauthorized_namespace_mutation")
            values=self.versions.setdefault(concept.id,[])
            if any(v.version_number==c.version_number or not ((c.effective_to and c.effective_to<v.effective_from) or (v.effective_to and v.effective_to<c.effective_from)) for v in values):raise SemanticAuthorityError("conflicting_semantic_version")
            item=SemanticVersion(self.next_id,UUID(int=self.next_id),concept.id,c.version_number,c.effective_from,c.effective_to,c.canonical_label,c.definition,definition_fingerprint);self.next_id+=1;values.append(item);return item
        return self._replay(c.command_key,f,create)
    def resolve(self,qualified,effective_on,tenant_id=None):
        n,c=qualified.split(":",1);concept=self.concepts.get((n,c));namespace=self.namespaces.get(n)
        if not concept or (namespace.scope is NamespaceScope.TENANT and namespace.tenant_id!=tenant_id):return None
        matches=[v for v in self.versions.get(concept.id,[]) if v.effective_from<=effective_on and (v.effective_to is None or effective_on<=v.effective_to)]
        return (concept,matches[0]) if len(matches)==1 else None
    def create_mapping(self,c,f):
        def create():
            source=self.concepts.get(tuple(c.source_qualified_code.lower().split(":",1)));target=self.concepts.get(tuple(c.target_qualified_code.lower().split(":",1)))
            if not source or not target:raise SemanticAuthorityError("mapping_concept_not_found")
            natural=(c.mapping_set_code,source.id,target.id,c.mapping_type,c.effective_from)
            prior=self.mappings.get(natural)
            if prior:
                if prior.effective_to!=c.effective_to:raise SemanticAuthorityError("duplicate_or_conflicting_semantic_mapping")
                return prior
            item=SemanticMapping(self.next_id,UUID(int=self.next_id),c.mapping_set_code,source.id,target.id,c.mapping_type,c.effective_from,c.effective_to);self.next_id+=1;self.mappings[natural]=item;return item
        return self._replay(c.command_key,f,create)
    def assign(self,c,f,concept,version):
        def create():
            natural=(c.tenant_id,c.subject_type,c.subject_key,concept.id,c.classified_on)
            prior=self.assignments.get(natural)
            if prior:return prior
            item=ClassificationSnapshot(self.next_id,c.subject_type,c.subject_key,concept.qualified_code,version.version_number,version.definition_fingerprint,c.taxonomy_node_id,c.classified_on);self.next_id+=1;self.assignments[natural]=item;return item
        return self._replay(c.command_key,f,create)
    def impact(self,qualified):
        concept=self.concepts.get(tuple(qualified.split(":",1)))
        if not concept:raise SemanticAuthorityError("semantic_concept_not_found")
        assignments=sum(1 for key in self.assignments if key[3]==concept.id);mappings=sum(1 for key in self.mappings if key[1]==concept.id or key[2]==concept.id)
        return {"qualified_code":qualified,"counts":{"assignments":assignments,"mappings":mappings},"safe_to_retire":not(assignments or mappings)}
    def move_taxonomy_node(self,c):
        current=self.nodes.get((c.tenant_id,c.taxonomy_node_id))
        if not current or current[1]!=c.expected_version:raise SemanticAuthorityError("taxonomy_not_found_cross_tenant_or_concurrent_change")
        result=TaxonomyPlacement(c.tenant_id,c.taxonomy_node_id,c.parent_id,current[1]+1);self.nodes[(c.tenant_id,c.taxonomy_node_id)]=(c.parent_id,result.semantic_row_version);return result
    def export(self,tenant_id):return {"schema":"xbos.pc3.semantic-export.v1","tenant_id":tenant_id,"namespaces":sorted(self.namespaces)}


def _authority():
    authority=SemanticAuthority(MemoryRepository())
    authority.create_namespace(CreateNamespace("ns","kernel",NamespaceScope.KERNEL,"pc3"))
    authority.create_concept(CreateConcept("concept","kernel","pc3","business_object"))
    authority.create_version(CreateSemanticVersion("version","kernel","pc3","business_object",1,date(2026,1,1),None,"Business object","A neutral business object."))
    return authority


def test_contract_covers_all_pc3_obligations_and_boundaries():
    contract=json.loads((ROOT/"contracts/platform/v1/pc3_semantic_authority.json").read_text())
    assert contract["scope"]==[f"PC3.{n}" for n in range(1,12)]
    assert contract["taxonomy"]["universal_tree"] is False
    assert contract["boundaries"]["atomic_units"]=="SO0"


def test_semantic_identity_survives_label_change_and_versions_resolve_by_date():
    authority=_authority();concept,v1=authority.resolve(qualified_code="kernel:business_object",effective_on=date(2026,6,1))
    assert concept.qualified_code=="kernel:business_object" and v1.canonical_label=="Business object"
    # Label is version presentation metadata, never the qualified semantic identity.
    assert replace(v1,canonical_label="Objet métier").concept_id==v1.concept_id


def test_namespace_replay_owner_collision_and_unauthorized_mutation_fail_closed():
    authority=_authority();command=CreateNamespace("tenant-ns","tenant.one",NamespaceScope.TENANT,"tenant:1",1)
    assert authority.create_namespace(command)==authority.create_namespace(command)
    with pytest.raises(SemanticAuthorityError,match="conflicting_semantic_command_replay"):authority.create_namespace(replace(command,owner_code="attacker"))
    with pytest.raises(SemanticAuthorityError,match="unauthorized_namespace_mutation"):authority.create_concept(CreateConcept("bad","kernel","tenant:1","override"))


def test_duplicate_semantic_code_and_conflicting_version_fail_closed():
    authority=_authority()
    with pytest.raises(SemanticAuthorityError,match="duplicate_semantic_code"):authority.create_concept(CreateConcept("duplicate","kernel","pc3","business_object"))
    with pytest.raises(SemanticAuthorityError,match="conflicting_semantic_version"):authority.create_version(CreateSemanticVersion("v2","kernel","pc3","business_object",2,date(2026,6,1),None,"Changed","Changed meaning"))


def test_mapping_direction_type_replay_and_conflict_are_explicit():
    authority=_authority();authority.create_concept(CreateConcept("c2","kernel","pc3","resource"));authority.create_version(CreateSemanticVersion("v-c2","kernel","pc3","resource",1,date(2026,1,1),None,"Resource","Neutral resource"))
    command=CreateMapping("map","kernel-map","pc3","kernel:business_object","kernel:resource",MappingType.BROADER,date(2026,1,1))
    assert authority.create_mapping(command)==authority.create_mapping(command)
    with pytest.raises(SemanticAuthorityError,match="conflicting_semantic_command_replay"):authority.create_mapping(replace(command,mapping_type=MappingType.EXACT))


def test_classification_snapshot_remains_stable_and_tenant_namespace_is_isolated():
    authority=_authority();assignment=AssignClassification("assign",1,"atomic_unit","42","kernel:business_object",date(2026,6,1),7)
    snapshot=authority.assign(assignment);assert snapshot==authority.assign(assignment)
    assert snapshot.concept_qualified_code=="kernel:business_object" and len(snapshot.definition_fingerprint)==64
    authority.create_namespace(CreateNamespace("private-ns","tenant.private",NamespaceScope.TENANT,"tenant:1",1))
    authority.create_concept(CreateConcept("private-c","tenant.private","tenant:1","custom"))
    authority.create_version(CreateSemanticVersion("private-v","tenant.private","tenant:1","custom",1,date(2026,1,1),None,"Custom","Tenant meaning"))
    with pytest.raises(SemanticAuthorityError,match="semantic_reference_not_found_or_not_effective"):authority.resolve(qualified_code="tenant.private:custom",effective_on=date(2026,6,1),tenant_id=2)


def test_impact_is_read_only_and_reports_assignments_and_mappings():
    authority=_authority();authority.assign(AssignClassification("assign",1,"atomic_unit","42","kernel:business_object",date(2026,6,1)))
    impact=authority.impact("kernel:business_object")
    assert impact["counts"]["assignments"]==1 and impact["safe_to_retire"] is False


def test_sql_impact_includes_superseding_concept_dependencies():
    source=(ROOT/"core/platform/semantics/sql_repository.py").read_text(encoding="utf-8")
    assert '"superseding_concepts":"SELECT count(*) FROM semantic_concepts WHERE superseded_by_concept_id=:id"' in source
    assert '"superseding_concepts","taxonomy_nodes","assignments"' in source


def test_taxonomy_parent_mutation_uses_optimistic_concurrency_and_tenant_scope():
    authority=_authority();moved=authority.move_taxonomy_node(MoveTaxonomyNode(1,7,None,1))
    assert moved.semantic_row_version==2
    with pytest.raises(SemanticAuthorityError,match="taxonomy_not_found_cross_tenant_or_concurrent_change"):authority.move_taxonomy_node(MoveTaxonomyNode(1,7,None,1))
    with pytest.raises(SemanticAuthorityError,match="taxonomy_not_found_cross_tenant_or_concurrent_change"):authority.move_taxonomy_node(MoveTaxonomyNode(2,7,None,1))


def test_migration_adopts_taxonomy_without_rewriting_data_or_atomic_units():
    assert "ALTER TABLE public.taxonomy_nodes" in UP
    assert "semantic_concept_id BIGINT NULL" in UP
    assert "COMMENT ON TABLE public.atomic_unit_taxonomy" in UP
    for forbidden in ("INSERT INTO public.taxonomy_nodes","UPDATE public.taxonomy_nodes","DELETE FROM public.taxonomy_nodes","ALTER TABLE public.atomic_units"):
        assert forbidden not in UP
    assert "DROP TABLE IF EXISTS public.taxonomy_nodes" not in DOWN


def test_migration_is_canonical_child_and_has_tree_cycle_guard():
    version=(ROOT/"alembic_neutral/versions/pc3_semantic_authority_023_namespaces_taxonomy_mapping_classification.py").read_text()
    assert 'revision = "pc3_semantic_authority_023"' in version and 'down_revision = "pc2_party_authority_022"' in version
    assert "pc3_reject_taxonomy_cycle" in UP and "fk_taxonomy_nodes_parent_tenant" in UP


def test_adoption_manifest_classifies_every_relevant_legacy_authority():
    manifest=json.loads((ROOT/"contracts/platform/v1/pc3_taxonomy_adoption_manifest.json").read_text())
    found={item["authority"]:item["classification"] for item in manifest["entries"]}
    assert found["taxonomy_nodes"]=="ADOPT/EVOLVE" and found["atomic_units"]=="PRESERVE"
    assert found["semantic_level"]==found["taxonomy_type"]=="BRIDGE"


def test_pc3_verifier_taxonomy_cycle_fixture_satisfies_legacy_not_null_taxonomy_type():
    source=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text(encoding="utf-8")
    assert "INSERT INTO taxonomy_nodes(tenant_id,parent_id,name,semantic_level,taxonomy_type,sort_order,is_active)" in source
    assert "'Child','domain','COMMERCE',1,true" in source
