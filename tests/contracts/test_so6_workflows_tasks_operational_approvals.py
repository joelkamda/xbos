from __future__ import annotations
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import json,pytest
ROOT=Path(__file__).resolve().parents[2]
from shared_operations.so6 import *

O=UUID("61000000-0000-0000-0000-000000000001");L=UUID("61000000-0000-0000-0000-000000000002");R=UUID("61000000-0000-0000-0000-000000000003");R2=UUID("61000000-0000-0000-0000-000000000004")
W=UUID("61000000-0000-0000-0000-000000000011");T=UUID("61000000-0000-0000-0000-000000000021");A=UUID("61000000-0000-0000-0000-000000000031")
NOW=datetime(2026,8,14,13,tzinfo=timezone.utc)

class FakeRepo:
    def __init__(self):self.workflows={};self.tasks_by_id={};self.approvals_by_id={};self.commands={};self.events=[]
    def _cmd(self,c,fp,kind):
        old=self.commands.get((c.tenant_id,c.command_key))
        if old and old[:2]!=(fp,kind):raise SO6AuthorityError("SO6_COMMAND_CONFLICT","idempotency_conflict","conflict")
        return old
    def create_workflow(self,c,pid,fp):
        old=self._cmd(c,fp,"create_workflow")
        if old:return self.workflows[old[2]]
        v=Workflow(pid,c.tenant_id,c.workflow_type_code,c.title,WorkflowStatus.OPEN,c.priority,c.subject_authority,c.subject_reference,c.due_at,c.organization_unit_public_id,c.location_public_id,c.metadata,1)
        self.workflows[pid]=v;self.commands[(c.tenant_id,c.command_key)]=(fp,"create_workflow",pid);self.events.append((pid,"workflow","created"));return v
    def workflow(self,t,p):
        v=self.workflows.get(p);return v if v and v.tenant_id==t else None
    def list_workflows(self,t,status=None):return tuple(v for v in self.workflows.values() if v.tenant_id==t and (status is None or v.status==status))
    def add_task(self,c,pid,fp):
        old=self._cmd(c,fp,"add_task")
        if old:return self.tasks_by_id[old[2]]
        w=self.workflow(c.tenant_id,c.workflow_public_id)
        if not w or w.row_version!=c.expected_workflow_version or w.status is not WorkflowStatus.OPEN:return None
        v=WorkflowTask(pid,c.tenant_id,w.public_id,c.task_type_code,c.title,TaskStatus.PENDING,c.priority,c.due_at,c.assignee_resource_public_id,c.required_capability_code,c.metadata,1)
        self.tasks_by_id[pid]=v;self.workflows[w.public_id]=replace(w,row_version=w.row_version+1);self.commands[(c.tenant_id,c.command_key)]=(fp,"add_task",pid);self.events.append((w.public_id,"task","created"));return v
    def task(self,t,p):
        v=self.tasks_by_id.get(p);return v if v and v.tenant_id==t else None
    def tasks(self,t,w,include_history=False):return tuple(x for x in self.tasks_by_id.values() if x.tenant_id==t and x.workflow_public_id==w and (include_history or x.status not in {TaskStatus.COMPLETED,TaskStatus.CANCELLED}))
    def change_task_status(self,c,fp):
        old=self._cmd(c,fp,"change_task_status")
        if old:return self.tasks_by_id[old[2]]
        v=self.task(c.tenant_id,c.task_public_id)
        if not v or v.row_version!=c.expected_version:return None
        v=replace(v,status=c.to_status,row_version=v.row_version+1);self.tasks_by_id[v.public_id]=v;self.commands[(c.tenant_id,c.command_key)]=(fp,"change_task_status",v.public_id);self.events.append((v.workflow_public_id,"task",c.to_status.value));return v
    def reassign_task(self,c,fp):
        old=self._cmd(c,fp,"reassign_task")
        if old:return self.tasks_by_id[old[2]]
        v=self.task(c.tenant_id,c.task_public_id)
        if not v or v.row_version!=c.expected_version:return None
        v=replace(v,assignee_resource_public_id=c.assignee_resource_public_id,row_version=v.row_version+1);self.tasks_by_id[v.public_id]=v;self.commands[(c.tenant_id,c.command_key)]=(fp,"reassign_task",v.public_id);self.events.append((v.workflow_public_id,"task","reassigned"));return v
    def request_approval(self,c,pid,fp):
        old=self._cmd(c,fp,"request_approval")
        if old:return self.approvals_by_id[old[2]]
        w=self.workflow(c.tenant_id,c.workflow_public_id)
        if not w or w.row_version!=c.expected_workflow_version or w.status is not WorkflowStatus.OPEN:return None
        if c.task_public_id and (not self.task(c.tenant_id,c.task_public_id) or self.task(c.tenant_id,c.task_public_id).workflow_public_id!=w.public_id):return None
        v=OperationalApproval(pid,c.tenant_id,w.public_id,c.approval_type_code,ApprovalStatus.PENDING,c.task_public_id,c.approver_resource_public_id,c.due_at,c.evidence_reference,None,1)
        self.approvals_by_id[pid]=v;self.workflows[w.public_id]=replace(w,row_version=w.row_version+1);self.commands[(c.tenant_id,c.command_key)]=(fp,"request_approval",pid);self.events.append((w.public_id,"approval","requested"));return v
    def approval(self,t,p):
        v=self.approvals_by_id.get(p);return v if v and v.tenant_id==t else None
    def approvals(self,t,w,include_history=False):return tuple(x for x in self.approvals_by_id.values() if x.tenant_id==t and x.workflow_public_id==w and (include_history or x.status is ApprovalStatus.PENDING))
    def decide_approval(self,c,fp):
        old=self._cmd(c,fp,"decide_approval")
        if old:return self.approvals_by_id[old[2]]
        v=self.approval(c.tenant_id,c.approval_public_id)
        if not v or v.row_version!=c.expected_version or v.status is not ApprovalStatus.PENDING:return None
        v=replace(v,status=c.decision,decision_note=c.decision_note,row_version=v.row_version+1);self.approvals_by_id[v.public_id]=v;self.commands[(c.tenant_id,c.command_key)]=(fp,"decide_approval",v.public_id);self.events.append((v.workflow_public_id,"approval",c.decision.value));return v
    def complete_workflow(self,c,fp):
        old=self._cmd(c,fp,"complete_workflow")
        if old:return self.workflows[old[2]]
        w=self.workflow(c.tenant_id,c.workflow_public_id)
        if not w or w.row_version!=c.expected_version or w.status is not WorkflowStatus.OPEN:return None
        if self.tasks(c.tenant_id,w.public_id) or self.approvals(c.tenant_id,w.public_id):return None
        w=replace(w,status=WorkflowStatus.COMPLETED,row_version=w.row_version+1);self.workflows[w.public_id]=w;self.commands[(c.tenant_id,c.command_key)]=(fp,"complete_workflow",w.public_id);self.events.append((w.public_id,"workflow","completed"));return w
    def cancel_workflow(self,c,fp):
        old=self._cmd(c,fp,"cancel_workflow")
        if old:return self.workflows[old[2]]
        w=self.workflow(c.tenant_id,c.workflow_public_id)
        if not w or w.row_version!=c.expected_version or w.status is not WorkflowStatus.OPEN:return None
        for k,v in list(self.tasks_by_id.items()):
            if v.tenant_id==c.tenant_id and v.workflow_public_id==w.public_id and v.status not in {TaskStatus.COMPLETED,TaskStatus.CANCELLED}:self.tasks_by_id[k]=replace(v,status=TaskStatus.CANCELLED,row_version=v.row_version+1)
        for k,v in list(self.approvals_by_id.items()):
            if v.tenant_id==c.tenant_id and v.workflow_public_id==w.public_id and v.status is ApprovalStatus.PENDING:self.approvals_by_id[k]=replace(v,status=ApprovalStatus.CANCELLED,row_version=v.row_version+1)
        w=replace(w,status=WorkflowStatus.CANCELLED,row_version=w.row_version+1);self.workflows[w.public_id]=w;self.commands[(c.tenant_id,c.command_key)]=(fp,"cancel_workflow",w.public_id);self.events.append((w.public_id,"workflow","cancelled"));return w
    def history(self,t,w):return tuple(x for x in self.events if x[0]==w)

def authority(repo=None,ids=None,permit=True):
    repo=repo or FakeRepo();ids=iter(ids or [W,T,A,UUID(int=61041),UUID(int=61042),UUID(int=61043),UUID(int=61044),UUID(int=61045)])
    def obj(t,p):return SimpleNamespace(tenant_id=t,public_id=p,status="active")
    return SO6Authority(repo,resource_resolver=lambda t,p:obj(t,p) if t==1 and p in {R,R2} else None,organization_resolver=lambda t,p:obj(t,p) if t==1 and p==O else None,location_resolver=lambda t,p:obj(t,p) if t==1 and p==L else None,authorize=lambda *x:permit,public_id_factory=lambda:next(ids)),repo

def test_workflow_task_resource_boundary_and_xa_queue_contract():
    so6,_=authority();w=so6.create_workflow(CreateWorkflow("w",1,"service_case","Case","service_order","SO-42",O,L,Priority.HIGH,NOW+timedelta(days=1)))
    t=so6.add_task(AddTask("t",1,w.public_id,w.row_version,"inspect","Inspect",R,"field_technician",Priority.NORMAL,NOW+timedelta(hours=2)))
    assert t.assignee_resource_public_id==R and t.workflow_public_id==w.public_id
    xa=json.loads((ROOT/'contracts/shared_operations/v1/so6_xa_metadata.json').read_text());assert xa['frontend_implementation']=='NONE' and xa['authorization_source']=='PC5' and xa['resource_source']=='SO5'

def test_task_transition_reassignment_history_and_exact_idempotency():
    so6,_=authority();cmd=CreateWorkflow("w",1,"review","Review","case","A-1",O,L);w=so6.create_workflow(cmd);assert so6.create_workflow(cmd)==w
    with pytest.raises(SO6AuthorityError,match='SO6_COMMAND_CONFLICT'):so6.create_workflow(replace(cmd,title='Changed'))
    t=so6.add_task(AddTask("t",1,w.public_id,w.row_version,"review","Review item",R));replay=so6.add_task(AddTask("t-replay",1,w.public_id,so6.workflow(1,w.public_id).row_version,"note","Second",R2))
    # keep the second task for cancellation/history coverage; transition the first
    t=so6.change_task_status(ChangeTaskStatus("start",1,t.public_id,t.row_version,TaskStatus.IN_PROGRESS,"started",NOW));t=so6.reassign_task(ReassignTask("reassign",1,t.public_id,t.row_version,R2,"handoff",NOW));t=so6.change_task_status(ChangeTaskStatus("done",1,t.public_id,t.row_version,TaskStatus.COMPLETED,"completed",NOW))
    assert t.status is TaskStatus.COMPLETED and t.assignee_resource_public_id==R2 and len(so6.history(1,w.public_id))>=5 and replay.status is TaskStatus.PENDING

def test_operational_approval_is_not_pc5_security_authority_and_blocks_completion_until_decided():
    so6,_=authority();w=so6.create_workflow(CreateWorkflow("w",1,"quality_case","Quality","case","Q-1",O,L));a=so6.request_approval(RequestOperationalApproval("a",1,w.public_id,w.row_version,"quality_release",None,R,NOW+timedelta(hours=1),"evidence:42"))
    w=so6.workflow(1,w.public_id)
    with pytest.raises(SO6AuthorityError,match='SO6_WORKFLOW_CONFLICT'):so6.complete_workflow(CompleteWorkflow("complete-early",1,w.public_id,w.row_version,"done",NOW))
    a=so6.decide_approval(DecideOperationalApproval("decide",1,a.public_id,a.row_version,ApprovalStatus.APPROVED,"reviewed",NOW,"Operationally acceptable"));assert a.status is ApprovalStatus.APPROVED
    w=so6.workflow(1,w.public_id);w=so6.complete_workflow(CompleteWorkflow("complete",1,w.public_id,w.row_version,"done",NOW));assert w.status is WorkflowStatus.COMPLETED
    authority_contract=json.loads((ROOT/'contracts/shared_operations/v1/so6_authority.json').read_text());assert authority_contract['security_approval_boundary']=='PC5_ONLY'

def test_cancel_is_explicit_and_preserves_history():
    so6,_=authority();w=so6.create_workflow(CreateWorkflow("w",1,"case","Case","source","1",O,L));t=so6.add_task(AddTask("t",1,w.public_id,w.row_version,"step","Step",R));w=so6.workflow(1,w.public_id);a=so6.request_approval(RequestOperationalApproval("a",1,w.public_id,w.row_version,"release",t.public_id,R));w=so6.workflow(1,w.public_id);w=so6.cancel_workflow(CancelWorkflow("cancel",1,w.public_id,w.row_version,"withdrawn",NOW));assert w.status is WorkflowStatus.CANCELLED and so6.task(1,t.public_id).status is TaskStatus.CANCELLED and so6.approval(1,a.public_id).status is ApprovalStatus.CANCELLED
    assert any(x[2]=='cancelled' for x in so6.history(1,w.public_id))

def test_tenant_isolation_and_server_permission_fail_closed():
    so6,_=authority()
    with pytest.raises(SO6AuthorityError,match='SO6_ORGANIZATION_NOT_FOUND'):so6.create_workflow(CreateWorkflow("x",2,"case","X","source","1",O,L))
    w=so6.create_workflow(CreateWorkflow("w",1,"case","W","source","1",O,L))
    with pytest.raises(SO6AuthorityError,match='SO6_RESOURCE_NOT_FOUND'):so6.add_task(AddTask("t",1,w.public_id,w.row_version,"step","Step",UUID(int=999)))
    denied,_=authority(permit=False)
    with pytest.raises(SO6AuthorityError,match='SO6_PERMISSION_DENIED'):denied.list_workflows(1)

def test_invalid_task_and_approval_transitions_fail_closed():
    so6,_=authority();w=so6.create_workflow(CreateWorkflow("w",1,"case","W","source","1",O,L));t=so6.add_task(AddTask("t",1,w.public_id,w.row_version,"step","Step",R));t=so6.change_task_status(ChangeTaskStatus("done",1,t.public_id,t.row_version,TaskStatus.COMPLETED,"done",NOW))
    with pytest.raises(SO6AuthorityError,match='SO6_INVALID_TASK_TRANSITION'):so6.change_task_status(ChangeTaskStatus("back",1,t.public_id,t.row_version,TaskStatus.IN_PROGRESS,"back",NOW))
    w=so6.workflow(1,w.public_id);a=so6.request_approval(RequestOperationalApproval("a",1,w.public_id,w.row_version,"release",t.public_id,R));a=so6.decide_approval(DecideOperationalApproval("d",1,a.public_id,a.row_version,ApprovalStatus.REJECTED,"rejected",NOW))
    with pytest.raises(SO6AuthorityError,match='SO6_APPROVAL_CLOSED'):so6.decide_approval(DecideOperationalApproval("d2",1,a.public_id,a.row_version,ApprovalStatus.APPROVED,"changed",NOW))

def test_neutral_profiles_and_forbidden_downstream_boundaries():
    a=json.loads((ROOT/'contracts/shared_operations/v1/examples/field_service_workflow_profile.json').read_text());b=json.loads((ROOT/'contracts/shared_operations/v1/examples/clinical_review_workflow_profile.json').read_text());assert a['terminology']!=b['terminology'] and a['workflow_types']!=b['workflow_types']
    sql=(ROOT/'alembic_neutral/sql/so6_workflows_tasks_operational_approvals_up.sql').read_text().lower()
    for forbidden in ('financial_events','journal_entries','financial_obligations','payment_settlements','protected_action_approvals','approval_decisions'):assert forbidden not in sql

def test_sql_tenant_qualified_resource_and_append_only_history_contract():
    sql=(ROOT/'alembic_neutral/sql/so6_workflows_tasks_operational_approvals_up.sql').read_text()
    assert 'REFERENCES public.so5_resources(tenant_id,id)' in sql and 'REFERENCES public.organization_units(tenant_id,id)' in sql and 'REFERENCES public.locations(tenant_id,id)' in sql
    assert 'so6_history_immutable' in sql and 'UNIQUE(tenant_id,workflow_id,id)' in sql
    repo=(ROOT/'shared_operations/so6/sql_repository.py').read_text();assert 'FOR UPDATE OF w' in repo and 'FOR UPDATE OF t' in repo and 'FOR UPDATE OF a' in repo
