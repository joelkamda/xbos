from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

from core.platform.security_authority import *

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
SESSION = UUID("50000000-0000-0000-0000-000000000001")
APPROVAL = UUID("50000000-0000-0000-0000-000000000002")


class MemoryRepository:
    def __init__(self):
        self.lock=Lock();self.identities={};self.memberships={};self.permissions={};self.roles={};self.role_assignments=[];self.sessions={};self.policies={};self.stepups={};self.approvals={};self.delegations={};self.audit=[];self.services={};self.devices={};self.next_id=1
    def _id(self):
        with self.lock:value=self.next_id;self.next_id+=1;return value
    def create_identity(self,key,fingerprint,login,party):
        if login in (x.login_name for x in self.identities.values()):raise SecurityAuthorityError("duplicate_identity")
        value=Identity(self._id(),UUID(int=self.next_id),login,Lifecycle.ACTIVE,party);self.identities[value.id]=value;return value
    def add_membership(self,key,fingerprint,identity,tenant,start,end,party):
        value=Membership(self._id(),identity,tenant,Lifecycle.ACTIVE,start,end,party);self.memberships[(identity,tenant)]=value;return value
    def revoke_membership(self,identity,tenant,at):
        value=self.memberships[(identity,tenant)];self.memberships[(identity,tenant)]=replace(value,status=Lifecycle.REVOKED);return value.id
    def register_permission(self,key,fingerprint,value):self.permissions[value.code]=value;return value
    def permission(self,code):return self.permissions.get(code)
    def create_role(self,key,fingerprint,role,tenant,permissions):self.roles[(tenant,role)]=permissions;return self._id()
    def assign_role(self,key,fingerprint,assignment):self.role_assignments.append(assignment);return self._id()
    def create_session(self,key,fingerprint,identity,tenant,actor,assurance,start,end,device):
        value=SessionContext(self._id(),SESSION,identity,tenant,actor,assurance,start,end,None,device);self.sessions[SESSION]=value;return value
    def session(self,public):return self.sessions.get(public)
    def revoke_session(self,public,at):self.sessions[public]=replace(self.sessions[public],revoked_at=at);return self.sessions[public]
    def membership_active(self,identity,tenant,at):
        value=self.memberships.get((identity,tenant));return bool(value and value.status is Lifecycle.ACTIVE and value.valid_from<=at and (value.valid_to is None or value.valid_to>at))
    def principal_active(self,actor_type,principal,tenant):return True
    def assignments(self,identity,tenant,at,actor_type=ActorType.HUMAN):
        return [{"scope":a.scope,"permissions":self.roles[(tenant,a.role_code)]} for a in self.role_assignments if a.identity_id==identity and a.actor_type is actor_type and a.tenant_id==tenant and a.valid_from<=at and (a.valid_to is None or a.valid_to>at)]
    def policy(self,permission,tenant,at):return self.policies.get((tenant,permission))
    def grant_support_access(self,grant,fingerprint):self.delegations[grant.public_id]=grant;return self._id()
    def revoke_support_access(self,public,at):self.delegations.pop(public,None);return 1
    def delegation_active(self,public,operator,tenant,permission,scope,at):
        value=self.delegations.get(public);return bool(value and value.operator_identity_id==operator and value.tenant_id==tenant and value.permission_code==permission and value.scope==scope and value.effective_from<=at<value.expires_at)
    def grant_step_up(self,key,fingerprint,session,assurance,end,scope):self.stepups[session]=(assurance,end,scope);return self._id()
    def step_up_assurance(self,session,scope,at):
        value=self.stepups.get(session);return value[0] if value and value[1]>at and (value[2] is None or value[2]==scope) else 0
    def request_approval(self,request,fingerprint):self.approvals[request.public_id]={"request":request,"decisions":set()};return self._id()
    def decide_approval(self,decision,fingerprint):
        request=self.approvals[decision.approval_id]["request"]
        if request.requester_identity_id==decision.approver_identity_id:raise SecurityAuthorityError("approval_separation_required")
        if decision.approver_identity_id in self.approvals[decision.approval_id]["decisions"]:raise SecurityAuthorityError("duplicate_approval_decision")
        if decision.approved:self.approvals[decision.approval_id]["decisions"].add(decision.approver_identity_id)
        return self._id()
    def approval_satisfied(self,public,request,identity,at):
        value=self.approvals.get(public)
        if not value:return False
        expected=__import__('hashlib').sha256(__import__('json').dumps({"permission":request.permission_code,"resource_type":request.resource_type,"resource_id":request.resource_id,"scope_type":request.target_scope.scope_type.value,"scope_id":request.target_scope.scope_id},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        approved=value["request"]
        return approved.requester_identity_id==identity and approved.permission_code==request.permission_code and approved.action_fingerprint==expected and approved.expires_at>at and len(value["decisions"])>=approved.required_approvals
    def append_audit(self,envelope,fingerprint):self.audit.append(envelope);return envelope.public_id
    def query_audit(self,query):return [x for x in self.audit if x.tenant_id==query.tenant_id]
    def export_identity(self,identity):return {"schema":"xbos.pc5.identity-export.v1","identity":{"id":identity},"memberships":[],"authorization_assignments":[]}
    def register_service_identity(self,key,fingerprint,code,owner,tenant,reference):
        value=ServiceIdentity(self._id(),UUID(int=self.next_id),code,owner,tenant,Lifecycle.ACTIVE,reference);self.services[value.id]=value;return value
    def register_device_identity(self,key,fingerprint,code,tenant,location,organization,assurance):
        value=DeviceIdentity(self._id(),UUID(int=self.next_id),code,tenant,Lifecycle.ACTIVE,location,organization,assurance);self.devices[value.id]=value;return value


def configured(required_assurance=1, approval_profile=None):
    repo=MemoryRepository();authority=SecurityAuthority(repo)
    identity=authority.create_identity(command_key="identity",login_name="operator@example.com")
    authority.add_membership(command_key="membership",identity_id=identity.id,tenant_id=7,valid_from=NOW-timedelta(days=1))
    permission=PermissionDefinition("pc5.audit.evidence.query","pc5","audit","query","high",(ScopeType.TENANT,ScopeType.ORGANIZATION_UNIT),required_assurance,approval_profile)
    authority.register_permission(command_key="permission",definition=permission)
    authority.create_role(command_key="role",role_code="auditor",tenant_id=7,permissions=(permission.code,))
    authority.assign_role(command_key="assign",assignment=RoleAssignment(identity.id,7,"auditor",StructuralScope(ScopeType.TENANT,7),NOW-timedelta(days=1)))
    authority.create_session(command_key="session",identity_id=identity.id,tenant_id=7,actor_type=ActorType.HUMAN,assurance_level=1,authenticated_at=NOW-timedelta(hours=1),expires_at=NOW+timedelta(hours=1))
    return authority,repo,identity


def request(**changes):
    values=dict(session_id=SESSION,permission_code="pc5.audit.evidence.query",tenant_id=7,target_scope=StructuralScope(ScopeType.TENANT,7),resource_type="audit_evidence",resource_id="query",occurred_at=NOW,correlation_id="pc5-test")
    values.update(changes);return AuthorizationRequest(**values)


def test_pc5_covers_exact_fifteen_wbs_v2_obligations():
    import json
    contract=json.loads((ROOT/"contracts/platform/v1/pc5_identity_policy_audit_authority.json").read_text())
    assert contract["scope"]==[f"PC5.{x}" for x in range(1,16)]


def test_database_acceptance_constructs_callable_session_factory_and_nested_transaction():
    from scripts.verify_pc5_identity_policy_audit import _database_session
    try:
        from sqlalchemy import create_engine,text
    except ModuleNotFoundError:
        events=[]
        class Transaction:
            def __enter__(self):events.append("transaction-enter");return self
            def __exit__(self,*args):events.append("transaction-exit")
        class DatabaseSession:
            def __enter__(self):events.append("session-enter");return self
            def __exit__(self,*args):events.append("session-exit")
            def begin(self):events.append("begin-called");return Transaction()
        def sessionmaker(*,bind,expire_on_commit):
            assert bind is engine and expire_on_commit is False;events.append("factory-built")
            return lambda:(events.append("factory-called") or DatabaseSession())
        sqlalchemy=ModuleType("sqlalchemy");sqlalchemy.__path__=[]
        orm=ModuleType("sqlalchemy.orm");orm.sessionmaker=sessionmaker;sqlalchemy.orm=orm
        engine=object()
        with patch.dict("sys.modules",{"sqlalchemy":sqlalchemy,"sqlalchemy.orm":orm}):
            with _database_session(engine) as database_session:
                assert isinstance(database_session,DatabaseSession);events.append("body")
        assert events==["factory-built","factory-called","session-enter","begin-called","transaction-enter","body","transaction-exit","session-exit"]
    else:
        engine=create_engine("sqlite+pysqlite:///:memory:")
        try:
            with _database_session(engine) as database_session:
                assert database_session.execute(text("SELECT 1")).scalar_one()==1
        finally:engine.dispose()


def test_sql_repository_create_authorize_lookup_revoke_deny_has_no_session_collision():
    try:
        repository_module=importlib.import_module("core.platform.security_authority.sql_repository")
    except ModuleNotFoundError as exc:
        if exc.name!="sqlalchemy":raise
        sqlalchemy=ModuleType("sqlalchemy");sqlalchemy.__path__=[];sqlalchemy.text=lambda statement:statement
        with patch.dict("sys.modules",{"sqlalchemy":sqlalchemy}):
            repository_module=importlib.import_module("core.platform.security_authority.sql_repository")

    class Result:
        def __init__(self,value=None):self.value=value
        def one(self):return self.value
        def first(self):return self.value
        def scalar_one(self):return self.value

    class FakeDBSession:
        def __init__(self):self.commands={};self.authentication_session=None
        def execute(self,statement,params=None):
            sql=str(statement);params=params or {}
            if sql.startswith("INSERT INTO security_commands"):
                self.commands.setdefault(params["k"],SimpleNamespace(request_fingerprint=params["f"],command_type=params["t"],result_id=None));return Result()
            if sql.startswith("SELECT * FROM security_commands"):
                return Result(self.commands[params["k"]])
            if sql.startswith("UPDATE security_commands"):
                self.commands[params["k"]].result_id=params["i"];return Result()
            if sql.startswith("INSERT INTO authentication_sessions"):
                self.authentication_session=SimpleNamespace(id=1,public_id=SESSION,principal_id=params["identity"],tenant_id=params["tenant"],actor_type=params["actor"],assurance_level=params["assurance"],authenticated_at=params["start"],expires_at=params["end"],revoked_at=None,device_identity_id=params["device"]);return Result(self.authentication_session)
            if sql.startswith("SELECT * FROM authentication_sessions WHERE public_id"):
                return Result(self.authentication_session if str(self.authentication_session.public_id)==params["id"] else None)
            if sql.startswith("SELECT COALESCE(max("):
                assert "max(g.assurance_level)" in sql
                assert "max(assurance_level)" not in sql
                return Result(0)
            if sql.startswith("UPDATE authentication_sessions SET revoked_at"):
                self.authentication_session.revoked_at=params["at"];return Result(self.authentication_session)
            raise AssertionError(f"unexpected SQL in collision regression: {sql}")

    db_session=FakeDBSession();repository=repository_module.SQLSecurityRepository(db_session)
    assert repository.db_session is db_session and "session" not in repository.__dict__ and callable(repository.session)
    permission=PermissionDefinition("pc5.audit.evidence.query","pc5","audit","query","high",(ScopeType.TENANT,),1)
    repository.permission=lambda code:permission if code==permission.code else None
    repository.delegation_active=lambda *args:False
    repository.membership_active=lambda *args:True
    repository.assignments=lambda *args,**kwargs:[{"scope":StructuralScope(ScopeType.TENANT,7),"permissions":(permission.code,)}]
    repository.policy=lambda *args:None
    authority=SecurityAuthority(repository)
    created=authority.create_session(command_key="collision-session",identity_id=41,tenant_id=7,actor_type=ActorType.HUMAN,assurance_level=1,authenticated_at=NOW-timedelta(minutes=1),expires_at=NOW+timedelta(hours=1))
    assert repository.session(created.public_id)==created
    authorization=request(session_id=created.public_id)
    assert authority.authorize(authorization).decision is Decision.ALLOW
    authority.revoke_session(created.public_id,NOW)
    denied=authority.authorize(authorization)
    assert denied.decision is Decision.DENY and denied.reason=="session_inactive"


def test_identity_party_membership_and_authorization_role_remain_distinct():
    authority,repo,identity=configured();membership=repo.memberships[(identity.id,7)]
    assert identity.party_id is None and membership.party_id is None and repo.roles[(7,"auditor")]
    assert "partyrole != pc5 authorization role" in " ".join(__import__('json').loads((ROOT/"contracts/platform/v1/pc5_identity_policy_audit_authority.json").read_text())["distinctions"]).lower()


def test_membership_alone_grants_no_permission_and_unknown_permission_denies():
    authority,repo,identity=configured();repo.role_assignments.clear()
    assert authority.authorize(request()).reason=="permission_not_established"
    assert authority.authorize(request(permission_code="pc5.unknown.resource.read")).reason=="unknown_permission"


def test_positive_scoped_role_authority_allows_and_cross_tenant_denies():
    authority,repo,identity=configured()
    assert authority.authorize(request()).decision is Decision.ALLOW
    assert authority.authorize(request(tenant_id=8,target_scope=StructuralScope(ScopeType.TENANT,8))).reason=="session_tenant_mismatch"


def test_equal_numeric_ids_across_scope_types_do_not_collapse():
    authority,repo,identity=configured();repo.role_assignments[0]=replace(repo.role_assignments[0],scope=StructuralScope(ScopeType.ORGANIZATION_UNIT,7))
    assert authority.authorize(request()).decision is Decision.DENY
    assert authority.authorize(request(target_scope=StructuralScope(ScopeType.ORGANIZATION_UNIT,7))).decision is Decision.ALLOW


def test_pc4_availability_entitlement_flag_and_pc5_permission_are_independent():
    authority,repo,identity=configured()
    for field in ("module_available","module_enabled","entitled","feature_active"):
        assert authority.authorize(replace(request(),**{field:False})).reason=="pc4_capability_unavailable"


def test_revoked_membership_and_revoked_or_expired_session_fail_closed():
    authority,repo,identity=configured();authority.revoke_membership(identity_id=identity.id,tenant_id=7,revoked_at=NOW)
    assert authority.authorize(request()).reason=="membership_inactive"
    repo.memberships[(identity.id,7)]=replace(repo.memberships[(identity.id,7)],status=Lifecycle.ACTIVE);authority.revoke_session(SESSION,NOW)
    assert authority.authorize(request()).reason=="session_inactive"
    repo.sessions[SESSION]=replace(repo.sessions[SESSION],revoked_at=None,expires_at=NOW)
    assert authority.authorize(request()).reason=="session_inactive"


def test_step_up_is_expiring_session_scoped_and_not_permanent_identity_state():
    authority,repo,identity=configured(required_assurance=2)
    assert authority.authorize(request()).decision is Decision.REQUIRE_STEP_UP
    authority.grant_step_up(command_key="step",session_id=SESSION,assurance_level=2,expires_at=NOW+timedelta(minutes=5),scope=StructuralScope(ScopeType.TENANT,7))
    assert authority.authorize(request()).decision is Decision.ALLOW
    assert identity.status is Lifecycle.ACTIVE


def test_maker_cannot_self_approve_and_approval_is_bound_to_exact_action():
    authority,repo,identity=configured(approval_profile="maker_checker")
    action=request();fingerprint=__import__('hashlib').sha256(__import__('json').dumps({"permission":action.permission_code,"resource_type":action.resource_type,"resource_id":action.resource_id,"scope_type":"tenant","scope_id":7},sort_keys=True,separators=(",",":")).encode()).hexdigest()
    approval=ApprovalRequest(APPROVAL,7,identity.id,action.permission_code,fingerprint,action.target_scope,1,NOW+timedelta(hours=1));authority.request_approval(approval)
    with pytest.raises(SecurityAuthorityError,match="approval_separation_required"):authority.decide_approval(ApprovalDecision(APPROVAL,identity.id,True,NOW,"self"))
    authority.decide_approval(ApprovalDecision(APPROVAL,identity.id+1,True,NOW,"independent"))
    assert authority.authorize(replace(action,approval_id=APPROVAL)).decision is Decision.ALLOW
    assert authority.authorize(replace(action,approval_id=APPROVAL,resource_id="other")).decision is Decision.REQUIRE_APPROVAL


def test_service_and_device_are_first_class_and_never_human_identity():
    authority,repo,identity=configured();service=authority.register_service_identity(command_key="service",service_code="worker.finance",owner_module="so9",tenant_id=7,credential_reference="vault.worker.finance")
    device=authority.register_device_identity(command_key="device",device_code="pos.001",tenant_id=7,location_id=7,organization_unit_id=7)
    assert isinstance(service,ServiceIdentity) and isinstance(device,DeviceIdentity)
    assert not isinstance(service,Identity) and not isinstance(device,Identity)
    assert service.service_code=="worker.finance" and device.device_code=="pos.001"
    assert service.owner_module=="so9" and device.tenant_id==7


def test_support_access_is_explicit_time_bound_permission_scoped_and_attributable():
    authority,repo,_=configured();operator=authority.create_identity(command_key="operator",login_name="platform@xbos.invalid")
    authority.create_session(command_key="platform-session",identity_id=operator.id,tenant_id=None,actor_type=ActorType.HUMAN,assurance_level=2,authenticated_at=NOW-timedelta(minutes=1),expires_at=NOW+timedelta(hours=1))
    grant_id=UUID("50000000-0000-0000-0000-000000000099")
    authority.grant_support_access(SupportAccessGrant(grant_id,operator.id,7,"pc5.audit.evidence.query",StructuralScope(ScopeType.TENANT,7),NOW-timedelta(minutes=1),NOW+timedelta(minutes=30),"approved merchant support",APPROVAL))
    assert authority.authorize(request(delegation_id=grant_id)).decision is Decision.ALLOW
    assert authority.authorize(request(delegation_id=grant_id,permission_code="pc5.identity.membership.manage")).decision is Decision.DENY
    authority.revoke_support_access(grant_id,NOW)
    assert authority.authorize(request(delegation_id=grant_id)).reason=="session_tenant_mismatch"


def test_support_access_rejects_invisible_or_overlong_break_glass():
    authority,repo,identity=configured()
    with pytest.raises(SecurityAuthorityError,match="invalid_support_access_grant"):
        authority.grant_support_access(SupportAccessGrant(UUID(int=98),identity.id,7,"pc5.audit.evidence.query",StructuralScope(ScopeType.TENANT,7),NOW,NOW+timedelta(hours=9),"",APPROVAL,True))


def test_audit_rejects_sensitive_material_and_export_excludes_credentials():
    authority,repo,identity=configured();envelope=AuditEnvelope(UUID(int=50),7,identity.id,ActorType.HUMAN,"pc5.audit.query","audit","query","allowed",NOW,"pc5","corr",SESSION,scope=StructuralScope(ScopeType.TENANT,7),metadata={"count":1})
    assert authority.append_audit(envelope)==envelope.public_id
    with pytest.raises(SecurityAuthorityError,match="audit_sensitive_material_forbidden"):authority.append_audit(replace(envelope,public_id=UUID(int=51),metadata={"password_hash":"bad"}))
    exported=authority.export_identity(identity.id);assert exported["credential_material_included"] is False and exported["session_secrets_included"] is False


def test_audit_query_is_permission_controlled_and_tenant_scoped():
    authority,repo,identity=configured();authority.append_audit(AuditEnvelope(UUID(int=52),7,identity.id,ActorType.HUMAN,"pc5.audit.query","audit","query","allowed",NOW,"pc5","corr",SESSION,scope=StructuralScope(ScopeType.TENANT,7)))
    assert len(authority.query_audit(AuditQuery(SESSION,7,NOW-timedelta(hours=1),NOW+timedelta(hours=1),scope=StructuralScope(ScopeType.TENANT,7))))==1
    repo.role_assignments.clear()
    with pytest.raises(SecurityAuthorityError,match="audit_query_forbidden"):authority.query_audit(AuditQuery(SESSION,7,NOW-timedelta(hours=1),NOW+timedelta(hours=1),scope=StructuralScope(ScopeType.TENANT,7)))


def test_migration_is_one_child_append_only_and_has_no_finance_or_outbox_writer():
    version=(ROOT/"alembic_neutral/versions/pc5_identity_policy_audit_025_canonical_security_authority.py").read_text();up=(ROOT/"alembic_neutral/sql/pc5_identity_policy_audit_up.sql").read_text()
    assert 'revision = "pc5_identity_policy_audit_025"' in version and 'down_revision = "pc4_operating_context_024"' in version
    assert "audit_evidence_append_only" in up and "BEFORE UPDATE OR DELETE" in up
    assert not any(x in up for x in ("ALTER TABLE public.financial_","UPDATE public.financial_","INSERT INTO public.outbox_messages","CREATE TABLE public.outbox"))


def test_legacy_auth_inventory_is_complete_and_has_named_retirement_paths():
    import json
    entries=json.loads((ROOT/"contracts/platform/v1/pc5_compatibility_migration_manifest.json").read_text())["entries"]
    authorities={x["authority"] for x in entries}
    assert {"users","users.password_hash","JWTService","users.tenant_id","users.branch_id","users.role","roles.permissions JSON","permission levels and role packs","permission middleware and decorators","generic audit authority","service/device credentials"}<=authorities
    assert all(x["retirement_owner"] and x["retirement_milestone"] for x in entries)


def test_accepted_pc1_pc2_pc3_pc4_repairs_are_preserved():
    pc1=(ROOT/"scripts/verify_pc1_structural_authority.py").read_text();pc3=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text();pc4=(ROOT/"alembic_neutral/sql/pc4_operating_context_up.sql").read_text();wrapper=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    assert "authority object types collapsed" not in pc1
    assert "name,semantic_level,taxonomy_type,sort_order" in pc3 and "'Child','domain','COMMERCE'" in pc3
    assert "OR NOT (CASE d.value_type" in pc4 and ".connection.cursor()" in wrapper
