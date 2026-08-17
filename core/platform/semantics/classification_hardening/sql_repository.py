"""SQLAlchemy repository for Pre-R0 semantic-classification hardening."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from core.platform.semantics import SemanticAuthorityError

from .contracts import (
    AssignSemanticClassification,
    AssignmentMode,
    ClassificationRecord,
    ClearTenantTaxonomyOverlay,
    CreateTaxonomyNode,
    CreateTaxonomySystem,
    EndSemanticClassification,
    HealthIssue,
    HealthSeverity,
    ReparentTaxonomyNode,
    SemanticSource,
    SemanticTaxonomyNode,
    SetTenantTaxonomyOverlay,
    TaxonomyPlacementVersion,
    TaxonomySystemDefinition,
    TenantTaxonomyOverlay,
)


class SQLSemanticClassificationRepository:
    def __init__(self, session):
        self.session = session

    def _command(self, tenant_id: int | None, key: str, fingerprint: str, command_type: str):
        self.session.execute(text("""INSERT INTO semantic_classification_commands(tenant_id,command_key,request_fingerprint,command_type)
            VALUES(:tenant,:key,:fingerprint,:type)
            ON CONFLICT DO NOTHING"""),
            {"tenant": tenant_id, "key": key, "fingerprint": fingerprint, "type": command_type})
        row = self.session.execute(text("""SELECT * FROM semantic_classification_commands
            WHERE tenant_id IS NOT DISTINCT FROM :tenant AND command_key=:key FOR UPDATE"""),
            {"tenant": tenant_id, "key": key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise SemanticAuthorityError("conflicting_semantic_classification_command_replay")
        return row

    def _complete(self, command_id: int, table_name: str, result_id: int) -> None:
        self.session.execute(text("""UPDATE semantic_classification_commands
            SET result_table=:table,result_id=:id,completed_at=now() WHERE id=:command"""),
            {"table": table_name, "id": result_id, "command": command_id})

    def _system(self, row) -> TaxonomySystemDefinition:
        return TaxonomySystemDefinition(row.id, UUID(str(row.public_id)), row.system_code, row.owner_code, row.tenant_id, row.namespace_code, row.lifecycle)

    def _node(self, row) -> SemanticTaxonomyNode:
        return SemanticTaxonomyNode(
            row.id, UUID(str(row.public_id)), row.taxonomy_system_id, row.system_code,
            row.semantic_concept_id, row.concept_qualified_code, row.node_code,
            row.tenant_id, row.lifecycle, row.row_version,
        )

    @staticmethod
    def _placement(row) -> TaxonomyPlacementVersion:
        return TaxonomyPlacementVersion(
            row.id, UUID(str(row.public_id)), row.semantic_taxonomy_node_id,
            row.placement_version, UUID(str(row.parent_node_public_id)) if row.parent_node_public_id else None,
            row.sort_order, row.effective_from, row.effective_to, SemanticSource(row.source_type),
            row.source_key, dict(row.provenance or {}),
        )

    @staticmethod
    def _overlay(row) -> TenantTaxonomyOverlay:
        return TenantTaxonomyOverlay(
            row.id, UUID(str(row.public_id)), row.tenant_id, row.semantic_taxonomy_node_id,
            row.overlay_version, row.local_label, row.local_sort_order,
            UUID(str(row.parent_override_public_id)) if row.parent_override_public_id else None,
            row.has_parent_override, row.is_suppressed, row.effective_from, row.effective_to,
            SemanticSource(row.source_type), row.source_key, dict(row.provenance or {}),
        )

    def create_system(self, command: CreateTaxonomySystem, fingerprint: str) -> TaxonomySystemDefinition:
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "create_taxonomy_system")
        if replay.result_id:
            row = self.session.execute(text("""SELECT s.*,n.namespace_code FROM taxonomy_systems s
                LEFT JOIN semantic_namespaces n ON n.id=s.namespace_id WHERE s.id=:id"""), {"id": replay.result_id}).one()
            return self._system(row)
        namespace = self.session.execute(text("""SELECT * FROM semantic_namespaces
            WHERE namespace_code=lower(btrim(:code)) FOR UPDATE"""), {"code": command.namespace_code}).first()
        if namespace is None:
            raise SemanticAuthorityError("namespace_not_found")
        if namespace.owner_code != command.owner_code.strip().lower():
            raise SemanticAuthorityError("unauthorized_namespace_mutation")
        if namespace.scope == "tenant" and namespace.tenant_id != command.tenant_id:
            raise SemanticAuthorityError("taxonomy_system_tenant_scope_mismatch")
        if namespace.scope != "tenant" and command.tenant_id is not None:
            raise SemanticAuthorityError("global_namespace_cannot_create_tenant_system")
        try:
            row = self.session.execute(text("""INSERT INTO taxonomy_systems(system_code,owner_code,tenant_id,namespace_id)
                VALUES(lower(btrim(:code)),lower(btrim(:owner)),:tenant,:namespace)
                RETURNING *, :namespace_code AS namespace_code"""),
                {"code": command.system_code, "owner": command.owner_code, "tenant": command.tenant_id, "namespace": namespace.id, "namespace_code": namespace.namespace_code}).one()
        except Exception as exc:
            raise SemanticAuthorityError("duplicate_or_conflicting_taxonomy_system") from exc
        self._complete(replay.id, "taxonomy_systems", row.id)
        return self._system(row)


    @staticmethod
    def _semantic_date(value: datetime):
        """Bridge timestamped SC41 operations to frozen PC3 DATE semantics in UTC.

        PostgreSQL CAST(timestamptz AS date) is session-timezone-sensitive.  PC3
        semantic versions are DATE-effective, so derive the date before binding.
        """
        return value.astimezone(timezone.utc).date()

    def _concept(self, qualified_code: str, effective_at: datetime, tenant_id: int | None):
        namespace_code, concept_code = qualified_code.lower().split(":", 1)
        rows = self.session.execute(text("""SELECT c.id,c.public_id,n.namespace_code,n.scope,n.tenant_id AS namespace_tenant_id,c.code,
                   v.id AS version_id,v.version_number,v.definition_fingerprint,v.canonical_label
            FROM semantic_namespaces n JOIN semantic_concepts c ON c.namespace_id=n.id
            JOIN semantic_versions v ON v.concept_id=c.id
            WHERE n.namespace_code=:namespace AND c.code=:code
              AND n.lifecycle<>'retired' AND c.lifecycle<>'retired'
              AND (n.scope<>'tenant' OR n.tenant_id=:tenant)
              AND v.effective_from<=:on AND (v.effective_to IS NULL OR v.effective_to>=:on)
            ORDER BY v.version_number DESC"""),
            {"namespace": namespace_code, "code": concept_code, "tenant": tenant_id, "on": self._semantic_date(effective_at)}).all()
        if len(rows) != 1:
            raise SemanticAuthorityError("semantic_reference_not_found_or_not_effective")
        return rows[0]

    def create_node(self, command: CreateTaxonomyNode, fingerprint: str):
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "create_taxonomy_node")
        if replay.result_id:
            node_row = self.session.execute(text("""SELECT n.*,s.system_code,ns.namespace_code||':'||c.code AS concept_qualified_code
                FROM semantic_taxonomy_nodes n JOIN taxonomy_systems s ON s.id=n.taxonomy_system_id
                JOIN semantic_concepts c ON c.id=n.semantic_concept_id JOIN semantic_namespaces ns ON ns.id=c.namespace_id
                WHERE n.id=:id"""), {"id": replay.result_id}).one()
            placement_row = self.session.execute(text("""SELECT p.*,parent.public_id AS parent_node_public_id
                FROM semantic_taxonomy_placements p LEFT JOIN semantic_taxonomy_nodes parent ON parent.id=p.parent_node_id
                WHERE p.semantic_taxonomy_node_id=:id ORDER BY p.placement_version LIMIT 1"""), {"id": replay.result_id}).one()
            return self._node(node_row), self._placement(placement_row)
        system = self.session.execute(text("""SELECT s.*,ns.namespace_code FROM taxonomy_systems s
            LEFT JOIN semantic_namespaces ns ON ns.id=s.namespace_id WHERE s.system_code=lower(btrim(:code)) FOR UPDATE OF s"""),
            {"code": command.system_code}).first()
        if system is None:
            raise SemanticAuthorityError("taxonomy_system_not_found")
        if system.tenant_id is not None and system.tenant_id != command.tenant_id:
            raise SemanticAuthorityError("taxonomy_system_not_visible_to_tenant")
        concept = self._concept(command.concept_qualified_code, command.effective_from, command.tenant_id)
        try:
            node_row = self.session.execute(text("""INSERT INTO semantic_taxonomy_nodes
                (taxonomy_system_id,semantic_concept_id,tenant_id,node_code)
                VALUES(:system,:concept,:tenant,lower(btrim(:node_code)))
                RETURNING *, :system_code AS system_code, :qualified AS concept_qualified_code"""),
                {"system": system.id, "concept": concept.id, "tenant": command.tenant_id,
                 "node_code": command.node_code, "system_code": system.system_code,
                 "qualified": command.concept_qualified_code.lower()}).one()
            parent_id = None
            if command.parent_node_public_id is not None:
                parent_id = self.session.execute(text("SELECT id FROM semantic_taxonomy_nodes WHERE public_id=:public"), {"public": command.parent_node_public_id}).scalar_one_or_none()
                if parent_id is None:
                    raise SemanticAuthorityError("taxonomy_parent_not_found")
            placement_row = self.session.execute(text("""INSERT INTO semantic_taxonomy_placements
                (semantic_taxonomy_node_id,placement_version,parent_node_id,sort_order,effective_from,source_type,source_key,provenance)
                VALUES(:node,1,:parent,:sort,:effective,:source_type,:source_key,CAST(:provenance AS jsonb))
                RETURNING *, (SELECT public_id FROM semantic_taxonomy_nodes WHERE id=parent_node_id) AS parent_node_public_id"""),
                {"node": node_row.id, "parent": parent_id, "sort": command.sort_order,
                 "effective": command.effective_from, "source_type": command.source_type.value,
                 "source_key": command.source_key, "provenance": json_dumps(command.provenance or {})}).one()
        except SemanticAuthorityError:
            raise
        except Exception as exc:
            raise SemanticAuthorityError("invalid_or_conflicting_taxonomy_node") from exc
        self._complete(replay.id, "semantic_taxonomy_nodes", node_row.id)
        return self._node(node_row), self._placement(placement_row)

    def reparent_node(self, command: ReparentTaxonomyNode, fingerprint: str) -> TaxonomyPlacementVersion:
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "reparent_taxonomy_node")
        if replay.result_id:
            row = self.session.execute(text("""SELECT p.*,parent.public_id AS parent_node_public_id FROM semantic_taxonomy_placements p
                LEFT JOIN semantic_taxonomy_nodes parent ON parent.id=p.parent_node_id WHERE p.id=:id"""), {"id": replay.result_id}).one()
            return self._placement(row)
        node = self.session.execute(text("SELECT * FROM semantic_taxonomy_nodes WHERE public_id=:public FOR UPDATE"), {"public": command.node_public_id}).first()
        if node is None or node.tenant_id != command.tenant_id:
            raise SemanticAuthorityError("taxonomy_node_not_found_or_scope_mismatch")
        current = self.session.execute(text("""SELECT * FROM semantic_taxonomy_placements
            WHERE semantic_taxonomy_node_id=:node AND effective_to IS NULL ORDER BY placement_version DESC LIMIT 1 FOR UPDATE"""), {"node": node.id}).first()
        if current is None or current.placement_version != command.expected_placement_version:
            raise SemanticAuthorityError("taxonomy_not_found_or_concurrent_change")
        if command.effective_from <= current.effective_from:
            raise SemanticAuthorityError("taxonomy_reparent_must_be_prospective")
        parent_id = None
        if command.parent_node_public_id is not None:
            parent_id = self.session.execute(text("SELECT id FROM semantic_taxonomy_nodes WHERE public_id=:public"), {"public": command.parent_node_public_id}).scalar_one_or_none()
            if parent_id is None:
                raise SemanticAuthorityError("taxonomy_parent_not_found")
        try:
            self.session.execute(text("UPDATE semantic_taxonomy_placements SET effective_to=:to WHERE id=:id"), {"to": command.effective_from, "id": current.id})
            row = self.session.execute(text("""INSERT INTO semantic_taxonomy_placements
                (semantic_taxonomy_node_id,placement_version,parent_node_id,sort_order,effective_from,source_type,source_key,provenance)
                VALUES(:node,:version,:parent,:sort,:effective,:source_type,:source_key,CAST(:provenance AS jsonb))
                RETURNING *, (SELECT public_id FROM semantic_taxonomy_nodes WHERE id=parent_node_id) AS parent_node_public_id"""),
                {"node": node.id, "version": current.placement_version + 1, "parent": parent_id,
                 "sort": command.sort_order, "effective": command.effective_from,
                 "source_type": command.source_type.value, "source_key": command.source_key,
                 "provenance": json_dumps(command.provenance or {})}).one()
        except Exception as exc:
            raise SemanticAuthorityError("invalid_taxonomy_reparent") from exc
        self._complete(replay.id, "semantic_taxonomy_placements", row.id)
        return self._placement(row)

    def set_overlay(self, command: SetTenantTaxonomyOverlay, fingerprint: str) -> TenantTaxonomyOverlay:
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "set_tenant_taxonomy_overlay")
        if replay.result_id:
            row = self.session.execute(text("""SELECT o.*,parent.public_id AS parent_override_public_id FROM tenant_taxonomy_overlays o
                LEFT JOIN semantic_taxonomy_nodes parent ON parent.id=o.parent_override_node_id WHERE o.id=:id"""), {"id": replay.result_id}).one()
            return self._overlay(row)
        node = self.session.execute(text("SELECT * FROM semantic_taxonomy_nodes WHERE public_id=:public FOR UPDATE"), {"public": command.node_public_id}).first()
        if node is None or (node.tenant_id is not None and node.tenant_id != command.tenant_id):
            raise SemanticAuthorityError("taxonomy_node_not_visible_to_tenant")
        current = self.session.execute(text("""SELECT * FROM tenant_taxonomy_overlays
            WHERE tenant_id=:tenant AND semantic_taxonomy_node_id=:node AND effective_to IS NULL
            ORDER BY overlay_version DESC LIMIT 1 FOR UPDATE"""), {"tenant": command.tenant_id, "node": node.id}).first()
        expected = command.expected_overlay_version
        if (current is None and expected is not None) or (current is not None and current.overlay_version != expected):
            raise SemanticAuthorityError("taxonomy_overlay_not_found_or_concurrent_change")
        parent_id = None
        if command.parent_override_public_id is not None:
            parent_id = self.session.execute(text("SELECT id FROM semantic_taxonomy_nodes WHERE public_id=:public"), {"public": command.parent_override_public_id}).scalar_one_or_none()
            if parent_id is None:
                raise SemanticAuthorityError("taxonomy_parent_not_found")
        version = 1 if current is None else current.overlay_version + 1
        if current is not None:
            if command.effective_from <= current.effective_from:
                raise SemanticAuthorityError("taxonomy_overlay_change_must_be_prospective")
            self.session.execute(text("UPDATE tenant_taxonomy_overlays SET effective_to=:to WHERE id=:id"), {"to": command.effective_from, "id": current.id})
        try:
            row = self.session.execute(text("""INSERT INTO tenant_taxonomy_overlays
                (tenant_id,semantic_taxonomy_node_id,overlay_version,local_label,local_sort_order,parent_override_node_id,has_parent_override,is_suppressed,effective_from,source_type,source_key,provenance)
                VALUES(:tenant,:node,:version,:label,:sort,:parent,:has_parent_override,:suppressed,:effective,:source_type,:source_key,CAST(:provenance AS jsonb))
                RETURNING *, (SELECT public_id FROM semantic_taxonomy_nodes WHERE id=parent_override_node_id) AS parent_override_public_id"""),
                {"tenant": command.tenant_id, "node": node.id, "version": version,
                 "label": command.local_label.strip() if command.local_label else None,
                 "sort": command.local_sort_order, "parent": parent_id, "has_parent_override": command.has_parent_override,
                 "suppressed": command.is_suppressed,
                 "effective": command.effective_from, "source_type": command.source_type.value,
                 "source_key": command.source_key, "provenance": json_dumps(command.provenance or {})}).one()
        except Exception as exc:
            raise SemanticAuthorityError("invalid_tenant_taxonomy_overlay") from exc
        self._complete(replay.id, "tenant_taxonomy_overlays", row.id)
        return self._overlay(row)

    def clear_overlay(self, command: ClearTenantTaxonomyOverlay, fingerprint: str) -> None:
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "clear_tenant_taxonomy_overlay")
        if replay.result_id:
            return
        node = self.session.execute(text("SELECT id FROM semantic_taxonomy_nodes WHERE public_id=:public"), {"public": command.node_public_id}).scalar_one_or_none()
        if node is None:
            raise SemanticAuthorityError("taxonomy_node_not_found")
        current = self.session.execute(text("""SELECT * FROM tenant_taxonomy_overlays
            WHERE tenant_id=:tenant AND semantic_taxonomy_node_id=:node AND effective_to IS NULL
            ORDER BY overlay_version DESC LIMIT 1 FOR UPDATE"""), {"tenant": command.tenant_id, "node": node}).first()
        if current is None or current.overlay_version != command.expected_overlay_version:
            raise SemanticAuthorityError("taxonomy_overlay_not_found_or_concurrent_change")
        if command.effective_from <= current.effective_from:
            raise SemanticAuthorityError("taxonomy_overlay_change_must_be_prospective")
        self.session.execute(text("UPDATE tenant_taxonomy_overlays SET effective_to=:to WHERE id=:id"), {"to": command.effective_from, "id": current.id})
        self._complete(replay.id, "tenant_taxonomy_overlays", current.id)

    def assign(self, command: AssignSemanticClassification, fingerprint: str) -> ClassificationRecord:
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "assign_semantic_classification")
        if replay.result_id:
            return self._classification_record(replay.result_id)
        concept = self._concept(command.concept_qualified_code, command.classified_at, command.tenant_id)
        node_id = None
        if command.semantic_taxonomy_node_public_id is not None:
            node = self.session.execute(text("""SELECT * FROM semantic_taxonomy_nodes WHERE public_id=:public"""), {"public": command.semantic_taxonomy_node_public_id}).first()
            if node is None or (node.tenant_id is not None and node.tenant_id != command.tenant_id):
                raise SemanticAuthorityError("taxonomy_node_not_visible_to_tenant")
            if node.semantic_concept_id != concept.id:
                raise SemanticAuthorityError("classification_node_concept_mismatch")
            node_id = node.id
        try:
            assignment = self.session.execute(text("""INSERT INTO classification_assignments
                (tenant_id,subject_type,subject_key,concept_id,concept_version_id,taxonomy_node_id,classified_on,
                 concept_qualified_code_snapshot,concept_version_snapshot,definition_fingerprint_snapshot)
                VALUES(:tenant,lower(btrim(:target_type)),btrim(:target_key),:concept,:version,NULL,CAST(:classified AS date),:qualified,:version_number,:fingerprint)
                RETURNING id"""),
                {"tenant": command.tenant_id, "target_type": command.target_type, "target_key": command.target_key,
                 "concept": concept.id, "version": concept.version_id, "classified": self._semantic_date(command.classified_at),
                 "qualified": command.concept_qualified_code.lower(), "version_number": concept.version_number,
                 "fingerprint": concept.definition_fingerprint}).scalar_one()
            self.session.execute(text("""INSERT INTO semantic_classification_governance
                (assignment_id,semantic_taxonomy_node_id,assignment_mode,source_type,source_key,effective_from,provenance)
                VALUES(:assignment,:node,:mode,:source_type,:source_key,:effective,CAST(:provenance AS jsonb))"""),
                {"assignment": assignment, "node": node_id, "mode": command.assignment_mode.value,
                 "source_type": command.source_type.value, "source_key": command.source_key,
                 "effective": command.classified_at, "provenance": json_dumps(command.provenance or {})})
        except Exception as exc:
            raise SemanticAuthorityError("duplicate_or_conflicting_semantic_classification") from exc
        self._complete(replay.id, "classification_assignments", assignment)
        return self._classification_record(assignment)

    def end_assignment(self, command: EndSemanticClassification, fingerprint: str) -> ClassificationRecord:
        replay = self._command(command.tenant_id, command.command_key, fingerprint, "end_semantic_classification")
        if replay.result_id:
            return self._classification_record(replay.result_id)
        row = self.session.execute(text("""SELECT a.tenant_id,g.* FROM classification_assignments a
            JOIN semantic_classification_governance g ON g.assignment_id=a.id
            WHERE a.id=:id FOR UPDATE OF g"""), {"id": command.assignment_id}).first()
        if row is None or row.tenant_id != command.tenant_id or row.effective_from != command.expected_effective_from or row.effective_to is not None:
            raise SemanticAuthorityError("classification_not_found_or_concurrent_change")
        self.session.execute(text("UPDATE semantic_classification_governance SET effective_to=:to WHERE assignment_id=:id"), {"to": command.effective_to, "id": command.assignment_id})
        self._complete(replay.id, "classification_assignments", command.assignment_id)
        return self._classification_record(command.assignment_id)

    def _classification_record(self, assignment_id: int) -> ClassificationRecord:
        row = self.session.execute(text("""SELECT a.id,a.tenant_id,a.subject_type,a.subject_key,a.concept_qualified_code_snapshot,a.concept_version_snapshot,
                   a.definition_fingerprint_snapshot,g.semantic_taxonomy_node_id,n.public_id AS semantic_taxonomy_node_public_id,
                   g.assignment_mode,g.source_type,g.source_key,g.effective_from,g.effective_to,g.provenance
            FROM classification_assignments a JOIN semantic_classification_governance g ON g.assignment_id=a.id
            LEFT JOIN semantic_taxonomy_nodes n ON n.id=g.semantic_taxonomy_node_id WHERE a.id=:id"""), {"id": assignment_id}).one()
        return ClassificationRecord(
            row.id, row.tenant_id, row.subject_type, row.subject_key, row.concept_qualified_code_snapshot,
            row.concept_version_snapshot, row.definition_fingerprint_snapshot,
            UUID(str(row.semantic_taxonomy_node_public_id)) if row.semantic_taxonomy_node_public_id else None,
            AssignmentMode(row.assignment_mode), SemanticSource(row.source_type), row.source_key,
            row.effective_from, row.effective_to, dict(row.provenance or {}),
        )

    @staticmethod
    def _visible_source_sql(alias: str = "p") -> str:
        if alias not in {"p", "g"}:
            raise ValueError("invalid semantic source alias")
        return f"""({alias}.source_type IN ('kernel','finance','external','migration','tenant')
            OR ({alias}.source_type IN ('pack','template') AND {alias}.source_key = ANY(CAST(:sources AS text[]))))"""

    def hierarchy_rows(self, system_code: str, effective_at: datetime, tenant_id: int | None, active_sources: tuple[str, ...]) -> list[dict]:
        query = text(f"""SELECT n.public_id AS node_public_id,s.system_code,n.node_code,
                   ns.namespace_code||':'||c.code AS concept_qualified_code,
                   COALESCE(o.local_label,v.canonical_label) AS label,n.tenant_id,
                   CASE WHEN o.has_parent_override THEN op.public_id ELSE parent.public_id END AS parent_public_id,
                   COALESCE(o.local_sort_order,p.sort_order) AS sort_order,p.source_type,p.source_key,
                   (n.tenant_id IS NULL) AS inherited
            FROM semantic_taxonomy_nodes n
            JOIN taxonomy_systems s ON s.id=n.taxonomy_system_id
            JOIN semantic_concepts c ON c.id=n.semantic_concept_id
            JOIN semantic_namespaces ns ON ns.id=c.namespace_id
            JOIN semantic_versions v ON v.concept_id=c.id AND v.effective_from<=:semantic_date
              AND (v.effective_to IS NULL OR v.effective_to>=:semantic_date)
            JOIN semantic_taxonomy_placements p ON p.semantic_taxonomy_node_id=n.id
              AND p.effective_from<=:at AND (p.effective_to IS NULL OR :at<p.effective_to)
            LEFT JOIN semantic_taxonomy_nodes parent ON parent.id=p.parent_node_id
            LEFT JOIN tenant_taxonomy_overlays o ON :tenant IS NOT NULL AND o.tenant_id=:tenant AND o.semantic_taxonomy_node_id=n.id
              AND o.effective_from<=:at AND (o.effective_to IS NULL OR :at<o.effective_to)
              AND (o.source_type IN ('tenant','migration')
                   OR (o.source_type IN ('pack','template') AND o.source_key = ANY(CAST(:sources AS text[]))))
            LEFT JOIN semantic_taxonomy_nodes op ON op.id=o.parent_override_node_id
            WHERE s.system_code=:system AND n.lifecycle='active'
              AND (n.tenant_id IS NULL OR n.tenant_id=:tenant)
              AND ({self._visible_source_sql()})
              AND COALESCE(o.is_suppressed,false)=false
            ORDER BY COALESCE(o.local_sort_order,p.sort_order),n.node_code,n.public_id""")
        rows = self.session.execute(query, {"system": system_code, "at": effective_at, "semantic_date": self._semantic_date(effective_at), "tenant": tenant_id, "sources": list(active_sources)}).all()
        return [{
            "node_public_id": UUID(str(row.node_public_id)), "system_code": row.system_code,
            "node_code": row.node_code, "concept_qualified_code": row.concept_qualified_code,
            "label": row.label, "tenant_id": row.tenant_id,
            "parent_public_id": UUID(str(row.parent_public_id)) if row.parent_public_id else None,
            "sort_order": row.sort_order, "source_type": SemanticSource(row.source_type),
            "source_key": row.source_key, "inherited": row.inherited,
        } for row in rows]

    def classification_rows(self, tenant_id: int, target_type: str, target_key: str, effective_at: datetime, active_sources: tuple[str, ...]) -> list[dict]:
        rows = self.session.execute(text(f"""SELECT a.tenant_id,a.subject_type AS target_type,a.subject_key AS target_key,
                   s.system_code,n.public_id AS node_public_id,n.node_code,a.concept_qualified_code_snapshot,
                   a.concept_version_snapshot,v.canonical_label AS label,g.assignment_mode,g.source_type,g.source_key,
                   g.effective_from,g.effective_to,g.provenance
            FROM classification_assignments a JOIN semantic_classification_governance g ON g.assignment_id=a.id
            JOIN semantic_versions v ON v.id=a.concept_version_id
            LEFT JOIN semantic_taxonomy_nodes n ON n.id=g.semantic_taxonomy_node_id
            LEFT JOIN taxonomy_systems s ON s.id=n.taxonomy_system_id
            WHERE a.tenant_id=:tenant AND a.subject_type=:target_type AND a.subject_key=:target_key
              AND g.effective_from<=:at AND (g.effective_to IS NULL OR :at<g.effective_to)
              AND ({self._visible_source_sql("g")})
            ORDER BY COALESCE(s.system_code,''),a.concept_qualified_code_snapshot,a.id"""),
            {"tenant": tenant_id, "target_type": target_type, "target_key": target_key, "at": effective_at,
             "sources": list(active_sources)}).all()
        return [{
            "tenant_id": row.tenant_id, "target_type": row.target_type, "target_key": row.target_key,
            "system_code": row.system_code, "node_public_id": UUID(str(row.node_public_id)) if row.node_public_id else None,
            "node_code": row.node_code, "concept_qualified_code": row.concept_qualified_code_snapshot,
            "concept_version": row.concept_version_snapshot, "label": row.label,
            "assignment_mode": AssignmentMode(row.assignment_mode), "source_type": SemanticSource(row.source_type),
            "source_key": row.source_key, "effective_from": row.effective_from, "effective_to": row.effective_to,
            "provenance": dict(row.provenance or {}),
        } for row in rows]

    def graph_rows(self, node_public_id: UUID, effective_at: datetime, tenant_id: int | None, active_sources: tuple[str, ...]) -> dict[str, object]:
        if node_public_id.int == 0:
            systems = tuple(self.session.execute(text("SELECT system_code FROM taxonomy_systems WHERE lifecycle='active' ORDER BY system_code")).scalars())
            return {"systems": systems}
        node = self.session.execute(text("""SELECT n.id,n.public_id,n.semantic_concept_id,s.system_code FROM semantic_taxonomy_nodes n
            JOIN taxonomy_systems s ON s.id=n.taxonomy_system_id WHERE n.public_id=:public"""), {"public": node_public_id}).first()
        if node is None:
            raise SemanticAuthorityError("taxonomy_node_not_found")
        hierarchy = self.hierarchy_rows(node.system_code, effective_at, tenant_id, active_sources)
        visible = {row["node_public_id"]: row for row in hierarchy}
        selected = visible.get(UUID(str(node.public_id)))
        if selected is None:
            raise SemanticAuthorityError("taxonomy_node_not_visible")
        children = tuple(str(row["node_public_id"]) for row in hierarchy if row["parent_public_id"] == selected["node_public_id"])
        mappings = tuple(dict(row._mapping) for row in self.session.execute(text("""SELECT ms.mapping_set_code,m.mapping_type,
                   sn.namespace_code||':'||sc.code AS source_qualified_code,tn.namespace_code||':'||tc.code AS target_qualified_code
            FROM semantic_mappings m JOIN semantic_mapping_sets ms ON ms.id=m.mapping_set_id
            JOIN semantic_concepts sc ON sc.id=m.source_concept_id JOIN semantic_namespaces sn ON sn.id=sc.namespace_id
            JOIN semantic_concepts tc ON tc.id=m.target_concept_id JOIN semantic_namespaces tn ON tn.id=tc.namespace_id
            WHERE (m.source_concept_id=:concept OR m.target_concept_id=:concept)
              AND m.effective_from<=:semantic_date AND (m.effective_to IS NULL OR m.effective_to>=:semantic_date)
            ORDER BY ms.mapping_set_code,m.id"""), {"concept": node.semantic_concept_id, "semantic_date": self._semantic_date(effective_at)}))
        return {
            "node": str(selected["node_public_id"]),
            "system_code": node.system_code,
            "parent": str(selected["parent_public_id"]) if selected["parent_public_id"] else None,
            "children": children,
            "mappings": mappings,
        }

    def health_rows(self, effective_at: datetime, tenant_id: int | None, active_sources: tuple[str, ...]) -> list[HealthIssue]:
        issues: list[HealthIssue] = []
        missing = self.session.execute(text("""SELECT n.public_id,s.system_code FROM semantic_taxonomy_nodes n
            JOIN taxonomy_systems s ON s.id=n.taxonomy_system_id
            WHERE n.lifecycle='active' AND (n.tenant_id IS NULL OR n.tenant_id=:tenant)
              AND NOT EXISTS (SELECT 1 FROM semantic_taxonomy_placements p WHERE p.semantic_taxonomy_node_id=n.id
                AND p.effective_from<=:at AND (p.effective_to IS NULL OR :at<p.effective_to))
            ORDER BY s.system_code,n.public_id"""), {"tenant": tenant_id, "at": effective_at}).all()
        for row in missing:
            issues.append(HealthIssue(HealthSeverity.ERROR, "missing_effective_placement", "semantic_taxonomy_node", str(row.public_id), row.system_code,
                "Active semantic taxonomy node has no effective placement.", "Create a governed effective placement or retire the node."))
        legacy = self.session.execute(text("""SELECT count(*) FROM classification_assignments a
            LEFT JOIN semantic_classification_governance g ON g.assignment_id=a.id
            WHERE g.assignment_id IS NULL AND (:tenant IS NULL OR a.tenant_id=:tenant)"""), {"tenant": tenant_id}).scalar_one()
        if legacy:
            issues.append(HealthIssue(HealthSeverity.INFO, "legacy_pc3_assignments_without_hardening_governance", "classification_assignment", str(legacy), None,
                "Frozen PC3 assignments predate hardening provenance/effective governance.", "Map legacy assignments during the owning tenant/pack migration; do not rewrite historical meaning silently."))
        return issues


def json_dumps(value: dict[str, Any]) -> str:
    import json
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
