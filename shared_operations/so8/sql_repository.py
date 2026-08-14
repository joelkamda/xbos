"""SQLAlchemy repository for SO8 operational delivery and offline synchronization."""
from __future__ import annotations
import json
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO8AuthorityError

class SQLSO8Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,tenant,key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so8_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).first()
        if row:
            if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO8AuthorityError("SO8_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
            return row
        return self.db_session.execute(text("INSERT INTO so8_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *"),{"t":tenant,"k":key,"f":fingerprint,"y":kind}).one()
    def _complete(self,tenant,key,result_type,public_id):
        self.db_session.execute(text("UPDATE so8_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"y":result_type,"p":str(public_id),"t":tenant,"k":key})
    def _delivery_row(self,tenant,public_id,lock=False):
        suffix=" FOR UPDATE OF j" if lock else ""
        return self.db_session.execute(text("SELECT j.* FROM so8_delivery_jobs j WHERE j.tenant_id=:t AND j.public_id=:p"+suffix),{"t":tenant,"p":str(public_id)}).first()
    @staticmethod
    def _delivery(v):
        if not v:return None
        return DeliveryJob(UUID(str(v.public_id)),v.tenant_id,v.delivery_kind,v.channel_code,v.destination_reference,DeliveryStatus(v.lifecycle_status),v.available_at,v.max_attempts,v.attempt_count,v.subject_authority,v.subject_reference,UUID(str(v.document_version_public_id)) if v.document_version_public_id else None,v.payload,v.payload_sha256,v.worker_reference,v.lease_until,v.row_version)
    def create_delivery(self,c,p,fp,payload_sha256):
        replay=self._command(c.tenant_id,c.command_key,fp,"create_delivery")
        if replay.result_public_id:return self.delivery(c.tenant_id,replay.result_public_id)
        self.db_session.execute(text("""INSERT INTO so8_delivery_jobs(public_id,tenant_id,delivery_kind,channel_code,destination_reference,subject_authority,subject_reference,document_version_public_id,payload,payload_sha256,available_at,max_attempts,lifecycle_status) VALUES(:p,:t,:k,:c,:d,:sa,:sr,:dv,CAST(:payload AS jsonb),:sha,:at,:m,'pending')"""),{"p":str(p),"t":c.tenant_id,"k":c.delivery_kind,"c":c.channel_code,"d":c.destination_reference,"sa":c.subject_authority,"sr":c.subject_reference,"dv":str(c.document_version_public_id) if c.document_version_public_id else None,"payload":json.dumps(c.payload,sort_keys=True),"sha":payload_sha256,"at":c.available_at,"m":c.max_attempts})
        self._complete(c.tenant_id,c.command_key,"delivery",p);return self.delivery(c.tenant_id,p)
    def delivery(self,t,p):return self._delivery(self._delivery_row(t,p))
    def list_deliveries(self,t,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so8_delivery_jobs WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY id"),{"t":t,"s":getattr(status,"value",status)}).all();return tuple(self.delivery(t,UUID(str(x.public_id))) for x in rows)
    def due_deliveries(self,t,as_of,limit=50):
        rows=self.db_session.execute(text("""SELECT public_id FROM so8_delivery_jobs WHERE tenant_id=:t AND lifecycle_status IN('pending','retry_wait') AND available_at<=:at AND (lease_until IS NULL OR lease_until<=:at) ORDER BY available_at,id LIMIT :limit"""),{"t":t,"at":as_of,"limit":limit}).all();return tuple(self.delivery(t,UUID(str(x.public_id))) for x in rows)
    def claim_delivery(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"claim_delivery")
        if replay.result_public_id:return self.delivery(c.tenant_id,replay.result_public_id)
        j=self._delivery_row(c.tenant_id,c.job_public_id,True)
        if not j or j.row_version!=c.expected_version or j.lifecycle_status not in ("pending","retry_wait") or j.available_at>c.occurred_at or (j.lease_until and j.lease_until>c.occurred_at):return None
        updated=self.db_session.execute(text("""UPDATE so8_delivery_jobs SET lifecycle_status='in_progress',worker_reference=:w,lease_until=:lease,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v RETURNING id"""),{"w":c.worker_reference,"lease":c.lease_until,"t":c.tenant_id,"id":j.id,"v":c.expected_version}).first()
        if not updated:return None
        self._complete(c.tenant_id,c.command_key,"delivery",c.job_public_id);return self.delivery(c.tenant_id,c.job_public_id)
    def record_attempt(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"record_attempt")
        if replay.result_public_id:return self.delivery(c.tenant_id,replay.result_public_id)
        j=self._delivery_row(c.tenant_id,c.job_public_id,True)
        if not j or j.row_version!=c.expected_version or j.lifecycle_status!="in_progress":return None
        n=j.attempt_count+1
        if c.outcome is AttemptOutcome.DELIVERED:status="delivered";available=j.available_at
        elif c.outcome is AttemptOutcome.RETRYABLE_FAILURE and n<j.max_attempts:status="retry_wait";available=c.retry_at
        else:status="dead_letter";available=j.available_at
        self.db_session.execute(text("""INSERT INTO so8_delivery_attempts(public_id,tenant_id,job_id,attempt_number,outcome,provider_code,provider_reference,error_code,attempted_at,retry_at,response_metadata) VALUES(:p,:t,:j,:n,:o,:pc,:pr,:e,:at,:retry,CAST(:m AS jsonb))"""),{"p":str(p),"t":c.tenant_id,"j":j.id,"n":n,"o":c.outcome.value,"pc":c.provider_code,"pr":c.provider_reference,"e":c.error_code,"at":c.occurred_at,"retry":c.retry_at,"m":json.dumps(c.response_metadata,sort_keys=True)})
        self.db_session.execute(text("""UPDATE so8_delivery_jobs SET lifecycle_status=:s,available_at=:avail,attempt_count=:n,worker_reference=NULL,lease_until=NULL,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v"""),{"s":status,"avail":available,"n":n,"t":c.tenant_id,"id":j.id,"v":c.expected_version})
        self._complete(c.tenant_id,c.command_key,"delivery",c.job_public_id);return self.delivery(c.tenant_id,c.job_public_id)
    def attempts(self,t,job_public_id):
        j=self._delivery_row(t,job_public_id)
        if not j:return ()
        rows=self.db_session.execute(text("SELECT * FROM so8_delivery_attempts WHERE tenant_id=:t AND job_id=:j ORDER BY attempt_number"),{"t":t,"j":j.id}).all()
        return tuple(DeliveryAttempt(UUID(str(x.public_id)),x.tenant_id,UUID(str(job_public_id)),x.attempt_number,AttemptOutcome(x.outcome),x.provider_code,x.attempted_at,x.provider_reference,x.error_code,x.retry_at,x.response_metadata) for x in rows)
    def cancel_delivery(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"cancel_delivery")
        if replay.result_public_id:return self.delivery(c.tenant_id,replay.result_public_id)
        j=self._delivery_row(c.tenant_id,c.job_public_id,True)
        if not j or j.row_version!=c.expected_version or j.lifecycle_status not in ("pending","retry_wait"):return None
        self.db_session.execute(text("UPDATE so8_delivery_jobs SET lifecycle_status='cancelled',worker_reference=NULL,lease_until=NULL,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v"),{"t":c.tenant_id,"id":j.id,"v":c.expected_version})
        self._complete(c.tenant_id,c.command_key,"delivery",c.job_public_id);return self.delivery(c.tenant_id,c.job_public_id)
    def _inbound_row(self,t,p):return self.db_session.execute(text("SELECT * FROM so8_inbound_deliveries WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _inbound(v):
        if not v:return None
        return InboundDelivery(UUID(str(v.public_id)),v.tenant_id,v.source_code,v.external_event_key,v.payload_sha256,v.payload,v.received_at,v.subject_authority,v.subject_reference)
    def receive_inbound(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"receive_inbound")
        if replay.result_public_id:return self.inbound(c.tenant_id,replay.result_public_id)
        existing=self.db_session.execute(text("SELECT * FROM so8_inbound_deliveries WHERE tenant_id=:t AND source_code=:s AND external_event_key=:e FOR UPDATE"),{"t":c.tenant_id,"s":c.source_code,"e":c.external_event_key}).first()
        if existing:
            same=(existing.payload_sha256==c.payload_sha256 and existing.payload==c.payload and existing.subject_authority==c.subject_authority and existing.subject_reference==c.subject_reference)
            if not same:raise SO8AuthorityError("SO8_EXTERNAL_EVENT_CONFLICT","conflict","The external event identity was reused with different evidence")
            self._complete(c.tenant_id,c.command_key,"inbound",existing.public_id);return self._inbound(existing)
        self.db_session.execute(text("""INSERT INTO so8_inbound_deliveries(public_id,tenant_id,source_code,external_event_key,payload_sha256,payload,subject_authority,subject_reference,received_at) VALUES(:p,:t,:s,:e,:sha,CAST(:payload AS jsonb),:sa,:sr,:at)"""),{"p":str(p),"t":c.tenant_id,"s":c.source_code,"e":c.external_event_key,"sha":c.payload_sha256,"payload":json.dumps(c.payload,sort_keys=True),"sa":c.subject_authority,"sr":c.subject_reference,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"inbound",p);return self.inbound(c.tenant_id,p)
    def inbound(self,t,p):return self._inbound(self._inbound_row(t,p))
    def list_inbound(self,t,source_code=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so8_inbound_deliveries WHERE tenant_id=:t AND (:s IS NULL OR source_code=:s) ORDER BY id"),{"t":t,"s":source_code}).all();return tuple(self.inbound(t,UUID(str(x.public_id))) for x in rows)
    def _offline_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF o" if lock else "";return self.db_session.execute(text("SELECT o.* FROM so8_offline_commands o WHERE o.tenant_id=:t AND o.public_id=:p"+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _offline(v):
        if not v:return None
        return OfflineCommand(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.device_public_id)),v.client_sequence,v.operation_code,v.target_authority,v.target_reference,v.payload,v.payload_sha256,v.captured_at,OfflineStatus(v.lifecycle_status),v.base_version,v.server_result_reference,v.resolution_code,v.resolved_at,v.row_version)
    def queue_offline(self,c,p,hp,fp,payload_sha256):
        replay=self._command(c.tenant_id,c.command_key,fp,"queue_offline")
        if replay.result_public_id:return self.offline(c.tenant_id,replay.result_public_id)
        existing=self.db_session.execute(text("SELECT * FROM so8_offline_commands WHERE tenant_id=:t AND device_public_id=:d AND client_sequence=:s FOR UPDATE"),{"t":c.tenant_id,"d":str(c.device_public_id),"s":c.client_sequence}).first()
        if existing:
            same=(existing.operation_code==c.operation_code and existing.target_authority==c.target_authority and existing.target_reference==c.target_reference and existing.payload_sha256==payload_sha256 and existing.payload==c.payload and existing.base_version==c.base_version)
            if not same:raise SO8AuthorityError("SO8_OFFLINE_SEQUENCE_CONFLICT","conflict","The device sequence was reused with different command content")
            self._complete(c.tenant_id,c.command_key,"offline",existing.public_id);return self._offline(existing)
        row=self.db_session.execute(text("""INSERT INTO so8_offline_commands(public_id,tenant_id,device_public_id,client_sequence,operation_code,target_authority,target_reference,payload,payload_sha256,base_version,captured_at,lifecycle_status) VALUES(:p,:t,:d,:s,:o,:ta,:tr,CAST(:payload AS jsonb),:sha,:b,:at,'queued') RETURNING id"""),{"p":str(p),"t":c.tenant_id,"d":str(c.device_public_id),"s":c.client_sequence,"o":c.operation_code,"ta":c.target_authority,"tr":c.target_reference,"payload":json.dumps(c.payload,sort_keys=True),"sha":payload_sha256,"b":c.base_version,"at":c.captured_at}).one()
        self.db_session.execute(text("INSERT INTO so8_offline_history(public_id,tenant_id,offline_command_id,from_status,to_status,reason_code,occurred_at) VALUES(:p,:t,:o,NULL,'queued','captured',:at)"),{"p":str(hp),"t":c.tenant_id,"o":row.id,"at":c.captured_at})
        self._complete(c.tenant_id,c.command_key,"offline",p);return self.offline(c.tenant_id,p)
    def offline(self,t,p):return self._offline(self._offline_row(t,p))
    def list_offline(self,t,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so8_offline_commands WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY device_public_id,client_sequence"),{"t":t,"s":getattr(status,"value",status)}).all();return tuple(self.offline(t,UUID(str(x.public_id))) for x in rows)
    def resolve_offline(self,c,hp,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"resolve_offline")
        if replay.result_public_id:return self.offline(c.tenant_id,replay.result_public_id)
        o=self._offline_row(c.tenant_id,c.offline_command_public_id,True)
        if not o or o.row_version!=c.expected_version or o.lifecycle_status!="queued":return None
        self.db_session.execute(text("""UPDATE so8_offline_commands SET lifecycle_status=:s,server_result_reference=:r,resolution_code=:code,resolved_at=:at,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v"""),{"s":c.to_status.value,"r":c.server_result_reference,"code":c.reason_code,"at":c.occurred_at,"t":c.tenant_id,"id":o.id,"v":c.expected_version})
        self.db_session.execute(text("""INSERT INTO so8_offline_history(public_id,tenant_id,offline_command_id,from_status,to_status,reason_code,result_reference,occurred_at) VALUES(:p,:t,:o,'queued',:s,:reason,:r,:at)"""),{"p":str(hp),"t":c.tenant_id,"o":o.id,"s":c.to_status.value,"reason":c.reason_code,"r":c.server_result_reference,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"offline",c.offline_command_public_id);return self.offline(c.tenant_id,c.offline_command_public_id)
    def offline_history(self,t,p):
        o=self._offline_row(t,p)
        if not o:return ()
        rows=self.db_session.execute(text("SELECT * FROM so8_offline_history WHERE tenant_id=:t AND offline_command_id=:o ORDER BY id"),{"t":t,"o":o.id}).all()
        return tuple(OfflineHistory(UUID(str(x.public_id)),x.tenant_id,UUID(str(p)),OfflineStatus(x.from_status) if x.from_status else None,OfflineStatus(x.to_status),x.reason_code,x.occurred_at,x.result_reference) for x in rows)
