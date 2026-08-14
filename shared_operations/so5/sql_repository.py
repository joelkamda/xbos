"""SQLAlchemy repository for SO5 resources and operational assignments."""
from __future__ import annotations
from types import SimpleNamespace
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO5AuthorityError

class SQLSO5Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,tenant,key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so5_resource_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).first()
        if row:
            if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO5AuthorityError("SO5_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
            return row
        return self.db_session.execute(text("INSERT INTO so5_resource_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *"),{"t":tenant,"k":key,"f":fingerprint,"y":kind}).one()
    def _complete(self,tenant,key,result_type,public_id):
        self.db_session.execute(text("UPDATE so5_resource_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"y":result_type,"p":str(public_id),"t":tenant,"k":key})
    def _ids(self,command):
        def scalar(table,public_id):
            return self.db_session.execute(text(f"SELECT id FROM {table} WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(public_id)}).scalar() if public_id else None
        return scalar("parties",command.party_public_id) if hasattr(command,"party_public_id") else None, scalar("organization_units",getattr(command,"organization_unit_public_id",None)), scalar("locations",getattr(command,"location_public_id",None))
    def _identity(self,tenant,public_id):
        if not public_id:return None
        return self.db_session.execute(text("SELECT i.id FROM identities i JOIN identity_memberships m ON m.identity_id=i.id AND m.tenant_id=:t AND m.status='active' WHERE i.public_id=:p AND i.status='active' ORDER BY m.id LIMIT 1"),{"t":tenant,"p":str(public_id)}).scalar()
    def create_resource(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"create_resource")
        if replay.result_public_id:return self.resource(command.tenant_id,replay.result_public_id)
        party,org,location=self._ids(command); identity=self._identity(command.tenant_id,command.identity_public_id)
        row=self.db_session.execute(text("""INSERT INTO so5_resources(public_id,tenant_id,resource_kind,classification_code,display_label,party_id,identity_id,organization_unit_id,location_id,lifecycle_status,capacity,exclusive_assignment,metadata) VALUES(:p,:t,:k,:c,:d,:party,:identity,:org,:loc,'active',:capacity,:exclusive,CAST(:metadata AS jsonb)) RETURNING id"""),{"p":str(public_id),"t":command.tenant_id,"k":command.resource_kind.value,"c":command.classification_code,"d":command.display_label,"party":party,"identity":identity,"org":org,"loc":location,"capacity":command.capacity,"exclusive":command.exclusive_assignment,"metadata":__import__('json').dumps(command.metadata,sort_keys=True)}).one()
        self.db_session.execute(text("INSERT INTO so5_resource_history(tenant_id,resource_id,event_type,to_status,reason_code,occurred_at) VALUES(:t,:r,'created','active','created',now())"),{"t":command.tenant_id,"r":row.id})
        self._complete(command.tenant_id,command.command_key,"resource",public_id);return self.resource(command.tenant_id,public_id)
    def _resource_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE" if lock else ""
        return self.db_session.execute(text("""SELECT r.*,p.public_id party_public_id,i.public_id identity_public_id,ou.public_id organization_public_id,l.public_id location_public_id FROM so5_resources r LEFT JOIN parties p ON (p.tenant_id,p.id)=(r.tenant_id,r.party_id) LEFT JOIN identities i ON i.id=r.identity_id LEFT JOIN organization_units ou ON (ou.tenant_id,ou.id)=(r.tenant_id,r.organization_unit_id) LEFT JOIN locations l ON (l.tenant_id,l.id)=(r.tenant_id,r.location_id) WHERE r.tenant_id=:t AND r.public_id=:p"""+(" FOR UPDATE OF r" if lock else "")),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _resource(value):
        if not value:return None
        return Resource(UUID(str(value.public_id)),value.tenant_id,ResourceKind(value.resource_kind),value.classification_code,value.display_label,ResourceStatus(value.lifecycle_status),value.capacity,value.exclusive_assignment,UUID(str(value.party_public_id)) if value.party_public_id else None,UUID(str(value.identity_public_id)) if value.identity_public_id else None,UUID(str(value.organization_public_id)) if value.organization_public_id else None,UUID(str(value.location_public_id)) if value.location_public_id else None,dict(value.metadata or {}),value.row_version)
    def resource(self,tenant_id,public_id):return self._resource(self._resource_row(tenant_id,public_id))
    def list_resources(self,tenant_id,classification_code=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so5_resources WHERE tenant_id=:t AND (:c IS NULL OR classification_code=:c) ORDER BY id"),{"t":tenant_id,"c":classification_code}).all()
        return tuple(self.resource(tenant_id,UUID(str(x.public_id))) for x in rows)
    def change_status(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"change_status")
        if replay.result_public_id:return self.resource(command.tenant_id,replay.result_public_id)
        current=self._resource_row(command.tenant_id,command.resource_public_id,True)
        if not current or current.row_version!=command.expected_version:return None
        self.db_session.execute(text("UPDATE so5_resources SET lifecycle_status=:s,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"s":command.to_status.value,"id":current.id})
        self.db_session.execute(text("INSERT INTO so5_resource_history(tenant_id,resource_id,event_type,from_status,to_status,reason_code,occurred_at) VALUES(:t,:r,'status_changed',:f,:s,:reason,:at)"),{"t":command.tenant_id,"r":current.id,"f":current.lifecycle_status,"s":command.to_status.value,"reason":command.reason_code,"at":command.occurred_at})
        self._complete(command.tenant_id,command.command_key,"resource",command.resource_public_id);return self.resource(command.tenant_id,command.resource_public_id)
    def assign(self,command,public_id,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"assign_resource")
        if replay.result_public_id:return self.assignment(command.tenant_id,replay.result_public_id)
        resource=self._resource_row(command.tenant_id,command.resource_public_id,True)
        if not resource or resource.row_version!=command.expected_resource_version:return None
        if resource.exclusive_assignment:
            overlap=self.db_session.execute(text("""SELECT 1 FROM so5_operational_assignments WHERE tenant_id=:t AND resource_id=:r AND lifecycle_status='active' AND tstzrange(effective_from,COALESCE(effective_to,'infinity'::timestamptz),'[)') && tstzrange(:f,COALESCE(:e,'infinity'::timestamptz),'[)') LIMIT 1"""),{"t":command.tenant_id,"r":resource.id,"f":command.effective_from,"e":command.effective_to}).first()
            if overlap:return None
        org=self.db_session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(command.organization_unit_public_id)}).scalar() if command.organization_unit_public_id else None
        location=self.db_session.execute(text("SELECT id FROM locations WHERE tenant_id=:t AND public_id=:p"),{"t":command.tenant_id,"p":str(command.location_public_id)}).scalar() if command.location_public_id else None
        row=self.db_session.execute(text("""INSERT INTO so5_operational_assignments(public_id,tenant_id,resource_id,capability_code,organization_unit_id,location_id,lifecycle_status,effective_from,effective_to,source_reference) VALUES(:p,:t,:r,:c,:o,:l,'active',:f,:e,:s) RETURNING id"""),{"p":str(public_id),"t":command.tenant_id,"r":resource.id,"c":command.capability_code,"o":org,"l":location,"f":command.effective_from,"e":command.effective_to,"s":command.source_reference}).one()
        self.db_session.execute(text("INSERT INTO so5_assignment_history(tenant_id,assignment_id,event_type,to_status,reason_code,occurred_at) VALUES(:t,:a,'assigned','active','assigned',:at)"),{"t":command.tenant_id,"a":row.id,"at":command.effective_from})
        self.db_session.execute(text("UPDATE so5_resources SET row_version=row_version+1,updated_at=now() WHERE id=:id"),{"id":resource.id})
        self._complete(command.tenant_id,command.command_key,"assignment",public_id);return self.assignment(command.tenant_id,public_id)
    def _assignment_row(self,tenant,public_id,lock=False):
        return self.db_session.execute(text("""SELECT a.*,r.public_id resource_public_id,ou.public_id organization_public_id,l.public_id location_public_id FROM so5_operational_assignments a JOIN so5_resources r ON (r.tenant_id,r.id)=(a.tenant_id,a.resource_id) LEFT JOIN organization_units ou ON (ou.tenant_id,ou.id)=(a.tenant_id,a.organization_unit_id) LEFT JOIN locations l ON (l.tenant_id,l.id)=(a.tenant_id,a.location_id) WHERE a.tenant_id=:t AND a.public_id=:p"""+(" FOR UPDATE OF a" if lock else "")),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _assignment(value):
        if not value:return None
        return OperationalAssignment(UUID(str(value.public_id)),value.tenant_id,UUID(str(value.resource_public_id)),value.capability_code,AssignmentStatus(value.lifecycle_status),value.effective_from,value.effective_to,UUID(str(value.organization_public_id)) if value.organization_public_id else None,UUID(str(value.location_public_id)) if value.location_public_id else None,value.source_reference,value.row_version)
    def assignment(self,tenant_id,public_id):return self._assignment(self._assignment_row(tenant_id,public_id))
    def end_assignment(self,command,fingerprint):
        replay=self._command(command.tenant_id,command.command_key,fingerprint,"end_assignment")
        if replay.result_public_id:return self.assignment(command.tenant_id,replay.result_public_id)
        current=self._assignment_row(command.tenant_id,command.assignment_public_id,True)
        if not current or current.row_version!=command.expected_version or current.lifecycle_status!='active' or command.ended_at<current.effective_from:return None
        self.db_session.execute(text("UPDATE so5_operational_assignments SET lifecycle_status='ended',effective_to=:at,row_version=row_version+1,updated_at=now() WHERE id=:id"),{"at":command.ended_at,"id":current.id})
        self.db_session.execute(text("INSERT INTO so5_assignment_history(tenant_id,assignment_id,event_type,from_status,to_status,reason_code,occurred_at) VALUES(:t,:a,'ended','active','ended',:reason,:at)"),{"t":command.tenant_id,"a":current.id,"reason":command.reason_code,"at":command.ended_at})
        self._complete(command.tenant_id,command.command_key,"assignment",command.assignment_public_id);return self.assignment(command.tenant_id,command.assignment_public_id)
    def assignments(self,tenant_id,resource_public_id,include_history=False):
        status="" if include_history else " AND a.lifecycle_status='active'"
        rows=self.db_session.execute(text("SELECT a.public_id FROM so5_operational_assignments a JOIN so5_resources r ON (r.tenant_id,r.id)=(a.tenant_id,a.resource_id) WHERE a.tenant_id=:t AND r.public_id=:p"+status+" ORDER BY a.id"),{"t":tenant_id,"p":str(resource_public_id)}).all()
        return tuple(self.assignment(tenant_id,UUID(str(x.public_id))) for x in rows)
    def history(self,tenant_id,resource_public_id):
        return tuple(self.db_session.execute(text("""SELECT 'resource' kind,h.event_type,h.from_status,h.to_status,h.reason_code,h.occurred_at FROM so5_resource_history h JOIN so5_resources r ON (r.tenant_id,r.id)=(h.tenant_id,h.resource_id) WHERE h.tenant_id=:t AND r.public_id=:p UNION ALL SELECT 'assignment',h.event_type,h.from_status,h.to_status,h.reason_code,h.occurred_at FROM so5_assignment_history h JOIN so5_operational_assignments a ON (a.tenant_id,a.id)=(h.tenant_id,h.assignment_id) JOIN so5_resources r ON (r.tenant_id,r.id)=(a.tenant_id,a.resource_id) WHERE h.tenant_id=:t AND r.public_id=:p ORDER BY occurred_at"""),{"t":tenant_id,"p":str(resource_public_id)}).mappings())
