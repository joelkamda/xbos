"""PostgreSQL repository for PK4-PK6 conformance and template authority."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import text

from .pk456_contracts import *
from .pk456_service import PK456AuthorityError, _primitive


class SQLPK456Repository:
    def __init__(self, session):
        self.session = session

    def _command(self, scope: str, key: str, fingerprint: str, command_type: str):
        self.session.execute(text("""INSERT INTO pk_pack_commands(scope_key,command_key,request_fingerprint,command_type)
            VALUES(:s,:k,:f,:t) ON CONFLICT(scope_key,command_key) DO NOTHING"""), {"s": scope, "k": key, "f": fingerprint, "t": command_type})
        row = self.session.execute(text("SELECT * FROM pk_pack_commands WHERE scope_key=:s AND command_key=:k FOR UPDATE"), {"s": scope, "k": key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise PK456AuthorityError("PK456_COMMAND_CONFLICT")
        return row

    def template_command_replay(self, tenant_id: int, command_key: str, fingerprint: str, command_type: str):
        scope = f"tenant:{tenant_id}"
        row = self.session.execute(text("SELECT * FROM pk_pack_commands WHERE scope_key=:s AND command_key=:k FOR UPDATE"), {"s": scope, "k": command_key}).first()
        if row is None:
            return None
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise PK456AuthorityError("PK456_COMMAND_CONFLICT")
        if row.result_id:
            return self._state_by_id(row.result_id)
        return None

    def _complete(self, scope: str, key: str, result_table: str, result_id: int):
        self.session.execute(text("UPDATE pk_pack_commands SET result_table=:t,result_id=:i,completed_at=now() WHERE scope_key=:s AND command_key=:k"), {"t": result_table, "i": result_id, "s": scope, "k": key})

    def pack_version(self, code: str, version: str):
        row = self.session.execute(text("""SELECT v.id,v.public_id,v.manifest_sha256,v.manifest_json,p.pack_code,v.pack_version
            FROM pk_pack_versions v JOIN pk_packs p ON p.id=v.pack_id
            WHERE p.pack_code=:c AND v.pack_version=:v"""), {"c": code, "v": version}).mappings().first()
        return None if row is None else dict(row)

    def certify(self, command_key, fingerprint, code, version, certification_code, suite_version, manifest_sha256, evidence_sha256, checks, notes):
        scope = "registry:certification"
        replay = self._command(scope, command_key, fingerprint, "certify_pack")
        if replay.result_id:
            return self._cert_record(self.session.execute(text("""SELECT c.*,p.pack_code,v.pack_version FROM pk_pack_certifications c
                JOIN pk_pack_versions v ON v.id=c.pack_version_id JOIN pk_packs p ON p.id=v.pack_id WHERE c.id=:i"""), {"i": replay.result_id}).one())
        pack = self.pack_version(code, version)
        if pack is None:
            raise PK456AuthorityError("PK456_PACK_VERSION_NOT_FOUND")
        if pack["manifest_sha256"] != manifest_sha256:
            raise PK456AuthorityError("PK456_MANIFEST_HASH_DRIFT")
        row = self.session.execute(text("""INSERT INTO pk_pack_certifications(pack_version_id,certification_code,suite_version,manifest_sha256,evidence_sha256,result,checks_json,notes_json)
            VALUES(:v,:c,:s,:m,:e,'pass',CAST(:checks AS jsonb),CAST(:notes AS jsonb)) RETURNING id"""), {
                "v": pack["id"], "c": certification_code, "s": suite_version, "m": manifest_sha256, "e": evidence_sha256,
                "checks": json.dumps(_primitive(checks), sort_keys=True), "notes": json.dumps(_primitive(notes), sort_keys=True),
            }).one()
        self._complete(scope, command_key, "pk_pack_certifications", row.id)
        return self._cert_record(self.session.execute(text("""SELECT c.*,p.pack_code,v.pack_version FROM pk_pack_certifications c
            JOIN pk_pack_versions v ON v.id=c.pack_version_id JOIN pk_packs p ON p.id=v.pack_id WHERE c.id=:i"""), {"i": row.id}).one())

    def _cert_record(self, row):
        return PackCertificationRecord(row.public_id, row.pack_code, row.pack_version, row.certification_code, row.suite_version, row.manifest_sha256, row.evidence_sha256, ConformanceResult(row.result))

    def is_certified(self, code: str, version: str) -> bool:
        return bool(self.session.execute(text("""SELECT EXISTS(SELECT 1 FROM pk_pack_certifications c
            JOIN pk_pack_versions v ON v.id=c.pack_version_id JOIN pk_packs p ON p.id=v.pack_id
            WHERE p.pack_code=:c AND v.pack_version=:v AND c.result='pass')"""), {"c": code, "v": version}).scalar_one())

    def register_template(self, command_key, fingerprint, template: TemplateDefinition, canonical: str, template_sha256: str):
        scope = "registry:template"
        replay = self._command(scope, command_key, fingerprint, "register_template")
        if replay.result_id:
            return self._template_record(self.session.execute(text("""SELECT v.*,t.template_code,t.owner_code FROM pk_template_versions v JOIN pk_templates t ON t.id=v.template_id WHERE v.id=:i"""), {"i": replay.result_id}).one())
        root = self.session.execute(text("SELECT * FROM pk_templates WHERE template_code=:c FOR UPDATE"), {"c": template.template_code}).first()
        if root is None:
            root = self.session.execute(text("INSERT INTO pk_templates(template_code,owner_code) VALUES(:c,:o) RETURNING *"), {"c": template.template_code, "o": template.owner_code}).one()
        elif root.owner_code != template.owner_code:
            raise PK456AuthorityError("PK456_TEMPLATE_OWNER_CONFLICT")
        existing = self.session.execute(text("SELECT * FROM pk_template_versions WHERE template_id=:t AND template_version=:v"), {"t": root.id, "v": template.version}).first()
        if existing:
            if existing.template_sha256 != template_sha256:
                raise PK456AuthorityError("PK456_TEMPLATE_VERSION_IMMUTABLE")
            self._complete(scope, command_key, "pk_template_versions", existing.id)
            return self._template_record(self.session.execute(text("""SELECT v.*,t.template_code,t.owner_code FROM pk_template_versions v JOIN pk_templates t ON t.id=v.template_id WHERE v.id=:i"""), {"i": existing.id}).one())
        row = self.session.execute(text("""INSERT INTO pk_template_versions(template_id,template_version,industry_semantic_ref,operating_model_semantic_ref,template_json,template_sha256,allowed_override_paths,configuration_defaults,terminology_json,xa_json,semantic_references,finance_workspace_exposed,finance_kernel_required)
            VALUES(:t,:v,:i,:o,CAST(:j AS jsonb),:sha,:paths,CAST(:cfg AS jsonb),CAST(:term AS jsonb),CAST(:xa AS jsonb),:sem,:fw,true) RETURNING *"""), {
                "t": root.id, "v": template.version, "i": template.industry_semantic_ref, "o": template.operating_model_semantic_ref,
                "j": canonical, "sha": template_sha256, "paths": list(template.allowed_override_paths),
                "cfg": json.dumps(_primitive(template.configuration_defaults), sort_keys=True), "term": json.dumps(template.terminology, sort_keys=True),
                "xa": json.dumps(_primitive(template.xa), sort_keys=True), "sem": list(template.semantic_references), "fw": template.finance_workspace_exposed,
            }).one()
        for requirement in template.requirements:
            self.session.execute(text("""INSERT INTO pk_template_pack_requirements(template_version_id,pack_code,pack_version,requirement_kind)
                VALUES(:i,:c,:v,:k)"""), {"i": row.id, "c": requirement.pack_code, "v": requirement.version, "k": requirement.kind.value})
        self._complete(scope, command_key, "pk_template_versions", row.id)
        return self._template_record(self.session.execute(text("""SELECT v.*,t.template_code,t.owner_code FROM pk_template_versions v JOIN pk_templates t ON t.id=v.template_id WHERE v.id=:i"""), {"i": row.id}).one())

    def _template_record(self, row):
        return TemplateVersionRecord(row.public_id, row.template_code, row.template_version, row.owner_code, row.template_sha256, row.industry_semantic_ref, row.operating_model_semantic_ref)

    @staticmethod
    def _template_projection(row):
        """Normalize persistence column names to the PK456 public template contract."""
        data = dict(row)
        data["version"] = data["template_version"]
        data["xa"] = data.get("xa_json") or {}
        data["terminology"] = data.get("terminology_json") or {}
        return data

    def template_version(self, code: str, version: str):
        row = self.session.execute(text("""SELECT v.*,t.template_code,t.owner_code FROM pk_template_versions v JOIN pk_templates t ON t.id=v.template_id
            WHERE t.template_code=:c AND v.template_version=:v"""), {"c": code, "v": version}).mappings().first()
        if row is None:
            return None
        data = self._template_projection(row)
        data["requirements"] = [dict(x) for x in self.session.execute(text("SELECT pack_code,pack_version AS version,requirement_kind AS kind FROM pk_template_pack_requirements WHERE template_version_id=:i ORDER BY pack_code,requirement_kind"), {"i": row["id"]}).mappings().all()]
        return data

    def pack_installation(self, tenant_id: int, code: str):
        row = self.session.execute(text("""SELECT i.lifecycle_status AS status,v.pack_version AS version FROM pk_tenant_pack_installations i
            JOIN pk_packs p ON p.id=i.pack_id JOIN pk_pack_versions v ON v.id=i.pack_version_id
            WHERE i.tenant_id=:t AND p.pack_code=:c"""), {"t": tenant_id, "c": code}).mappings().first()
        return None if row is None else dict(row)

    def apply_template(self, command: ApplyTemplate, fingerprint: str, plan: TemplatePlan) -> TenantTemplateState:
        scope = f"tenant:{command.tenant_id}"
        replay = self._command(scope, command.command_key, fingerprint, "apply_template")
        if replay.result_id:
            return self._state_by_id(replay.result_id)
        if self.tenant_template(command.tenant_id, command.template_code) is not None:
            raise PK456AuthorityError("PK456_TEMPLATE_ALREADY_APPLIED")
        target = self.template_version(command.template_code, command.version)
        row = self.session.execute(text("""INSERT INTO pk_tenant_template_bindings(tenant_id,template_id,template_version_id,selected_optional_packs,applied_plan_sha256)
            VALUES(:tenant,:template,:version,:optional,:plan) RETURNING id"""), {
                "tenant": command.tenant_id, "template": target["template_id"], "version": target["id"],
                "optional": list(command.selected_optional_packs), "plan": plan.plan_sha256,
            }).one()
        for path, value in sorted(plan.preserved_overrides.items()):
            self.session.execute(text("""INSERT INTO pk_tenant_template_overrides(tenant_id,binding_id,override_path,override_json)
                VALUES(:t,:b,:p,CAST(:v AS jsonb))"""), {"t": command.tenant_id, "b": row.id, "p": path, "v": json.dumps(_primitive(value), sort_keys=True)})
        self.session.execute(text("""INSERT INTO pk_tenant_template_history(tenant_id,binding_id,sequence,action,from_template_version_id,to_template_version_id,plan_sha256,command_key,reason)
            VALUES(:t,:b,1,'apply',NULL,:v,:p,:k,'initial application')"""), {"t": command.tenant_id, "b": row.id, "v": target["id"], "p": plan.plan_sha256, "k": command.command_key})
        self._complete(scope, command.command_key, "pk_tenant_template_bindings", row.id)
        return self._state_by_id(row.id)

    def upgrade_template(self, command: UpgradeTemplate, fingerprint: str, plan: TemplatePlan) -> TenantTemplateState:
        scope = f"tenant:{command.tenant_id}"
        replay = self._command(scope, command.command_key, fingerprint, "upgrade_template")
        if replay.result_id:
            return self._state_by_id(replay.result_id)
        state = self._binding_row(command.tenant_id, command.template_code, lock=True)
        if state is None:
            raise PK456AuthorityError("PK456_TEMPLATE_NOT_APPLIED")
        if state.row_version != command.expected_row_version:
            raise PK456AuthorityError("PK456_CONCURRENT_CHANGE")
        target = self.template_version(command.template_code, command.target_version)
        old_id = state.template_version_id
        self.session.execute(text("""UPDATE pk_tenant_template_bindings SET template_version_id=:v,row_version=row_version+1,upgraded_at=now(),applied_plan_sha256=:p
            WHERE id=:i"""), {"v": target["id"], "p": plan.plan_sha256, "i": state.id})
        allowed = set(target["allowed_override_paths"])
        self.session.execute(text("DELETE FROM pk_tenant_template_overrides WHERE binding_id=:b AND NOT (override_path = ANY(:allowed))"), {"b": state.id, "allowed": list(allowed)})
        seq = self.session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM pk_tenant_template_history WHERE tenant_id=:t AND binding_id=:b"), {"t": command.tenant_id, "b": state.id}).scalar_one()
        self.session.execute(text("""INSERT INTO pk_tenant_template_history(tenant_id,binding_id,sequence,action,from_template_version_id,to_template_version_id,plan_sha256,command_key,reason)
            VALUES(:t,:b,:s,'upgrade',:f,:to,:p,:k,:r)"""), {"t": command.tenant_id, "b": state.id, "s": seq, "f": old_id, "to": target["id"], "p": plan.plan_sha256, "k": command.command_key, "r": command.reason})
        self._complete(scope, command.command_key, "pk_tenant_template_bindings", state.id)
        return self._state_by_id(state.id)

    def _binding_row(self, tenant_id: int, template_code: str, lock: bool = False):
        suffix = " FOR UPDATE" if lock else ""
        return self.session.execute(text("""SELECT b.*,t.template_code FROM pk_tenant_template_bindings b JOIN pk_templates t ON t.id=b.template_id
            WHERE b.tenant_id=:tenant AND t.template_code=:code""" + suffix), {"tenant": tenant_id, "code": template_code}).first()

    def tenant_template(self, tenant_id: int, template_code: str):
        row = self._binding_row(tenant_id, template_code)
        return None if row is None else self._state_by_id(row.id)

    def selected_optional_packs(self, tenant_id: int, template_code: str):
        row = self._binding_row(tenant_id, template_code)
        return () if row is None else tuple(row.selected_optional_packs or ())

    def _state_by_id(self, binding_id: int) -> TenantTemplateState:
        row = self.session.execute(text("""SELECT b.id,b.public_id,b.tenant_id,b.row_version,t.template_code,v.template_version,v.template_sha256,v.configuration_defaults
            FROM pk_tenant_template_bindings b JOIN pk_templates t ON t.id=b.template_id JOIN pk_template_versions v ON v.id=b.template_version_id
            WHERE b.id=:i"""), {"i": binding_id}).mappings().one()
        overrides = {x["override_path"]: x["override_json"] for x in self.session.execute(text("SELECT override_path,override_json FROM pk_tenant_template_overrides WHERE binding_id=:b ORDER BY override_path"), {"b": binding_id}).mappings().all()}
        defaults = dict(row["configuration_defaults"] or {})
        from .pk456_service import _merge_configuration
        return TenantTemplateState(row["public_id"], row["tenant_id"], row["template_code"], row["template_version"], row["row_version"], row["template_sha256"], overrides, _merge_configuration(defaults, overrides))
