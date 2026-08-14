"""SQLAlchemy repository for SO6 workflows, tasks, and operational approvals."""
from __future__ import annotations
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO6AuthorityError

class SQLSO6Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,tenant,key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so6_workflow_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).first()
        if row:
            if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO6AuthorityError("SO6_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
            return row
        return self.db_session.execute(text("INSERT INTO so6_workflow_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *"),{"t":tenant,"k":key,"f":fingerprint,"y":kind}).one()
    def _complete(self,tenant,key,result_type,public_id):
        self.db_session.execute(text("UPDATE so6_workflow_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"y":result_type,"p":str(public_id),"t":tenant,"k":key})
    def _id(self,table,tenant,public_id):
        if public_id is None:return None
        return self.db_session.execute(text(f"SELECT id FROM {table} WHERE tenant_id=:t AND public_id=:p"),{"t":tenant,"p":str(public_id)}).scalar()
    def _workflow_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE OF w" if lock else ""
        return self.db_session.execute(text("""SELECT w.*,ou.public_id organization_public_id,l.public_id location_public_id FROM so6_workflows w LEFT JOIN organization_units ou ON (ou.tenant_id,ou.id)=(w.tenant_id,w.organization_unit_id) LEFT JOIN locations l ON (l.tenant_id,l.id)=(w.tenant_id,w.location_id) WHERE w.tenant_id=:t AND w.public_id=:p"""+suffix),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _workflow(value):
        if not value:return None
        return Workflow(UUID(str(value.public_id)),value.tenant_id,value.workflow_type_code,value.title,WorkflowStatus(value.lifecycle_status),Priority(value.priority),value.subject_authority,value.subject_reference,value.due_at,UUID(str(value.organization_public_id)) if value.organization_public_id else None,UUID(str(value.location_public_id)) if value.location_public_id else None,value.metadata,value.row_version)
    def create_workflow(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"create_workflow")
        if replay.result_public_id:return self.workflow(command.tenant_id,replay.result_public_id)
        org=self._id("organization_units",command.tenant_id,command.organization_unit_public_id);loc=self._id("locations",command.tenant_id,command.location_public_id)
        row=self.db_session.execute(text("""INSERT INTO so6_workflows(public_id,tenant_id,workflow_type_code,title,subject_authority,subject_reference,organization_unit_id,location_id,lifecycle_status,priority,due_at,metadata) VALUES(:p,:t,:w,:title,:sa,:sr,:org,:loc,'open',:priority,:due,CAST(:metadata AS jsonb)) RETURNING id"""),{"p":str(public_id),"t":command.tenant_id,"w":command.workflow_type_code,"title":command.title,"sa":command.subject_authority,"sr":command.subject_reference,"org":org,"loc":loc,"priority":command.priority.value,"due":command.due_at,"metadata":__import__('json').dumps(command.metadata,sort_keys=True)}).one()
        self._history(command.tenant_id,row.id,None,None,"workflow","created",None,"open","created",None)
        self._complete(command.tenant_id,command.command_key,"workflow",public_id);return self.workflow(command.tenant_id,public_id)
    def workflow(self,tenant_id,public_id):return self._workflow(self._workflow_row(tenant_id,public_id))
    def list_workflows(self,tenant_id,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so6_workflows WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY id"),{"t":tenant_id,"s":getattr(status,"value",status)}).all()
        return tuple(self.workflow(tenant_id,UUID(str(r.public_id))) for r in rows)
    def _task_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE OF t" if lock else ""
        return self.db_session.execute(text("""SELECT t.*,w.public_id workflow_public_id,r.public_id assignee_resource_public_id FROM so6_workflow_tasks t JOIN so6_workflows w ON (w.tenant_id,w.id)=(t.tenant_id,t.workflow_id) LEFT JOIN so5_resources r ON (r.tenant_id,r.id)=(t.tenant_id,t.assignee_resource_id) WHERE t.tenant_id=:tenant AND t.public_id=:p"""+suffix),{"tenant":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _task(value):
        if not value:return None
        return WorkflowTask(UUID(str(value.public_id)),value.tenant_id,UUID(str(value.workflow_public_id)),value.task_type_code,value.title,TaskStatus(value.lifecycle_status),Priority(value.priority),value.due_at,UUID(str(value.assignee_resource_public_id)) if value.assignee_resource_public_id else None,value.required_capability_code,value.metadata,value.row_version)
    def add_task(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"add_task")
        if replay.result_public_id:return self.task(command.tenant_id,replay.result_public_id)
        w=self._workflow_row(command.tenant_id,command.workflow_public_id,True)
        if not w or w.row_version!=command.expected_workflow_version or w.lifecycle_status!="open":return None
        resource=self._id("so5_resources",command.tenant_id,command.assignee_resource_public_id)
        row=self.db_session.execute(text("""INSERT INTO so6_workflow_tasks(public_id,tenant_id,workflow_id,task_type_code,title,assignee_resource_id,required_capability_code,lifecycle_status,priority,due_at,metadata) VALUES(:p,:t,:w,:type,:title,:r,:cap,'pending',:priority,:due,CAST(:metadata AS jsonb)) RETURNING id"""),{"p":str(public_id),"t":command.tenant_id,"w":w.id,"type":command.task_type_code,"title":command.title,"r":resource,"cap":command.required_capability_code,"priority":command.priority.value,"due":command.due_at,"metadata":__import__('json').dumps(command.metadata,sort_keys=True)}).one()
        self.db_session.execute(text("UPDATE so6_workflows SET row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:w"),{"t":command.tenant_id,"w":w.id})
        self._history(command.tenant_id,w.id,row.id,None,"task","created",None,"pending","created",None)
        self._complete(command.tenant_id,command.command_key,"task",public_id);return self.task(command.tenant_id,public_id)
    def task(self,tenant_id,public_id):return self._task(self._task_row(tenant_id,public_id))
    def tasks(self,tenant_id,workflow_public_id,include_history=False):
        w=self._workflow_row(tenant_id,workflow_public_id)
        if not w:return ()
        clause="" if include_history else " AND lifecycle_status NOT IN ('completed','cancelled')"
        rows=self.db_session.execute(text("SELECT public_id FROM so6_workflow_tasks WHERE tenant_id=:t AND workflow_id=:w"+clause+" ORDER BY id"),{"t":tenant_id,"w":w.id}).all()
        return tuple(self.task(tenant_id,UUID(str(r.public_id))) for r in rows)
    def change_task_status(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"change_task_status")
        if replay.result_public_id:return self.task(command.tenant_id,replay.result_public_id)
        row=self._task_row(command.tenant_id,command.task_public_id,True)
        if not row or row.row_version!=command.expected_version:return None
        updated=self.db_session.execute(text("UPDATE so6_workflow_tasks SET lifecycle_status=:s,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v RETURNING workflow_id"),{"s":command.to_status.value,"t":command.tenant_id,"id":row.id,"v":command.expected_version}).first()
        if not updated:return None
        self._history(command.tenant_id,updated.workflow_id,row.id,None,"task","status_changed",row.lifecycle_status,command.to_status.value,command.reason_code,command.occurred_at)
        self._complete(command.tenant_id,command.command_key,"task",command.task_public_id);return self.task(command.tenant_id,command.task_public_id)
    def reassign_task(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"reassign_task")
        if replay.result_public_id:return self.task(command.tenant_id,replay.result_public_id)
        row=self._task_row(command.tenant_id,command.task_public_id,True)
        if not row or row.row_version!=command.expected_version:return None
        resource=self._id("so5_resources",command.tenant_id,command.assignee_resource_public_id)
        updated=self.db_session.execute(text("UPDATE so6_workflow_tasks SET assignee_resource_id=:r,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v RETURNING workflow_id"),{"r":resource,"t":command.tenant_id,"id":row.id,"v":command.expected_version}).first()
        if not updated:return None
        self._history(command.tenant_id,updated.workflow_id,row.id,None,"task","reassigned",row.lifecycle_status,row.lifecycle_status,command.reason_code,command.occurred_at)
        self._complete(command.tenant_id,command.command_key,"task",command.task_public_id);return self.task(command.tenant_id,command.task_public_id)
    def _approval_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE OF a" if lock else ""
        return self.db_session.execute(text("""SELECT a.*,w.public_id workflow_public_id,t.public_id task_public_id,r.public_id approver_resource_public_id FROM so6_operational_approvals a JOIN so6_workflows w ON (w.tenant_id,w.id)=(a.tenant_id,a.workflow_id) LEFT JOIN so6_workflow_tasks t ON (t.tenant_id,t.workflow_id,t.id)=(a.tenant_id,a.workflow_id,a.task_id) LEFT JOIN so5_resources r ON (r.tenant_id,r.id)=(a.tenant_id,a.approver_resource_id) WHERE a.tenant_id=:tenant AND a.public_id=:p"""+suffix),{"tenant":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _approval(value):
        if not value:return None
        return OperationalApproval(UUID(str(value.public_id)),value.tenant_id,UUID(str(value.workflow_public_id)),value.approval_type_code,ApprovalStatus(value.lifecycle_status),UUID(str(value.task_public_id)) if value.task_public_id else None,UUID(str(value.approver_resource_public_id)) if value.approver_resource_public_id else None,value.due_at,value.evidence_reference,value.decision_note,value.row_version)
    def request_approval(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"request_approval")
        if replay.result_public_id:return self.approval(command.tenant_id,replay.result_public_id)
        w=self._workflow_row(command.tenant_id,command.workflow_public_id,True)
        if not w or w.row_version!=command.expected_workflow_version or w.lifecycle_status!="open":return None
        task=self._id("so6_workflow_tasks",command.tenant_id,command.task_public_id);resource=self._id("so5_resources",command.tenant_id,command.approver_resource_public_id)
        if command.task_public_id:
            scoped=self.db_session.execute(text("SELECT 1 FROM so6_workflow_tasks WHERE tenant_id=:t AND id=:task AND workflow_id=:w"),{"t":command.tenant_id,"task":task,"w":w.id}).scalar()
            if not scoped:return None
        row=self.db_session.execute(text("""INSERT INTO so6_operational_approvals(public_id,tenant_id,workflow_id,task_id,approval_type_code,approver_resource_id,lifecycle_status,due_at,evidence_reference) VALUES(:p,:t,:w,:task,:type,:r,'pending',:due,:evidence) RETURNING id"""),{"p":str(public_id),"t":command.tenant_id,"w":w.id,"task":task,"type":command.approval_type_code,"r":resource,"due":command.due_at,"evidence":command.evidence_reference}).one()
        self.db_session.execute(text("UPDATE so6_workflows SET row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:w"),{"t":command.tenant_id,"w":w.id})
        self._history(command.tenant_id,w.id,task,row.id,"approval","requested",None,"pending","requested",None)
        self._complete(command.tenant_id,command.command_key,"approval",public_id);return self.approval(command.tenant_id,public_id)
    def approval(self,tenant_id,public_id):return self._approval(self._approval_row(tenant_id,public_id))
    def approvals(self,tenant_id,workflow_public_id,include_history=False):
        w=self._workflow_row(tenant_id,workflow_public_id)
        if not w:return ()
        clause="" if include_history else " AND lifecycle_status='pending'"
        rows=self.db_session.execute(text("SELECT public_id FROM so6_operational_approvals WHERE tenant_id=:t AND workflow_id=:w"+clause+" ORDER BY id"),{"t":tenant_id,"w":w.id}).all()
        return tuple(self.approval(tenant_id,UUID(str(r.public_id))) for r in rows)
    def decide_approval(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"decide_approval")
        if replay.result_public_id:return self.approval(command.tenant_id,replay.result_public_id)
        row=self._approval_row(command.tenant_id,command.approval_public_id,True)
        if not row or row.row_version!=command.expected_version or row.lifecycle_status!="pending":return None
        updated=self.db_session.execute(text("UPDATE so6_operational_approvals SET lifecycle_status=:s,decision_note=:note,decided_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v AND lifecycle_status='pending' RETURNING workflow_id,task_id"),{"s":command.decision.value,"note":command.decision_note,"at":command.occurred_at,"t":command.tenant_id,"id":row.id,"v":command.expected_version}).first()
        if not updated:return None
        self._history(command.tenant_id,updated.workflow_id,updated.task_id,row.id,"approval","decided","pending",command.decision.value,command.reason_code,command.occurred_at)
        self._complete(command.tenant_id,command.command_key,"approval",command.approval_public_id);return self.approval(command.tenant_id,command.approval_public_id)
    def complete_workflow(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"complete_workflow")
        if replay.result_public_id:return self.workflow(command.tenant_id,replay.result_public_id)
        w=self._workflow_row(command.tenant_id,command.workflow_public_id,True)
        if not w or w.row_version!=command.expected_version or w.lifecycle_status!="open":return None
        open_tasks=self.db_session.execute(text("SELECT count(*) FROM so6_workflow_tasks WHERE tenant_id=:t AND workflow_id=:w AND lifecycle_status NOT IN ('completed','cancelled')"),{"t":command.tenant_id,"w":w.id}).scalar_one()
        pending=self.db_session.execute(text("SELECT count(*) FROM so6_operational_approvals WHERE tenant_id=:t AND workflow_id=:w AND lifecycle_status='pending'"),{"t":command.tenant_id,"w":w.id}).scalar_one()
        if open_tasks or pending:return None
        self.db_session.execute(text("UPDATE so6_workflows SET lifecycle_status='completed',row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:w"),{"t":command.tenant_id,"w":w.id})
        self._history(command.tenant_id,w.id,None,None,"workflow","completed","open","completed",command.reason_code,command.occurred_at)
        self._complete(command.tenant_id,command.command_key,"workflow",command.workflow_public_id);return self.workflow(command.tenant_id,command.workflow_public_id)
    def cancel_workflow(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"cancel_workflow")
        if replay.result_public_id:return self.workflow(command.tenant_id,replay.result_public_id)
        w=self._workflow_row(command.tenant_id,command.workflow_public_id,True)
        if not w or w.row_version!=command.expected_version or w.lifecycle_status!="open":return None
        task_rows=self.db_session.execute(text("SELECT id,lifecycle_status FROM so6_workflow_tasks WHERE tenant_id=:t AND workflow_id=:w AND lifecycle_status NOT IN ('completed','cancelled') FOR UPDATE"),{"t":command.tenant_id,"w":w.id}).all()
        for task in task_rows:
            self.db_session.execute(text("UPDATE so6_workflow_tasks SET lifecycle_status='cancelled',row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id"),{"t":command.tenant_id,"id":task.id})
            self._history(command.tenant_id,w.id,task.id,None,"task","cancelled",task.lifecycle_status,"cancelled",command.reason_code,command.occurred_at)
        approval_rows=self.db_session.execute(text("SELECT id,task_id FROM so6_operational_approvals WHERE tenant_id=:t AND workflow_id=:w AND lifecycle_status='pending' FOR UPDATE"),{"t":command.tenant_id,"w":w.id}).all()
        for approval in approval_rows:
            self.db_session.execute(text("UPDATE so6_operational_approvals SET lifecycle_status='cancelled',row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id"),{"t":command.tenant_id,"id":approval.id})
            self._history(command.tenant_id,w.id,approval.task_id,approval.id,"approval","cancelled","pending","cancelled",command.reason_code,command.occurred_at)
        self.db_session.execute(text("UPDATE so6_workflows SET lifecycle_status='cancelled',row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:w"),{"t":command.tenant_id,"w":w.id})
        self._history(command.tenant_id,w.id,None,None,"workflow","cancelled","open","cancelled",command.reason_code,command.occurred_at)
        self._complete(command.tenant_id,command.command_key,"workflow",command.workflow_public_id);return self.workflow(command.tenant_id,command.workflow_public_id)
    def _history(self,tenant,workflow_id,task_id,approval_id,entity_type,event_type,from_status,to_status,reason_code,occurred_at):
        self.db_session.execute(text("""INSERT INTO so6_workflow_history(tenant_id,workflow_id,task_id,approval_id,entity_type,event_type,from_status,to_status,reason_code,occurred_at) VALUES(:t,:w,:task,:approval,:entity,:event,:froms,:tos,:reason,COALESCE(:at,now()))"""),{"t":tenant,"w":workflow_id,"task":task_id,"approval":approval_id,"entity":entity_type,"event":event_type,"froms":from_status,"tos":to_status,"reason":reason_code or event_type,"at":occurred_at})
    def history(self,tenant_id,workflow_public_id):
        w=self._workflow_row(tenant_id,workflow_public_id)
        if not w:return ()
        return tuple(self.db_session.execute(text("SELECT entity_type,event_type,from_status,to_status,reason_code,occurred_at FROM so6_workflow_history WHERE tenant_id=:t AND workflow_id=:w ORDER BY sequence"),{"t":tenant_id,"w":w.id}).all())
