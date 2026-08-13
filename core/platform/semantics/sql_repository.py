"""SQLAlchemy persistence boundary for PC3 semantic authority."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from .contracts import (
    AssignClassification, ClassificationSnapshot, CreateConcept, CreateMapping,
    CreateNamespace, CreateSemanticVersion, MappingType, MoveTaxonomyNode, NamespaceScope,
    SemanticConcept, SemanticLifecycle, SemanticMapping, SemanticNamespace,
    SemanticVersion, TaxonomyPlacement,
)
from .service import SemanticAuthorityError


class SQLSemanticRepository:
    def __init__(self, session): self.session=session

    def _command(self,key,fingerprint,command_type):
        self.session.execute(text("""INSERT INTO semantic_commands(command_key,request_fingerprint,command_type)
            VALUES(:key,:fingerprint,:type) ON CONFLICT(command_key) DO NOTHING"""),{"key":key,"fingerprint":fingerprint,"type":command_type})
        row=self.session.execute(text("SELECT * FROM semantic_commands WHERE command_key=:key FOR UPDATE"),{"key":key}).one()
        if row.request_fingerprint!=fingerprint or row.command_type!=command_type:raise SemanticAuthorityError("conflicting_semantic_command_replay")
        return row

    def _complete(self,key,table,result_id):
        self.session.execute(text("UPDATE semantic_commands SET result_table=:table,result_id=:id,completed_at=now() WHERE command_key=:key"),{"key":key,"table":table,"id":result_id})

    @staticmethod
    def _namespace(row):return SemanticNamespace(row.id,UUID(str(row.public_id)),row.namespace_code,NamespaceScope(row.scope),row.owner_code,row.tenant_id,SemanticLifecycle(row.lifecycle))
    @staticmethod
    def _concept(row):return SemanticConcept(row.id,UUID(str(row.public_id)),row.namespace_id,row.namespace_code,row.code,SemanticLifecycle(row.lifecycle))
    @staticmethod
    def _version(row):return SemanticVersion(row.id,UUID(str(row.public_id)),row.concept_id,row.version_number,row.effective_from,row.effective_to,row.canonical_label,row.definition,row.definition_fingerprint)

    def create_namespace(self,command:CreateNamespace,fingerprint:str)->SemanticNamespace:
        replay=self._command(command.command_key,fingerprint,"create_namespace")
        if replay.result_id:row=self.session.execute(text("SELECT * FROM semantic_namespaces WHERE id=:id"),{"id":replay.result_id}).one()
        else:
            try:row=self.session.execute(text("""INSERT INTO semantic_namespaces(namespace_code,scope,owner_code,tenant_id)
                VALUES(lower(btrim(:code)),:scope,lower(btrim(:owner)),:tenant) RETURNING *"""),{"code":command.namespace_code,"scope":command.scope.value,"owner":command.owner_code,"tenant":command.tenant_id}).one()
            except Exception as exc:raise SemanticAuthorityError("namespace_collision_or_competing_owner") from exc
            self._complete(command.command_key,"semantic_namespaces",row.id)
        return self._namespace(row)

    def create_concept(self,command:CreateConcept,fingerprint:str)->SemanticConcept:
        replay=self._command(command.command_key,fingerprint,"create_concept")
        if replay.result_id:
            row=self.session.execute(text("""SELECT c.*,n.namespace_code FROM semantic_concepts c JOIN semantic_namespaces n ON n.id=c.namespace_id WHERE c.id=:id"""),{"id":replay.result_id}).one()
        else:
            namespace=self.session.execute(text("SELECT * FROM semantic_namespaces WHERE namespace_code=lower(btrim(:code)) FOR UPDATE"),{"code":command.namespace_code}).first()
            if namespace is None:raise SemanticAuthorityError("namespace_not_found")
            if namespace.owner_code!=command.owner_code.lower():raise SemanticAuthorityError("unauthorized_namespace_mutation")
            try:row=self.session.execute(text("""INSERT INTO semantic_concepts(namespace_id,code)
                VALUES(:namespace,lower(btrim(:code))) RETURNING *, :namespace_code AS namespace_code"""),{"namespace":namespace.id,"code":command.code,"namespace_code":namespace.namespace_code}).one()
            except Exception as exc:raise SemanticAuthorityError("duplicate_semantic_code") from exc
            self._complete(command.command_key,"semantic_concepts",row.id)
        return self._concept(row)

    def create_version(self,command:CreateSemanticVersion,fingerprint:str,definition_fingerprint:str)->SemanticVersion:
        replay=self._command(command.command_key,fingerprint,"create_version")
        if replay.result_id:row=self.session.execute(text("SELECT * FROM semantic_versions WHERE id=:id"),{"id":replay.result_id}).one()
        else:
            concept=self.session.execute(text("""SELECT c.id,n.owner_code FROM semantic_concepts c JOIN semantic_namespaces n ON n.id=c.namespace_id
                WHERE n.namespace_code=lower(btrim(:namespace)) AND c.code=lower(btrim(:code)) FOR UPDATE OF c"""),{"namespace":command.namespace_code,"code":command.concept_code}).first()
            if concept is None:raise SemanticAuthorityError("semantic_concept_not_found")
            if concept.owner_code!=command.owner_code.lower():raise SemanticAuthorityError("unauthorized_namespace_mutation")
            try:row=self.session.execute(text("""INSERT INTO semantic_versions
                (concept_id,version_number,effective_from,effective_to,canonical_label,definition,definition_fingerprint)
                VALUES(:concept,:version,:start,:end,:label,:definition,:fingerprint) RETURNING *"""),{"concept":concept.id,"version":command.version_number,"start":command.effective_from,"end":command.effective_to,"label":command.canonical_label.strip(),"definition":command.definition.strip(),"fingerprint":definition_fingerprint}).one()
            except Exception as exc:raise SemanticAuthorityError("conflicting_semantic_version") from exc
            self._complete(command.command_key,"semantic_versions",row.id)
        return self._version(row)

    def resolve(self,qualified_code,effective_on,tenant_id=None):
        namespace_code,concept_code=qualified_code.split(":",1)
        row=self.session.execute(text("""SELECT c.id,c.public_id,c.namespace_id,n.namespace_code,c.code,c.lifecycle,
                   v.id AS version_id,v.public_id AS version_public_id,v.version_number,v.effective_from,v.effective_to,v.canonical_label,v.definition,v.definition_fingerprint
            FROM semantic_namespaces n JOIN semantic_concepts c ON c.namespace_id=n.id JOIN semantic_versions v ON v.concept_id=c.id
            WHERE n.namespace_code=:namespace AND c.code=:code AND n.lifecycle<>'retired' AND c.lifecycle<>'retired'
              AND (n.scope<>'tenant' OR n.tenant_id=:tenant)
              AND v.effective_from<=:on AND (v.effective_to IS NULL OR v.effective_to>=:on)
            ORDER BY v.version_number DESC"""),{"namespace":namespace_code,"code":concept_code,"tenant":tenant_id,"on":effective_on}).all()
        if len(row)!=1:return None
        item=row[0]
        concept=SemanticConcept(item.id,UUID(str(item.public_id)),item.namespace_id,item.namespace_code,item.code,SemanticLifecycle(item.lifecycle))
        version=SemanticVersion(item.version_id,UUID(str(item.version_public_id)),item.id,item.version_number,item.effective_from,item.effective_to,item.canonical_label,item.definition,item.definition_fingerprint)
        return concept,version

    def create_mapping(self,command:CreateMapping,fingerprint:str)->SemanticMapping:
        replay=self._command(command.command_key,fingerprint,"create_mapping")
        if replay.result_id:row=self.session.execute(text("SELECT m.*,s.mapping_set_code FROM semantic_mappings m JOIN semantic_mapping_sets s ON s.id=m.mapping_set_id WHERE m.id=:id"),{"id":replay.result_id}).one()
        else:
            mapping_set=self.session.execute(text("SELECT * FROM semantic_mapping_sets WHERE mapping_set_code=lower(btrim(:code)) FOR UPDATE"),{"code":command.mapping_set_code}).first()
            if mapping_set is None:
                mapping_set=self.session.execute(text("""INSERT INTO semantic_mapping_sets(mapping_set_code,owner_code)
                    VALUES(lower(btrim(:code)),lower(btrim(:owner))) RETURNING *"""),{"code":command.mapping_set_code,"owner":command.owner_code}).one()
            if mapping_set.owner_code!=command.owner_code.lower():raise SemanticAuthorityError("unauthorized_mapping_set_mutation")
            def concept_id(qualified):
                namespace,code=qualified.lower().split(":",1)
                return self.session.execute(text("SELECT c.id FROM semantic_concepts c JOIN semantic_namespaces n ON n.id=c.namespace_id WHERE n.namespace_code=:n AND c.code=:c"),{"n":namespace,"c":code}).scalar_one_or_none()
            source,target=concept_id(command.source_qualified_code),concept_id(command.target_qualified_code)
            if source is None or target is None:raise SemanticAuthorityError("mapping_concept_not_found")
            try:row=self.session.execute(text("""INSERT INTO semantic_mappings(mapping_set_id,source_concept_id,target_concept_id,mapping_type,effective_from,effective_to)
                VALUES(:set,:source,:target,:type,:start,:end) RETURNING *, :set_code AS mapping_set_code"""),{"set":mapping_set.id,"source":source,"target":target,"type":command.mapping_type.value,"start":command.effective_from,"end":command.effective_to,"set_code":mapping_set.mapping_set_code}).one()
            except Exception as exc:raise SemanticAuthorityError("duplicate_or_conflicting_semantic_mapping") from exc
            self._complete(command.command_key,"semantic_mappings",row.id)
        return SemanticMapping(row.id,UUID(str(row.public_id)),row.mapping_set_code,row.source_concept_id,row.target_concept_id,MappingType(row.mapping_type),row.effective_from,row.effective_to)

    def assign(self,command:AssignClassification,fingerprint:str,concept:SemanticConcept,version:SemanticVersion)->ClassificationSnapshot:
        replay=self._command(command.command_key,fingerprint,"assign_classification")
        if replay.result_id:row=self.session.execute(text("SELECT * FROM classification_assignments WHERE id=:id"),{"id":replay.result_id}).one()
        else:
            try:row=self.session.execute(text("""INSERT INTO classification_assignments
                (tenant_id,subject_type,subject_key,concept_id,concept_version_id,taxonomy_node_id,classified_on,concept_qualified_code_snapshot,concept_version_snapshot,definition_fingerprint_snapshot)
                VALUES(:tenant,lower(btrim(:subject_type)),btrim(:subject_key),:concept,:version,:node,:on,:qualified,:version_number,:fingerprint)
                RETURNING *"""),{"tenant":command.tenant_id,"subject_type":command.subject_type,"subject_key":command.subject_key,"concept":concept.id,"version":version.id,"node":command.taxonomy_node_id,"on":command.classified_on,"qualified":concept.qualified_code,"version_number":version.version_number,"fingerprint":version.definition_fingerprint}).one()
            except Exception as exc:raise SemanticAuthorityError("duplicate_or_cross_tenant_classification") from exc
            self._complete(command.command_key,"classification_assignments",row.id)
        return ClassificationSnapshot(row.id,row.subject_type,row.subject_key,row.concept_qualified_code_snapshot,row.concept_version_snapshot,row.definition_fingerprint_snapshot,row.taxonomy_node_id,row.classified_on)

    def impact(self,qualified_code):
        namespace,code=qualified_code.split(":",1)
        concept=self.session.execute(text("SELECT c.id FROM semantic_concepts c JOIN semantic_namespaces n ON n.id=c.namespace_id WHERE n.namespace_code=:n AND c.code=:c"),{"n":namespace,"c":code}).scalar_one_or_none()
        if concept is None:raise SemanticAuthorityError("semantic_concept_not_found")
        counts={}
        for name,query in {
            "versions":"SELECT count(*) FROM semantic_versions WHERE concept_id=:id",
            "superseding_concepts":"SELECT count(*) FROM semantic_concepts WHERE superseded_by_concept_id=:id",
            "taxonomy_nodes":"SELECT count(*) FROM taxonomy_nodes WHERE semantic_concept_id=:id",
            "assignments":"SELECT count(*) FROM classification_assignments WHERE concept_id=:id",
            "source_mappings":"SELECT count(*) FROM semantic_mappings WHERE source_concept_id=:id",
            "target_mappings":"SELECT count(*) FROM semantic_mappings WHERE target_concept_id=:id",
        }.items():counts[name]=self.session.execute(text(query),{"id":concept}).scalar_one()
        return {"qualified_code":qualified_code,"counts":counts,"safe_to_retire":not any(counts[name] for name in ("superseding_concepts","taxonomy_nodes","assignments","source_mappings","target_mappings"))}

    def move_taxonomy_node(self,command:MoveTaxonomyNode)->TaxonomyPlacement:
        row=self.session.execute(text("""UPDATE taxonomy_nodes SET parent_id=:parent,semantic_row_version=semantic_row_version+1
            WHERE tenant_id=:tenant AND id=:id AND semantic_row_version=:version
            RETURNING tenant_id,id,parent_id,semantic_row_version"""),{"parent":command.parent_id,"tenant":command.tenant_id,"id":command.taxonomy_node_id,"version":command.expected_version}).first()
        if row is None:raise SemanticAuthorityError("taxonomy_not_found_cross_tenant_or_concurrent_change")
        return TaxonomyPlacement(row.tenant_id,row.id,row.parent_id,row.semantic_row_version)

    def export(self,tenant_id):
        namespaces=[dict(row._mapping) for row in self.session.execute(text("""SELECT namespace_code,scope,owner_code,tenant_id,lifecycle FROM semantic_namespaces
            WHERE scope<>'tenant' OR tenant_id=:tenant ORDER BY namespace_code"""),{"tenant":tenant_id})]
        assignments=[] if tenant_id is None else [dict(row._mapping) for row in self.session.execute(text("""SELECT subject_type,subject_key,concept_qualified_code_snapshot,concept_version_snapshot,definition_fingerprint_snapshot,taxonomy_node_id,classified_on
            FROM classification_assignments WHERE tenant_id=:tenant ORDER BY subject_type,subject_key,classified_on,id"""),{"tenant":tenant_id})]
        return {"schema":"xbos.pc3.semantic-export.v1","tenant_id":tenant_id,"namespaces":namespaces,"assignments":assignments}
