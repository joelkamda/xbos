from __future__ import annotations
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import json,pytest
ROOT=Path(__file__).resolve().parents[2]
from shared_operations.so5 import *

P=UUID("51000000-0000-0000-0000-000000000001"); I=UUID("51000000-0000-0000-0000-000000000002")
O=UUID("51000000-0000-0000-0000-000000000003"); L=UUID("51000000-0000-0000-0000-000000000004")
R1=UUID("51000000-0000-0000-0000-000000000011"); R2=UUID("51000000-0000-0000-0000-000000000012"); A1=UUID("51000000-0000-0000-0000-000000000021")
NOW=datetime(2026,8,14,12,tzinfo=timezone.utc)

class FakeRepo:
    def __init__(self):self.resources={};self.assignments_by_id={};self.commands={};self.events=[]
    def _cmd(self,c,fp,kind):
        old=self.commands.get((c.tenant_id,c.command_key))
        if old and old[:2]!=(fp,kind):raise SO5AuthorityError("SO5_COMMAND_CONFLICT","idempotency_conflict","conflict")
        return old
    def create_resource(self,c,pid,fp):
        old=self._cmd(c,fp,"create_resource")
        if old:return self.resources[old[2]]
        value=Resource(pid,c.tenant_id,c.resource_kind,c.classification_code,c.display_label,ResourceStatus.ACTIVE,c.capacity,c.exclusive_assignment,c.party_public_id,c.identity_public_id,c.organization_unit_public_id,c.location_public_id,c.metadata,1)
        self.resources[pid]=value;self.commands[(c.tenant_id,c.command_key)]=(fp,"create_resource",pid);self.events.append((pid,"created"));return value
    def resource(self,t,p):
        v=self.resources.get(p);return v if v and v.tenant_id==t else None
    def list_resources(self,t,classification_code=None):return tuple(v for v in self.resources.values() if v.tenant_id==t and (classification_code is None or v.classification_code==classification_code))
    def change_status(self,c,fp):
        old=self._cmd(c,fp,"change_status")
        if old:return self.resources[old[2]]
        v=self.resource(c.tenant_id,c.resource_public_id)
        if not v or v.row_version!=c.expected_version:return None
        v=replace(v,status=c.to_status,row_version=v.row_version+1);self.resources[v.public_id]=v;self.commands[(c.tenant_id,c.command_key)]=(fp,"change_status",v.public_id);self.events.append((v.public_id,c.to_status.value));return v
    def assign(self,c,pid,fp):
        old=self._cmd(c,fp,"assign_resource")
        if old:return self.assignments_by_id[old[2]]
        r=self.resource(c.tenant_id,c.resource_public_id)
        if not r or r.row_version!=c.expected_resource_version:return None
        if r.exclusive_assignment:
            for a in self.assignments_by_id.values():
                if a.tenant_id==c.tenant_id and a.resource_public_id==r.public_id and a.status is AssignmentStatus.ACTIVE:
                    ae=a.effective_to or datetime.max.replace(tzinfo=timezone.utc); ce=c.effective_to or datetime.max.replace(tzinfo=timezone.utc)
                    if a.effective_from<ce and c.effective_from<ae:return None
        a=OperationalAssignment(pid,c.tenant_id,r.public_id,c.capability_code,AssignmentStatus.ACTIVE,c.effective_from,c.effective_to,c.organization_unit_public_id,c.location_public_id,c.source_reference,1)
        self.assignments_by_id[pid]=a;self.resources[r.public_id]=replace(r,row_version=r.row_version+1);self.commands[(c.tenant_id,c.command_key)]=(fp,"assign_resource",pid);self.events.append((r.public_id,"assigned"));return a
    def assignment(self,t,p):
        a=self.assignments_by_id.get(p);return a if a and a.tenant_id==t else None
    def end_assignment(self,c,fp):
        old=self._cmd(c,fp,"end_assignment")
        if old:return self.assignments_by_id[old[2]]
        a=self.assignment(c.tenant_id,c.assignment_public_id)
        if not a or a.row_version!=c.expected_version or a.status is not AssignmentStatus.ACTIVE or c.ended_at<a.effective_from:return None
        a=replace(a,status=AssignmentStatus.ENDED,effective_to=c.ended_at,row_version=a.row_version+1);self.assignments_by_id[a.public_id]=a;self.commands[(c.tenant_id,c.command_key)]=(fp,"end_assignment",a.public_id);self.events.append((a.resource_public_id,"ended"));return a
    def assignments(self,t,r,include_history=False):return tuple(a for a in self.assignments_by_id.values() if a.tenant_id==t and a.resource_public_id==r and (include_history or a.status is AssignmentStatus.ACTIVE))
    def history(self,t,r):return tuple(x for x in self.events if x[0]==r)

def authority(repo=None,ids=None):
    repo=repo or FakeRepo();ids=iter(ids or [R1,R2,A1,UUID(int=51031),UUID(int=51032),UUID(int=51033),UUID(int=51034),UUID(int=51035)])
    def obj(t,p,party=None):return SimpleNamespace(tenant_id=t,public_id=p,party_public_id=party)
    return SO5Authority(repo,party_resolver=lambda t,p:obj(t,p) if p==P and t==1 else None,identity_resolver=lambda t,p:obj(t,p,P) if p==I and t==1 else None,organization_resolver=lambda t,p:obj(t,p) if p==O and t==1 else None,location_resolver=lambda t,p:obj(t,p) if p==L and t==1 else None,authorize=lambda *x:True,public_id_factory=lambda:next(ids)),repo

def test_resource_party_user_and_operational_assignment_boundaries():
    so5,repo=authority()
    person=so5.create_resource(CreateResource("person",1,ResourceKind.PERSON,"technician","Field Tech",P,I,O,L,1,True))
    machine=so5.create_resource(CreateResource("machine",1,ResourceKind.NON_PERSON,"diagnostic_equipment","Analyzer",None,None,O,L,2,False))
    assert person.party_public_id==P and person.identity_public_id==I and person.public_id not in {P,I}
    assert machine.party_public_id is None and machine.identity_public_id is None
    assignment=so5.assign(AssignResource("assign",1,person.public_id,person.row_version,"field_service",NOW,NOW+timedelta(hours=8),O,L))
    assert assignment.capability_code=="field_service" and person.identity_public_id==I
    assert so5.assignments(1,person.public_id)==(assignment,)

def test_assignment_history_exclusivity_and_exact_idempotency():
    so5,repo=authority()
    person_cmd=CreateResource("person",1,ResourceKind.PERSON,"clinician","Clinician",P,I,O,L,1,True)
    r=so5.create_resource(person_cmd);assert so5.create_resource(person_cmd)==r
    with pytest.raises(SO5AuthorityError,match="SO5_COMMAND_CONFLICT"):so5.create_resource(replace(person_cmd,display_label="Changed"))
    cmd=AssignResource("a",1,r.public_id,r.row_version,"clinical_care",NOW,NOW+timedelta(hours=4),O,L)
    a=so5.assign(cmd);assert so5.assign(cmd)==a
    r=so5.resource(1,r.public_id)
    with pytest.raises(SO5AuthorityError,match="SO5_ASSIGNMENT_CONFLICT"):so5.assign(AssignResource("overlap",1,r.public_id,r.row_version,"clinical_care",NOW+timedelta(hours=1),NOW+timedelta(hours=2),O,L))
    ended=so5.end_assignment(EndAssignment("end",1,a.public_id,a.row_version,NOW+timedelta(hours=3),"shift_end"))
    assert ended.status is AssignmentStatus.ENDED and so5.assignments(1,r.public_id)==() and so5.assignments(1,r.public_id,True)[0].status is AssignmentStatus.ENDED
    assert len(so5.history(1,r.public_id))>=3

def test_tenant_isolation_identity_and_nonperson_rules_are_fail_closed():
    so5,_=authority()
    with pytest.raises(SO5AuthorityError,match="SO5_PARTY_NOT_FOUND"):so5.create_resource(CreateResource("x",2,ResourceKind.PERSON,"tech","X",P))
    with pytest.raises(SO5AuthorityError,match="SO5_NON_PERSON_PARTY_FORBIDDEN"):so5.create_resource(CreateResource("y",1,ResourceKind.NON_PERSON,"room","Room",P))
    with pytest.raises(SO5AuthorityError,match="SO5_IDENTITY_PARTY_MISMATCH"):
        so5.identity_resolver=lambda t,p:SimpleNamespace(tenant_id=1,public_id=I,party_public_id=UUID(int=999));so5.create_resource(CreateResource("z",1,ResourceKind.PERSON,"tech","Z",P,I))

def test_permission_is_server_side_and_xa_never_grants_authority():
    repo=FakeRepo();so5,_=authority(repo);so5.authorize=lambda *x:False
    with pytest.raises(SO5AuthorityError,match="SO5_PERMISSION_DENIED"):so5.list_resources(1)
    xa=json.loads((ROOT/"contracts/shared_operations/v1/so5_xa_metadata.json").read_text());assert xa["frontend_implementation"]=="NONE" and xa["denial_source"]=="PC5"

def test_neutral_profiles_and_finance_boundary():
    a=json.loads((ROOT/"contracts/shared_operations/v1/examples/field_service_resources_profile.json").read_text());b=json.loads((ROOT/"contracts/shared_operations/v1/examples/clinical_resources_profile.json").read_text())
    assert a["terminology"]!=b["terminology"] and a["classifications"]!=b["classifications"]
    sql=(ROOT/"alembic_neutral/sql/so5_resources_operational_assignment_up.sql").read_text().lower()
    for forbidden in ("financial_events","journal_entries","financial_obligations","payment_settlements","payroll","commission") : assert forbidden not in sql

def test_sql_has_tenant_qualified_authorities_and_identity_membership_trigger():
    sql=(ROOT/"alembic_neutral/sql/so5_resources_operational_assignment_up.sql").read_text()
    assert "REFERENCES public.parties(tenant_id,id)" in sql
    assert "REFERENCES public.organization_units(tenant_id,id)" in sql and "REFERENCES public.locations(tenant_id,id)" in sql
    assert "identity_memberships" in sql and "NEW.tenant_id" in sql
    assert "so5_history_immutable" in sql

def test_authority_contract_excludes_security_workflow_scheduling_and_finance():
    a=json.loads((ROOT/"contracts/shared_operations/v1/so5_authority.json").read_text())
    assert a["party_authority"]=="PC2_REUSED" and a["identity_authority"]=="PC5_SEPARATE" and a["structure_authority"]=="PC1_REUSED"
    assert a["workflow_authority"]=="SO6_EXCLUDED" and a["scheduling_authority"]=="SO10_EXCLUDED" and a["finance"]=="UNCHANGED"
