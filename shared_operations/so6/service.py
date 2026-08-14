"""SO6 neutral workflow, task, and operational-approval authority."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class SO6AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code; self.category=category; self.safe_explanation=explanation; self.retryable=retryable
        super().__init__(code)

class SO6Repository(Protocol):
    def create_workflow(self,command,public_id,fingerprint)->Workflow: ...
    def workflow(self,tenant_id,public_id)->Workflow|None: ...
    def list_workflows(self,tenant_id,status=None): ...
    def add_task(self,command,public_id,fingerprint)->WorkflowTask|None: ...
    def task(self,tenant_id,public_id)->WorkflowTask|None: ...
    def tasks(self,tenant_id,workflow_public_id,include_history=False): ...
    def change_task_status(self,command,fingerprint)->WorkflowTask|None: ...
    def reassign_task(self,command,fingerprint)->WorkflowTask|None: ...
    def request_approval(self,command,public_id,fingerprint)->OperationalApproval|None: ...
    def approval(self,tenant_id,public_id)->OperationalApproval|None: ...
    def approvals(self,tenant_id,workflow_public_id,include_history=False): ...
    def decide_approval(self,command,fingerprint)->OperationalApproval|None: ...
    def complete_workflow(self,command,fingerprint)->Workflow|None: ...
    def cancel_workflow(self,command,fingerprint)->Workflow|None: ...
    def history(self,tenant_id,workflow_public_id): ...

class SO6Authority:
    def __init__(self,repository:SO6Repository,*,resource_resolver:Callable,organization_resolver:Callable,
                 location_resolver:Callable,authorize:Callable,public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository; self.resource_resolver=resource_resolver; self.organization_resolver=organization_resolver
        self.location_resolver=location_resolver; self.authorize=authorize; self.public_id_factory=public_id_factory
    @staticmethod
    def _fingerprint(command):return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _code(value,field):
        value=value.strip().lower()
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):
            raise SO6AuthorityError("SO6_INVALID_"+field.upper(),"validation_failure",field+" must be a neutral code")
        return value
    @staticmethod
    def _text(value,field,max_length=240):
        value=value.strip()
        if not value or len(value)>max_length:raise SO6AuthorityError("SO6_INVALID_"+field.upper(),"validation_failure",field+" is required and bounded")
        return value
    def _permit(self,tenant,permission,scope_type="tenant",scope_id=None):
        if not self.authorize(tenant,permission,scope_type,tenant if scope_id is None else scope_id):
            raise SO6AuthorityError("SO6_PERMISSION_DENIED","permission_denied","The workflow operation is not permitted")
    @staticmethod
    def _owned(value,tenant,public_id,code):
        if value is None or getattr(value,"tenant_id",None)!=tenant or UUID(str(getattr(value,"public_id",UUID(int=0))))!=public_id:
            raise SO6AuthorityError(code,"scope_mismatch","The referenced authority was not found in this tenant")
        return value
    def _context(self,tenant,org,location):
        if org:self._owned(self.organization_resolver(tenant,org),tenant,org,"SO6_ORGANIZATION_NOT_FOUND")
        if location:self._owned(self.location_resolver(tenant,location),tenant,location,"SO6_LOCATION_NOT_FOUND")
    def _resource(self,tenant,public_id):
        if public_id is None:return None
        value=self._owned(self.resource_resolver(tenant,public_id),tenant,public_id,"SO6_RESOURCE_NOT_FOUND")
        status=getattr(value,"status",None)
        if status is not None and str(getattr(status,"value",status))!="active":raise SO6AuthorityError("SO6_RESOURCE_NOT_ACTIVE","invalid_state_transition","Only active SO5 resources may receive operational work")
        return value
    def create_workflow(self,command:CreateWorkflow):
        self._permit(command.tenant_id,"workflow.create")
        self._context(command.tenant_id,command.organization_unit_public_id,command.location_public_id)
        normalized=replace(command,workflow_type_code=self._code(command.workflow_type_code,"workflow_type_code"),title=self._text(command.title,"title"),subject_authority=self._code(command.subject_authority,"subject_authority"),subject_reference=self._text(command.subject_reference,"subject_reference"))
        return self.repository.create_workflow(normalized,self.public_id_factory(),self._fingerprint(normalized))
    def workflow(self,tenant_id,public_id):
        self._permit(tenant_id,"workflow.read","workflow",public_id);value=self.repository.workflow(tenant_id,public_id)
        if value is None:raise SO6AuthorityError("SO6_WORKFLOW_NOT_FOUND","not_found","The workflow was not found")
        return value
    def list_workflows(self,tenant_id,status=None):
        self._permit(tenant_id,"workflow.read")
        return self.repository.list_workflows(tenant_id,status)
    def add_task(self,command:AddTask):
        self._permit(command.tenant_id,"workflow.task.create","workflow",command.workflow_public_id)
        current=self.repository.workflow(command.tenant_id,command.workflow_public_id)
        if current is None:raise SO6AuthorityError("SO6_WORKFLOW_NOT_FOUND","not_found","The workflow was not found")
        if current.status is not WorkflowStatus.OPEN:raise SO6AuthorityError("SO6_WORKFLOW_CLOSED","invalid_state_transition","Tasks may only be added to open workflows")
        self._resource(command.tenant_id,command.assignee_resource_public_id)
        capability=self._code(command.required_capability_code,"required_capability_code") if command.required_capability_code else None
        normalized=replace(command,task_type_code=self._code(command.task_type_code,"task_type_code"),title=self._text(command.title,"title"),required_capability_code=capability)
        result=self.repository.add_task(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_WORKFLOW_CONFLICT","stale_version","The workflow changed; reload before retrying",retryable=True)
        return result
    def task(self,tenant_id,public_id):
        self._permit(tenant_id,"workflow.task.read","task",public_id);value=self.repository.task(tenant_id,public_id)
        if value is None:raise SO6AuthorityError("SO6_TASK_NOT_FOUND","not_found","The task was not found")
        return value
    def tasks(self,tenant_id,workflow_public_id,include_history=False):
        self._permit(tenant_id,"workflow.task.read","workflow",workflow_public_id)
        if self.repository.workflow(tenant_id,workflow_public_id) is None:raise SO6AuthorityError("SO6_WORKFLOW_NOT_FOUND","not_found","The workflow was not found")
        return self.repository.tasks(tenant_id,workflow_public_id,include_history)
    def change_task_status(self,command:ChangeTaskStatus):
        self._permit(command.tenant_id,"workflow.task.transition","task",command.task_public_id)
        current=self.repository.task(command.tenant_id,command.task_public_id)
        if current is None:raise SO6AuthorityError("SO6_TASK_NOT_FOUND","not_found","The task was not found")
        allowed={TaskStatus.PENDING:{TaskStatus.IN_PROGRESS,TaskStatus.COMPLETED,TaskStatus.CANCELLED},TaskStatus.IN_PROGRESS:{TaskStatus.COMPLETED,TaskStatus.CANCELLED},TaskStatus.COMPLETED:set(),TaskStatus.CANCELLED:set()}
        if command.to_status not in allowed[current.status]:raise SO6AuthorityError("SO6_INVALID_TASK_TRANSITION","invalid_state_transition","The requested task transition is not allowed")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.change_task_status(normalized,self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_STALE_TASK","stale_version","The task changed; reload before retrying",retryable=True)
        return result
    def reassign_task(self,command:ReassignTask):
        self._permit(command.tenant_id,"workflow.task.reassign","task",command.task_public_id)
        current=self.repository.task(command.tenant_id,command.task_public_id)
        if current is None:raise SO6AuthorityError("SO6_TASK_NOT_FOUND","not_found","The task was not found")
        if current.status in {TaskStatus.COMPLETED,TaskStatus.CANCELLED}:raise SO6AuthorityError("SO6_TASK_CLOSED","invalid_state_transition","Closed tasks cannot be reassigned")
        self._resource(command.tenant_id,command.assignee_resource_public_id)
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.reassign_task(normalized,self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_STALE_TASK","stale_version","The task changed; reload before retrying",retryable=True)
        return result
    def request_approval(self,command:RequestOperationalApproval):
        self._permit(command.tenant_id,"workflow.approval.request","workflow",command.workflow_public_id)
        workflow=self.repository.workflow(command.tenant_id,command.workflow_public_id)
        if workflow is None:raise SO6AuthorityError("SO6_WORKFLOW_NOT_FOUND","not_found","The workflow was not found")
        if workflow.status is not WorkflowStatus.OPEN:raise SO6AuthorityError("SO6_WORKFLOW_CLOSED","invalid_state_transition","Operational approvals may only be requested on open workflows")
        if command.task_public_id:
            task=self.repository.task(command.tenant_id,command.task_public_id)
            if task is None or task.workflow_public_id!=command.workflow_public_id:raise SO6AuthorityError("SO6_TASK_SCOPE_MISMATCH","scope_mismatch","The task is not part of this workflow")
        self._resource(command.tenant_id,command.approver_resource_public_id)
        normalized=replace(command,approval_type_code=self._code(command.approval_type_code,"approval_type_code"),evidence_reference=self._text(command.evidence_reference,"evidence_reference") if command.evidence_reference else None)
        result=self.repository.request_approval(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_WORKFLOW_CONFLICT","stale_version","The workflow changed; reload before retrying",retryable=True)
        return result
    def approval(self,tenant_id,public_id):
        self._permit(tenant_id,"workflow.approval.read","approval",public_id);value=self.repository.approval(tenant_id,public_id)
        if value is None:raise SO6AuthorityError("SO6_APPROVAL_NOT_FOUND","not_found","The operational approval was not found")
        return value
    def approvals(self,tenant_id,workflow_public_id,include_history=False):
        self._permit(tenant_id,"workflow.approval.read","workflow",workflow_public_id)
        if self.repository.workflow(tenant_id,workflow_public_id) is None:raise SO6AuthorityError("SO6_WORKFLOW_NOT_FOUND","not_found","The workflow was not found")
        return self.repository.approvals(tenant_id,workflow_public_id,include_history)
    def decide_approval(self,command:DecideOperationalApproval):
        self._permit(command.tenant_id,"workflow.approval.decide","approval",command.approval_public_id)
        if command.decision not in {ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}:raise SO6AuthorityError("SO6_INVALID_APPROVAL_DECISION","validation_failure","Operational approval decisions are approve or reject")
        current=self.repository.approval(command.tenant_id,command.approval_public_id)
        if current is None:raise SO6AuthorityError("SO6_APPROVAL_NOT_FOUND","not_found","The operational approval was not found")
        if current.status is not ApprovalStatus.PENDING:raise SO6AuthorityError("SO6_APPROVAL_CLOSED","invalid_state_transition","The operational approval is already decided")
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"),decision_note=command.decision_note.strip() if command.decision_note else None)
        result=self.repository.decide_approval(normalized,self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_STALE_APPROVAL","stale_version","The operational approval changed; reload before retrying",retryable=True)
        return result
    def complete_workflow(self,command:CompleteWorkflow):
        self._permit(command.tenant_id,"workflow.complete","workflow",command.workflow_public_id)
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.complete_workflow(normalized,self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_WORKFLOW_CONFLICT","conflict","The workflow changed or still has open work",retryable=True)
        return result
    def cancel_workflow(self,command:CancelWorkflow):
        self._permit(command.tenant_id,"workflow.cancel","workflow",command.workflow_public_id)
        normalized=replace(command,reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.cancel_workflow(normalized,self._fingerprint(normalized))
        if result is None:raise SO6AuthorityError("SO6_WORKFLOW_CONFLICT","conflict","The workflow changed or cannot be cancelled",retryable=True)
        return result
    def history(self,tenant_id,workflow_public_id):
        self._permit(tenant_id,"workflow.history.read","workflow",workflow_public_id)
        if self.repository.workflow(tenant_id,workflow_public_id) is None:raise SO6AuthorityError("SO6_WORKFLOW_NOT_FOUND","not_found","The workflow was not found")
        return self.repository.history(tenant_id,workflow_public_id)
