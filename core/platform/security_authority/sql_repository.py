"""SQLAlchemy persistence boundary for PC5 security authority."""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from .contracts import *
from .service import SecurityAuthorityError


class SQLSecurityRepository:
    def __init__(self, session): self.db_session = session

    def _command(self, key, fingerprint, kind):
        self.db_session.execute(text("INSERT INTO security_commands(command_key,request_fingerprint,command_type) VALUES(:k,:f,:t) ON CONFLICT(command_key) DO NOTHING"), {"k": key, "f": fingerprint, "t": kind})
        row = self.db_session.execute(text("SELECT * FROM security_commands WHERE command_key=:k FOR UPDATE"), {"k": key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != kind: raise SecurityAuthorityError("conflicting_security_command")
        return row

    def _complete(self, key, table, result_id):
        self.db_session.execute(text("UPDATE security_commands SET result_table=:t,result_id=:i,completed_at=now() WHERE command_key=:k"), {"t": table, "i": result_id, "k": key})

    def create_identity(self, key, fingerprint, login, party_id):
        replay = self._command(key, fingerprint, "create_identity")
        if replay.result_id: row = self.db_session.execute(text("SELECT * FROM identities WHERE id=:i"), {"i": replay.result_id}).one()
        else:
            try: row = self.db_session.execute(text("INSERT INTO identities(login_name,party_id) VALUES(:login,:party) RETURNING *"), {"login": login, "party": party_id}).one()
            except Exception as exc: raise SecurityAuthorityError("duplicate_identity") from exc
            self._complete(key, "identities", row.id)
        return Identity(row.id, row.public_id, row.login_name, Lifecycle(row.status), row.party_id)

    def add_membership(self, key, fingerprint, identity, tenant, start, end, party):
        replay = self._command(key, fingerprint, "add_membership")
        if replay.result_id: row = self.db_session.execute(text("SELECT * FROM identity_memberships WHERE id=:i"), {"i": replay.result_id}).one()
        else:
            try: row = self.db_session.execute(text("INSERT INTO identity_memberships(identity_id,tenant_id,party_id,valid_from,valid_to) VALUES(:identity,:tenant,:party,:start,:end) RETURNING *"), {"identity": identity, "tenant": tenant, "party": party, "start": start, "end": end}).one()
            except Exception as exc: raise SecurityAuthorityError("duplicate_or_invalid_membership") from exc
            self._complete(key, "identity_memberships", row.id)
        return Membership(row.id, row.identity_id, row.tenant_id, Lifecycle(row.status), row.valid_from, row.valid_to, row.party_id)

    def register_permission(self, key, fingerprint, definition):
        replay = self._command(key, fingerprint, "register_permission")
        if not replay.result_id:
            try: row = self.db_session.execute(text("""INSERT INTO permission_definitions(permission_code,owner_module,resource_code,action_code,risk_class,allowed_scopes,required_assurance,approval_profile)
                VALUES(:code,:owner,:resource,:action,:risk,:scopes,:assurance,:approval) RETURNING id"""), {"code": definition.code, "owner": definition.owner_module, "resource": definition.resource, "action": definition.action, "risk": definition.risk_class, "scopes": [x.value for x in definition.allowed_scopes], "assurance": definition.required_assurance, "approval": definition.approval_profile}).one()
            except Exception as exc: raise SecurityAuthorityError("duplicate_or_conflicting_permission") from exc
            self._complete(key, "permission_definitions", row.id)
        return self.permission(definition.code)

    def permission(self, code):
        row = self.db_session.execute(text("SELECT * FROM permission_definitions WHERE permission_code=:c AND status='active'"), {"c": code}).first()
        if row is None: return None
        return PermissionDefinition(row.permission_code, row.owner_module, row.resource_code, row.action_code, row.risk_class, tuple(ScopeType(x) for x in row.allowed_scopes), row.required_assurance, row.approval_profile)

    def create_role(self, key, fingerprint, role, tenant, permissions):
        replay = self._command(key, fingerprint, "create_role")
        if replay.result_id: return replay.result_id
        try:
            row = self.db_session.execute(text("INSERT INTO authorization_roles(role_code,tenant_id) VALUES(:role,:tenant) RETURNING id"), {"role": role, "tenant": tenant}).one()
            for permission in permissions: self.db_session.execute(text("INSERT INTO authorization_role_permissions(role_id,permission_id) SELECT :role,id FROM permission_definitions WHERE permission_code=:permission"), {"role": row.id, "permission": permission})
        except Exception as exc: raise SecurityAuthorityError("duplicate_or_invalid_authorization_role") from exc
        self._complete(key, "authorization_roles", row.id); return row.id

    def assign_role(self, key, fingerprint, assignment):
        replay = self._command(key, fingerprint, "assign_role")
        if replay.result_id: return replay.result_id
        try: row = self.db_session.execute(text("""INSERT INTO scoped_role_assignments(principal_id,actor_type,tenant_id,role_id,scope_type,scope_id,valid_from,valid_to)
            SELECT :identity,:actor,:tenant,id,:scope,:scope_id,:start,:end FROM authorization_roles WHERE role_code=:role AND tenant_id IS NOT DISTINCT FROM :tenant RETURNING id"""), {"identity": assignment.identity_id, "actor": assignment.actor_type.value, "tenant": assignment.tenant_id, "role": assignment.role_code, "scope": assignment.scope.scope_type.value, "scope_id": assignment.scope.scope_id, "start": assignment.valid_from, "end": assignment.valid_to}).one()
        except Exception as exc: raise SecurityAuthorityError("duplicate_or_invalid_role_assignment") from exc
        self._complete(key, "scoped_role_assignments", row.id); return row.id

    def create_session(self, key, fingerprint, identity, tenant, actor_type, assurance, start, end, device):
        replay = self._command(key, fingerprint, "create_session")
        if replay.result_id: row = self.db_session.execute(text("SELECT * FROM authentication_sessions WHERE id=:i"), {"i": replay.result_id}).one()
        else:
            try: row = self.db_session.execute(text("INSERT INTO authentication_sessions(principal_id,tenant_id,actor_type,assurance_level,authenticated_at,expires_at,device_identity_id) VALUES(:identity,:tenant,:actor,:assurance,:start,:end,:device) RETURNING *"), {"identity": identity, "tenant": tenant, "actor": actor_type.value, "assurance": assurance, "start": start, "end": end, "device": device}).one()
            except Exception as exc: raise SecurityAuthorityError("invalid_session") from exc
            self._complete(key, "authentication_sessions", row.id)
        return self._session(row)

    def session(self, public_id):
        row = self.db_session.execute(text("SELECT * FROM authentication_sessions WHERE public_id=:id"), {"id": str(public_id)}).first()
        return self._session(row) if row else None

    @staticmethod
    def _session(row): return SessionContext(row.id, row.public_id, row.principal_id, row.tenant_id, ActorType(row.actor_type), row.assurance_level, row.authenticated_at, row.expires_at, row.revoked_at, row.device_identity_id)

    def revoke_session(self, public_id, at):
        row = self.db_session.execute(text("UPDATE authentication_sessions SET revoked_at=COALESCE(revoked_at,:at),revocation_version=revocation_version+1 WHERE public_id=:id RETURNING *"), {"at": at, "id": str(public_id)}).first()
        if row is None: raise SecurityAuthorityError("session_not_found")
        return self._session(row)

    def membership_active(self, identity, tenant, at):
        return bool(self.db_session.execute(text("SELECT 1 FROM identity_memberships WHERE identity_id=:identity AND tenant_id=:tenant AND status='active' AND valid_from<=:at AND (valid_to IS NULL OR valid_to>:at)"), {"identity": identity, "tenant": tenant, "at": at}).scalar_one_or_none())

    def revoke_membership(self, identity, tenant, at):
        row = self.db_session.execute(text("UPDATE identity_memberships SET status='revoked',revoked_at=:at WHERE identity_id=:identity AND tenant_id=:tenant AND status<>'revoked' RETURNING id"), {"identity": identity, "tenant": tenant, "at": at}).first()
        if row is None: raise SecurityAuthorityError("membership_not_found_or_revoked")
        self.db_session.execute(text("UPDATE authentication_sessions SET revoked_at=COALESCE(revoked_at,:at),revocation_version=revocation_version+1 WHERE principal_id=:identity AND actor_type='human' AND tenant_id=:tenant"), {"identity": identity, "tenant": tenant, "at": at})
        return row.id

    def grant_step_up(self, key, fingerprint, session_id, assurance, expires, scope):
        replay = self._command(key, fingerprint, "grant_step_up")
        if replay.result_id: return replay.result_id
        row = self.db_session.execute(text("INSERT INTO step_up_grants(session_id,assurance_level,scope_type,scope_id,expires_at) SELECT id,:assurance,:scope,:scope_id,:expires FROM authentication_sessions WHERE public_id=:session AND revoked_at IS NULL RETURNING id"), {"assurance": assurance, "scope": scope.scope_type.value if scope else None, "scope_id": scope.scope_id if scope else None, "expires": expires, "session": str(session_id)}).first()
        if row is None: raise SecurityAuthorityError("inactive_session_step_up")
        self._complete(key, "step_up_grants", row.id); return row.id

    def step_up_assurance(self, session_id, scope, at):
        return int(self.db_session.execute(text("SELECT COALESCE(max(g.assurance_level),0) FROM step_up_grants g JOIN authentication_sessions s ON s.id=g.session_id WHERE s.public_id=:session AND g.revoked_at IS NULL AND g.expires_at>:at AND (g.scope_type IS NULL OR (g.scope_type=:scope AND g.scope_id=:scope_id))"), {"session": str(session_id), "at": at, "scope": scope.scope_type.value, "scope_id": scope.scope_id}).scalar_one())

    def register_service_identity(self, key, fingerprint, code, owner, tenant, reference):
        replay = self._command(key, fingerprint, "register_service_identity")
        if replay.result_id: row = self.db_session.execute(text("SELECT * FROM service_identities WHERE id=:id"), {"id": replay.result_id}).one()
        else:
            row = self.db_session.execute(text("INSERT INTO service_identities(service_code,owner_module,tenant_id,credential_reference) VALUES(:code,:owner,:tenant,:reference) RETURNING *"), {"code": code, "owner": owner, "tenant": tenant, "reference": reference}).one()
            self._complete(key, "service_identities", row.id)
        return ServiceIdentity(row.id, row.public_id, row.service_code, row.owner_module, row.tenant_id, Lifecycle(row.status), row.credential_reference)

    def register_device_identity(self, key, fingerprint, code, tenant, location, organization, assurance):
        replay = self._command(key, fingerprint, "register_device_identity")
        if replay.result_id: row = self.db_session.execute(text("SELECT * FROM device_identities WHERE id=:id"), {"id": replay.result_id}).one()
        else:
            row = self.db_session.execute(text("INSERT INTO device_identities(device_code,tenant_id,location_id,organization_unit_id,assurance_level) VALUES(:code,:tenant,:location,:organization,:assurance) RETURNING *"), {"code": code, "tenant": tenant, "location": location, "organization": organization, "assurance": assurance}).one()
            self._complete(key, "device_identities", row.id)
        return DeviceIdentity(row.id, row.public_id, row.device_code, row.tenant_id, Lifecycle(row.status), row.location_id, row.organization_unit_id, row.assurance_level)

    def principal_active(self, actor_type, principal, tenant):
        table = "service_identities" if actor_type is ActorType.SERVICE else "device_identities"
        return bool(self.db_session.execute(text(f"SELECT 1 FROM {table} WHERE id=:id AND tenant_id IS NOT DISTINCT FROM :tenant AND status='active' AND revoked_at IS NULL"), {"id": principal, "tenant": tenant}).scalar_one_or_none())

    def assignments(self, identity, tenant, at, actor_type=ActorType.HUMAN):
        rows = self.db_session.execute(text("""SELECT a.scope_type,a.scope_id,array_agg(p.permission_code ORDER BY p.permission_code) permissions
            FROM scoped_role_assignments a JOIN authorization_roles r ON r.id=a.role_id JOIN authorization_role_permissions rp ON rp.role_id=r.id JOIN permission_definitions p ON p.id=rp.permission_id
            WHERE a.principal_id=:identity AND a.actor_type=:actor AND a.tenant_id IS NOT DISTINCT FROM :tenant AND a.status='active' AND r.status='active' AND p.status='active'
            AND a.valid_from<=:at AND (a.valid_to IS NULL OR a.valid_to>:at) GROUP BY a.id,a.scope_type,a.scope_id"""), {"identity": identity, "actor": actor_type.value, "tenant": tenant, "at": at}).all()
        return [{"scope": StructuralScope(ScopeType(x.scope_type), x.scope_id), "permissions": tuple(x.permissions)} for x in rows]

    def policy(self, permission, tenant, at):
        rows = self.db_session.execute(text("SELECT required_assurance,approval_profile FROM authorization_policies WHERE permission_code=:p AND (tenant_id=:t OR tenant_id IS NULL) AND status='active' AND effective_from<=:at AND (effective_to IS NULL OR effective_to>:at) ORDER BY tenant_id NULLS LAST"), {"p": permission, "t": tenant, "at": at}).all()
        if len(rows) > 1 and rows[0].required_assurance != rows[1].required_assurance: raise SecurityAuthorityError("ambiguous_authorization_policy")
        return dict(rows[0]._mapping) if rows else None

    def grant_support_access(self, grant, fingerprint):
        try:row=self.db_session.execute(text("""INSERT INTO support_access_grants(public_id,operator_identity_id,tenant_id,permission_code,scope_type,scope_id,effective_from,expires_at,reason,approval_public_id,break_glass,grant_fingerprint)
          VALUES(:id,:operator,:tenant,:permission,:scope,:scope_id,:start,:end,:reason,:approval,:break_glass,:fingerprint) RETURNING id"""),{"id":str(grant.public_id),"operator":grant.operator_identity_id,"tenant":grant.tenant_id,"permission":grant.permission_code,"scope":grant.scope.scope_type.value,"scope_id":grant.scope.scope_id,"start":grant.effective_from,"end":grant.expires_at,"reason":grant.reason,"approval":str(grant.approval_id),"break_glass":grant.break_glass,"fingerprint":fingerprint}).one()
        except Exception as exc:raise SecurityAuthorityError("duplicate_or_invalid_support_access") from exc
        return row.id

    def revoke_support_access(self,public_id,at):
        row=self.db_session.execute(text("UPDATE support_access_grants SET revoked_at=COALESCE(revoked_at,:at) WHERE public_id=:id RETURNING id"),{"id":str(public_id),"at":at}).first()
        if row is None:raise SecurityAuthorityError("support_access_not_found")
        return row.id

    def delegation_active(self,public_id,operator,tenant,permission,scope,at):
        if public_id is None:return False
        return bool(self.db_session.execute(text("""SELECT 1 FROM support_access_grants WHERE public_id=:id AND operator_identity_id=:operator AND tenant_id=:tenant AND permission_code=:permission
          AND scope_type=:scope AND scope_id=:scope_id AND effective_from<=:at AND expires_at>:at AND revoked_at IS NULL"""),{"id":str(public_id),"operator":operator,"tenant":tenant,"permission":permission,"scope":scope.scope_type.value,"scope_id":scope.scope_id,"at":at}).scalar_one_or_none())

    def request_approval(self, request, fingerprint):
        try: row = self.db_session.execute(text("""INSERT INTO protected_action_approvals(public_id,tenant_id,requester_identity_id,permission_code,action_fingerprint,scope_type,scope_id,required_approvals,expires_at,request_fingerprint)
            VALUES(:id,:tenant,:requester,:permission,:fingerprint,:scope,:scope_id,:required,:expires,:request) RETURNING id"""), {"id": str(request.public_id), "tenant": request.tenant_id, "requester": request.requester_identity_id, "permission": request.permission_code, "fingerprint": request.action_fingerprint, "scope": request.scope.scope_type.value, "scope_id": request.scope.scope_id, "required": request.required_approvals, "expires": request.expires_at, "request": fingerprint}).one()
        except Exception as exc: raise SecurityAuthorityError("duplicate_or_invalid_approval") from exc
        return row.id

    def decide_approval(self, decision, fingerprint):
        approval = self.db_session.execute(text("SELECT * FROM protected_action_approvals WHERE public_id=:id FOR UPDATE"), {"id": str(decision.approval_id)}).first()
        if approval is None: raise SecurityAuthorityError("approval_not_found")
        if approval.requester_identity_id == decision.approver_identity_id: raise SecurityAuthorityError("approval_separation_required")
        try: row = self.db_session.execute(text("INSERT INTO approval_decisions(approval_id,approver_identity_id,approved,reason,decided_at,decision_fingerprint) VALUES(:approval,:approver,:approved,:reason,:at,:fingerprint) RETURNING id"), {"approval": approval.id, "approver": decision.approver_identity_id, "approved": decision.approved, "reason": decision.reason, "at": decision.decided_at, "fingerprint": fingerprint}).one()
        except Exception as exc: raise SecurityAuthorityError("duplicate_approval_decision") from exc
        return row.id

    def approval_satisfied(self, public_id, request, identity, at):
        if public_id is None: return False
        row = self.db_session.execute(text("""SELECT a.requester_identity_id,a.permission_code,a.action_fingerprint,a.expires_at,a.required_approvals,count(*) FILTER(WHERE d.approved) approved
            FROM protected_action_approvals a LEFT JOIN approval_decisions d ON d.approval_id=a.id WHERE a.public_id=:id AND a.tenant_id=:tenant GROUP BY a.id"""), {"id": str(public_id), "tenant": request.tenant_id}).first()
        expected = _action_fingerprint(request)
        return bool(row and row.requester_identity_id == identity and row.permission_code == request.permission_code and row.action_fingerprint == expected and row.expires_at > at and row.approved >= row.required_approvals)

    def append_audit(self, envelope, fingerprint):
        try: row = self.db_session.execute(text("""INSERT INTO audit_evidence(public_id,tenant_id,actor_identity_id,actor_type,action_code,target_type,target_id,outcome,reason,occurred_at,correlation_id,source_module,session_public_id,authorization_reference,approval_public_id,scope_type,scope_id,safe_metadata,prior_evidence_id,evidence_fingerprint,delegation_public_id)
            VALUES(:id,:tenant,:actor,:actor_type,:action,:target_type,:target_id,:outcome,:reason,:at,:correlation,:source,:session,:authorization,:approval,:scope,:scope_id,CAST(:metadata AS jsonb),:prior,:fingerprint,:delegation) RETURNING public_id"""), {"id": str(envelope.public_id), "tenant": envelope.tenant_id, "actor": envelope.actor_id, "actor_type": envelope.actor_type.value, "action": envelope.action_code, "target_type": envelope.target_type, "target_id": envelope.target_id, "outcome": envelope.outcome, "reason": envelope.reason, "at": envelope.occurred_at, "correlation": envelope.correlation_id, "source": envelope.source_module, "session": str(envelope.session_id) if envelope.session_id else None, "authorization": envelope.authorization_reference, "approval": str(envelope.approval_id) if envelope.approval_id else None, "scope": envelope.scope.scope_type.value if envelope.scope else None, "scope_id": envelope.scope.scope_id if envelope.scope else None, "metadata": json.dumps(envelope.metadata or {}, sort_keys=True), "prior": str(envelope.prior_evidence_id) if envelope.prior_evidence_id else None, "fingerprint": fingerprint,"delegation":str(envelope.delegation_id) if envelope.delegation_id else None}).one()
        except Exception as exc: raise SecurityAuthorityError("duplicate_or_invalid_audit_evidence") from exc
        return row.public_id

    def query_audit(self, query):
        clauses = ["tenant_id IS NOT DISTINCT FROM :tenant", "occurred_at>=:start", "occurred_at<:end"]
        params = {"tenant": query.tenant_id, "start": query.start, "end": query.end}
        for field, value in (("actor_identity_id", query.actor_id), ("action_code", query.action_code), ("target_type", query.target_type), ("correlation_id", query.correlation_id)):
            if value is not None: clauses.append(f"{field}=:{field}"); params[field] = value
        if query.scope: clauses.extend(("scope_type=:scope_type", "scope_id=:scope_id")); params.update(scope_type=query.scope.scope_type.value, scope_id=query.scope.scope_id)
        return [dict(x._mapping) for x in self.db_session.execute(text("SELECT * FROM audit_evidence WHERE " + " AND ".join(clauses) + " ORDER BY occurred_at,public_id"), params)]

    def export_identity(self, identity):
        profile = self.db_session.execute(text("SELECT public_id,login_name,status,party_id FROM identities WHERE id=:id"), {"id": identity}).mappings().one()
        memberships = [dict(x._mapping) for x in self.db_session.execute(text("SELECT tenant_id,status,valid_from,valid_to,party_id FROM identity_memberships WHERE identity_id=:id ORDER BY tenant_id,valid_from"), {"id": identity})]
        roles = [dict(x._mapping) for x in self.db_session.execute(text("SELECT tenant_id,scope_type,scope_id,valid_from,valid_to FROM scoped_role_assignments WHERE principal_id=:id AND actor_type='human' ORDER BY tenant_id,scope_type,scope_id"), {"id": identity})]
        return {"schema": "xbos.pc5.identity-export.v1", "identity": dict(profile), "memberships": memberships, "authorization_assignments": roles}


def _action_fingerprint(request):
    return __import__("hashlib").sha256(json.dumps({"permission": request.permission_code, "resource_type": request.resource_type, "resource_id": request.resource_id, "scope_type": request.target_scope.scope_type.value, "scope_id": request.target_scope.scope_id}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
