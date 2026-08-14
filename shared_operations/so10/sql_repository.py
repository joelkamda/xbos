"""SQLAlchemy repository for SO10 scheduling, reservations and service execution."""
from __future__ import annotations
import json
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO10AuthorityError

class SQLSO10Repository:
    def __init__(self,db_session):self.db_session=db_session
    def _command(self,tenant,key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so10_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).first()
        if row:
            if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO10AuthorityError("SO10_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
            return row
        return self.db_session.execute(text("INSERT INTO so10_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *"),{"t":tenant,"k":key,"f":fingerprint,"y":kind}).one()
    def _complete(self,tenant,key,result_type,public_id):
        self.db_session.execute(text("UPDATE so10_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"y":result_type,"p":str(public_id),"t":tenant,"k":key})
    def _service_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF s" if lock else ""
        return self.db_session.execute(text("""SELECT s.*,COALESCE(o.public_id,u.public_id) target_public_id FROM so10_services s LEFT JOIN so1_offers o ON s.target_type='offer' AND (o.tenant_id,o.id)=(s.tenant_id,s.offer_id) LEFT JOIN atomic_units u ON s.target_type='atomic_unit' AND (u.tenant_id,u.id)=(s.tenant_id,s.atomic_unit_id) WHERE s.tenant_id=:t AND s.public_id=:p"""+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _service(v):
        if not v:return None
        return SchedulingService(UUID(str(v.public_id)),v.tenant_id,v.service_code,v.title,SchedulableTarget(v.target_type),UUID(str(v.target_public_id)),v.calendar_code,v.calendar_version,v.default_duration_minutes,v.max_capacity,ServiceStatus(v.lifecycle_status),v.metadata,v.row_version)
    def define_service(self,c,p,fp,target_internal_id):
        replay=self._command(c.tenant_id,c.command_key,fp,"define_service")
        if replay.result_public_id:return self.service(c.tenant_id,replay.result_public_id)
        if self.db_session.execute(text("SELECT 1 FROM so10_services WHERE tenant_id=:t AND service_code=:c"),{"t":c.tenant_id,"c":c.service_code}).scalar():return None
        offer=target_internal_id if c.target_type is SchedulableTarget.OFFER else None;unit=target_internal_id if c.target_type is SchedulableTarget.ATOMIC_UNIT else None
        self.db_session.execute(text("""INSERT INTO so10_services(public_id,tenant_id,service_code,title,target_type,offer_id,atomic_unit_id,calendar_code,calendar_version,default_duration_minutes,max_capacity,metadata,lifecycle_status) VALUES(:p,:t,:c,:title,:tt,:o,:u,:cc,:cv,:d,:m,CAST(:meta AS jsonb),'active')"""),{"p":str(p),"t":c.tenant_id,"c":c.service_code,"title":c.title,"tt":c.target_type.value,"o":offer,"u":unit,"cc":c.calendar_code,"cv":c.calendar_version,"d":c.default_duration_minutes,"m":c.max_capacity,"meta":json.dumps(c.metadata,sort_keys=True)})
        self._complete(c.tenant_id,c.command_key,"service",p);return self.service(c.tenant_id,p)
    def service(self,t,p):return self._service(self._service_row(t,p))
    def list_services(self,t,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so10_services WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY service_code"),{"t":t,"s":getattr(status,"value",status)}).all();return tuple(self.service(t,UUID(str(x.public_id))) for x in rows)
    def _window_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF w" if lock else ""
        return self.db_session.execute(text("""SELECT w.*,s.public_id service_public_id,l.public_id location_public_id FROM so10_availability_windows w JOIN so10_services s ON (s.tenant_id,s.id)=(w.tenant_id,w.service_id) JOIN locations l ON (l.tenant_id,l.id)=(w.tenant_id,w.location_id) WHERE w.tenant_id=:t AND w.public_id=:p"""+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _window(v):
        if not v:return None
        return AvailabilityWindow(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.service_public_id)),UUID(str(v.location_public_id)),v.starts_at,v.ends_at,v.capacity,AvailabilityStatus(v.lifecycle_status),v.row_version)
    def define_window(self,c,p,fp,location_internal_id):
        replay=self._command(c.tenant_id,c.command_key,fp,"define_window")
        if replay.result_public_id:return self.window(c.tenant_id,replay.result_public_id)
        s=self._service_row(c.tenant_id,c.service_public_id,True)
        if not s or s.lifecycle_status!="active":return None
        overlap=self.db_session.execute(text("""SELECT 1 FROM so10_availability_windows WHERE tenant_id=:t AND service_id=:s AND location_id=:l AND lifecycle_status='active' AND starts_at<:e AND ends_at>:b LIMIT 1"""),{"t":c.tenant_id,"s":s.id,"l":location_internal_id,"b":c.starts_at,"e":c.ends_at}).scalar()
        if overlap:return None
        self.db_session.execute(text("""INSERT INTO so10_availability_windows(public_id,tenant_id,service_id,location_id,starts_at,ends_at,capacity,lifecycle_status) VALUES(:p,:t,:s,:l,:b,:e,:c,'active')"""),{"p":str(p),"t":c.tenant_id,"s":s.id,"l":location_internal_id,"b":c.starts_at,"e":c.ends_at,"c":c.capacity})
        self._complete(c.tenant_id,c.command_key,"availability_window",p);return self.window(c.tenant_id,p)
    def window(self,t,p):return self._window(self._window_row(t,p))
    def windows(self,t,service_public_id,starts_at=None,ends_at=None):
        s=self._service_row(t,service_public_id)
        if not s:return ()
        rows=self.db_session.execute(text("""SELECT public_id FROM so10_availability_windows WHERE tenant_id=:t AND service_id=:s AND (:b IS NULL OR ends_at>:b) AND (:e IS NULL OR starts_at<:e) ORDER BY starts_at,public_id"""),{"t":t,"s":s.id,"b":starts_at,"e":ends_at}).all();return tuple(self.window(t,UUID(str(x.public_id))) for x in rows)
    def _reservation_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF r" if lock else ""
        return self.db_session.execute(text("""SELECT r.*,s.public_id service_public_id,p.public_id party_public_id,rel.public_id relationship_public_id,l.public_id location_public_id FROM so10_reservations r JOIN so10_services s ON (s.tenant_id,s.id)=(r.tenant_id,r.service_id) JOIN parties p ON (p.tenant_id,p.id)=(r.tenant_id,r.party_id) JOIN so2_operational_relationships rel ON (rel.tenant_id,rel.id)=(r.tenant_id,r.relationship_id) LEFT JOIN locations l ON (l.tenant_id,l.id)=(r.tenant_id,r.location_id) WHERE r.tenant_id=:t AND r.public_id=:p"""+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _reservation(v):
        if not v:return None
        return Reservation(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.service_public_id)),UUID(str(v.party_public_id)),UUID(str(v.relationship_public_id)),v.requested_start,v.requested_end,v.capacity_units,ReservationStatus(v.lifecycle_status),v.confirmed_start,v.confirmed_end,UUID(str(v.location_public_id)) if v.location_public_id else None,v.business_date,v.source_reference,v.row_version)
    def create_reservation(self,c,p,fp,party_internal_id,relationship_internal_id):
        replay=self._command(c.tenant_id,c.command_key,fp,"create_reservation")
        if replay.result_public_id:return self.reservation(c.tenant_id,replay.result_public_id)
        s=self._service_row(c.tenant_id,c.service_public_id)
        if not s or s.lifecycle_status!="active":return None
        self.db_session.execute(text("""INSERT INTO so10_reservations(public_id,tenant_id,service_id,party_id,relationship_id,requested_start,requested_end,capacity_units,lifecycle_status,source_reference) VALUES(:p,:t,:s,:party,:rel,:b,:e,:c,'requested',:src)"""),{"p":str(p),"t":c.tenant_id,"s":s.id,"party":party_internal_id,"rel":relationship_internal_id,"b":c.requested_start,"e":c.requested_end,"c":c.capacity_units,"src":c.source_reference})
        r=self._reservation_row(c.tenant_id,p)
        self.db_session.execute(text("INSERT INTO so10_reservation_history(tenant_id,reservation_id,event_type,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:r,'created','requested','created',:at,'{}'::jsonb)"),{"t":c.tenant_id,"r":r.id,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"reservation",p);return self.reservation(c.tenant_id,p)
    def reservation(self,t,p):return self._reservation(self._reservation_row(t,p))
    def reservations(self,t,service_public_id=None,status=None):
        sid=None
        if service_public_id:
            s=self._service_row(t,service_public_id)
            if not s:return ()
            sid=s.id
        rows=self.db_session.execute(text("SELECT public_id FROM so10_reservations WHERE tenant_id=:t AND (:s IS NULL OR service_id=:s) AND (:st IS NULL OR lifecycle_status=:st) ORDER BY requested_start,public_id"),{"t":t,"s":sid,"st":getattr(status,"value",status)}).all();return tuple(self.reservation(t,UUID(str(x.public_id))) for x in rows)
    def _availability_locked(self,t,service_id,location_public_id,b,e):
        return self.db_session.execute(text("""SELECT w.*,l.public_id location_public_id FROM so10_availability_windows w JOIN locations l ON (l.tenant_id,l.id)=(w.tenant_id,w.location_id) WHERE w.tenant_id=:t AND w.service_id=:s AND l.public_id=:l AND w.lifecycle_status='active' AND w.starts_at<=:b AND w.ends_at>=:e ORDER BY w.starts_at DESC,w.id LIMIT 1 FOR UPDATE OF w"""),{"t":t,"s":service_id,"l":str(location_public_id),"b":b,"e":e}).first()
    def _reserved_capacity(self,t,window_id,b,e,exclude_reservation_id=None):
        return int(self.db_session.execute(text("""SELECT COALESCE(sum(capacity_units),0) FROM so10_reservations WHERE tenant_id=:t AND availability_window_id=:w AND lifecycle_status='confirmed' AND confirmed_start<:e AND confirmed_end>:b AND (:x IS NULL OR id<>:x)"""),{"t":t,"w":window_id,"b":b,"e":e,"x":exclude_reservation_id}).scalar_one())
    def availability(self,t,service_public_id,location_public_id,b,e):
        s=self._service_row(t,service_public_id)
        if not s:return None
        w=self.db_session.execute(text("""SELECT w.*,l.public_id location_public_id FROM so10_availability_windows w JOIN locations l ON (l.tenant_id,l.id)=(w.tenant_id,w.location_id) WHERE w.tenant_id=:t AND w.service_id=:s AND l.public_id=:l AND w.lifecycle_status='active' AND w.starts_at<=:b AND w.ends_at>=:e ORDER BY w.starts_at DESC,w.id LIMIT 1"""),{"t":t,"s":s.id,"l":str(location_public_id),"b":b,"e":e}).first()
        if not w:return None
        reserved=self._reserved_capacity(t,w.id,b,e)
        return AvailabilityResult(UUID(str(service_public_id)),UUID(str(location_public_id)),b,e,UUID(str(w.public_id)),w.capacity,reserved,max(0,w.capacity-reserved))
    def _lock_resources_and_check(self,t,reservation_id,b,e,resource_ids):
        for public_id,units,expected_internal_id in sorted(resource_ids,key=lambda x:str(x[0])):
            row=self.db_session.execute(text("SELECT r.* FROM so5_resources r WHERE r.tenant_id=:t AND r.public_id=:p FOR UPDATE OF r"),{"t":t,"p":str(public_id)}).first()
            if not row or row.lifecycle_status!="active" or (expected_internal_id is not None and row.id!=expected_internal_id):return False
            used=int(self.db_session.execute(text("""SELECT COALESCE(sum(a.capacity_units),0) FROM so10_resource_allocations a JOIN so10_reservations x ON (x.tenant_id,x.id)=(a.tenant_id,a.reservation_id) WHERE a.tenant_id=:t AND a.resource_id=:r AND a.allocation_version=x.row_version AND x.lifecycle_status='confirmed' AND a.starts_at<:e AND a.ends_at>:b AND x.id<>:x"""),{"t":t,"r":row.id,"b":b,"e":e,"x":reservation_id}).scalar_one())
            if used+units>row.capacity:return False
        return True
    def _insert_allocations(self,t,reservation_id,new_version,b,e,resource_ids):
        for public_id,units,internal_id in resource_ids:
            rid=internal_id
            if rid is None:rid=self.db_session.execute(text("SELECT id FROM so5_resources WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(public_id)}).scalar_one()
            self.db_session.execute(text("INSERT INTO so10_resource_allocations(tenant_id,reservation_id,resource_id,allocation_version,starts_at,ends_at,capacity_units) VALUES(:t,:r,:res,:v,:b,:e,:u)"),{"t":t,"r":reservation_id,"res":rid,"v":new_version,"b":b,"e":e,"u":units})
    def _schedule(self,c,fp,business_date,resource_ids,kind):
        replay=self._command(c.tenant_id,c.command_key,fp,kind)
        if replay.result_public_id:return self.reservation(c.tenant_id,replay.result_public_id)
        r=self._reservation_row(c.tenant_id,c.reservation_public_id,True)
        valid={"requested","confirmed"} if kind=="confirm" else {"confirmed"}
        if not r or r.row_version!=c.expected_version or r.lifecycle_status not in valid:return None
        # Lock only the explicitly selected canonical availability row, not joined metadata.
        w=self.db_session.execute(text("""SELECT w.*,l.public_id location_public_id FROM so10_availability_windows w JOIN locations l ON (l.tenant_id,l.id)=(w.tenant_id,w.location_id) WHERE w.tenant_id=:t AND w.service_id=:s AND l.public_id=:l AND w.lifecycle_status='active' AND w.starts_at<=:b AND w.ends_at>=:e ORDER BY w.starts_at DESC,w.id LIMIT 1 FOR UPDATE OF w"""),{"t":c.tenant_id,"s":r.service_id,"l":str(c.location_public_id),"b":c.confirmed_start,"e":c.confirmed_end}).first()
        if not w:return None
        location_public_id=UUID(str(w.location_public_id))
        reserved=self._reserved_capacity(c.tenant_id,w.id,c.confirmed_start,c.confirmed_end,r.id)
        if reserved+r.capacity_units>w.capacity:return None
        if not self._lock_resources_and_check(c.tenant_id,r.id,c.confirmed_start,c.confirmed_end,resource_ids):return None
        new_version=r.row_version+1
        old_payload={"confirmed_start":r.confirmed_start.isoformat() if r.confirmed_start else None,"confirmed_end":r.confirmed_end.isoformat() if r.confirmed_end else None,"location_public_id":str(r.location_public_id) if getattr(r,"location_public_id",None) else None}
        updated=self.db_session.execute(text("""UPDATE so10_reservations SET lifecycle_status='confirmed',confirmed_start=:b,confirmed_end=:e,availability_window_id=:w,location_id=:l,business_date=:bd,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v RETURNING id"""),{"b":c.confirmed_start,"e":c.confirmed_end,"w":w.id,"l":w.location_id,"bd":business_date,"t":c.tenant_id,"id":r.id,"v":c.expected_version}).first()
        if not updated:return None
        self._insert_allocations(c.tenant_id,r.id,new_version,c.confirmed_start,c.confirmed_end,resource_ids)
        reason="confirmed" if kind=="confirm" else c.reason_code
        payload={"old":old_payload,"new":{"confirmed_start":c.confirmed_start.isoformat(),"confirmed_end":c.confirmed_end.isoformat(),"location_public_id":str(location_public_id),"resource_allocations":[{"resource_public_id":str(x[0]),"capacity_units":x[1]} for x in resource_ids]}}
        self.db_session.execute(text("INSERT INTO so10_reservation_history(tenant_id,reservation_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:r,:ev,:f,'confirmed',:reason,:at,CAST(:payload AS jsonb))"),{"t":c.tenant_id,"r":r.id,"ev":"confirmed" if kind=="confirm" else "rescheduled","f":r.lifecycle_status,"reason":reason,"at":c.occurred_at,"payload":json.dumps(payload,sort_keys=True)})
        self._complete(c.tenant_id,c.command_key,"reservation",c.reservation_public_id);return self.reservation(c.tenant_id,c.reservation_public_id)
    def confirm(self,c,fp,business_date,resource_ids):return self._schedule(c,fp,business_date,resource_ids,"confirm")
    def reschedule(self,c,fp,business_date,resource_ids):return self._schedule(c,fp,business_date,resource_ids,"reschedule")
    def _terminal(self,c,fp,kind,target_status):
        replay=self._command(c.tenant_id,c.command_key,fp,kind)
        if replay.result_public_id:return self.reservation(c.tenant_id,replay.result_public_id)
        r=self._reservation_row(c.tenant_id,c.reservation_public_id,True)
        allowed={"requested","confirmed"} if target_status=="cancelled" else {"confirmed"}
        if not r or r.row_version!=c.expected_version or r.lifecycle_status not in allowed:return None
        if target_status=="no_show" and r.confirmed_start and c.occurred_at<r.confirmed_start:return None
        if self.db_session.execute(text("SELECT 1 FROM so10_service_executions WHERE tenant_id=:t AND reservation_id=:r AND lifecycle_status='in_progress'"),{"t":c.tenant_id,"r":r.id}).scalar():return None
        self.db_session.execute(text("UPDATE so10_reservations SET lifecycle_status=:s,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v"),{"s":target_status,"t":c.tenant_id,"id":r.id,"v":c.expected_version})
        self.db_session.execute(text("INSERT INTO so10_reservation_history(tenant_id,reservation_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:r,:e,:f,:to,:reason,:at,'{}'::jsonb)"),{"t":c.tenant_id,"r":r.id,"e":target_status,"f":r.lifecycle_status,"to":target_status,"reason":c.reason_code,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"reservation",c.reservation_public_id);return self.reservation(c.tenant_id,c.reservation_public_id)
    def cancel(self,c,fp):return self._terminal(c,fp,"cancel","cancelled")
    def no_show(self,c,fp):return self._terminal(c,fp,"no_show","no_show")
    def allocations(self,t,reservation_public_id,current_only=True):
        r=self._reservation_row(t,reservation_public_id)
        if not r:return ()
        where=" AND a.allocation_version=:v" if current_only else ""
        params={"t":t,"r":r.id,"v":r.row_version}
        rows=self.db_session.execute(text("""SELECT a.*,res.public_id resource_public_id FROM so10_resource_allocations a JOIN so5_resources res ON (res.tenant_id,res.id)=(a.tenant_id,a.resource_id) WHERE a.tenant_id=:t AND a.reservation_id=:r"""+where+" ORDER BY a.allocation_version,a.id"),params).all()
        return tuple(ResourceAllocation(x.tenant_id,UUID(str(reservation_public_id)),UUID(str(x.resource_public_id)),x.allocation_version,x.starts_at,x.ends_at,x.capacity_units) for x in rows)
    def history(self,t,reservation_public_id):
        r=self._reservation_row(t,reservation_public_id)
        if not r:return ()
        return tuple(self.db_session.execute(text("SELECT event_type,from_status,to_status,reason_code,occurred_at,event_payload FROM so10_reservation_history WHERE tenant_id=:t AND reservation_id=:r ORDER BY sequence"),{"t":t,"r":r.id}).mappings().all())
    def _execution_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF e" if lock else ""
        return self.db_session.execute(text("""SELECT e.*,r.public_id reservation_public_id FROM so10_service_executions e JOIN so10_reservations r ON (r.tenant_id,r.id)=(e.tenant_id,e.reservation_id) WHERE e.tenant_id=:t AND e.public_id=:p"""+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _execution(v):
        if not v:return None
        return ServiceExecution(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.reservation_public_id)),ExecutionStatus(v.lifecycle_status),v.started_at,v.completed_at,v.result_code,v.evidence_reference,v.row_version)
    def start_service(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"start_service")
        if replay.result_public_id:return self.execution(c.tenant_id,replay.result_public_id)
        r=self._reservation_row(c.tenant_id,c.reservation_public_id,True)
        if not r or r.row_version!=c.expected_reservation_version or r.lifecycle_status!="confirmed":return None
        if self.db_session.execute(text("SELECT 1 FROM so10_service_executions WHERE tenant_id=:t AND reservation_id=:r"),{"t":c.tenant_id,"r":r.id}).scalar():return None
        self.db_session.execute(text("INSERT INTO so10_service_executions(public_id,tenant_id,reservation_id,lifecycle_status,started_at) VALUES(:p,:t,:r,'in_progress',:at)"),{"p":str(p),"t":c.tenant_id,"r":r.id,"at":c.occurred_at})
        e=self._execution_row(c.tenant_id,p)
        self.db_session.execute(text("INSERT INTO so10_execution_history(tenant_id,execution_id,event_type,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:e,'started','in_progress','started',:at,'{}'::jsonb)"),{"t":c.tenant_id,"e":e.id,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"service_execution",p);return self.execution(c.tenant_id,p)
    def complete_service(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"complete_service")
        if replay.result_public_id:return self.execution(c.tenant_id,replay.result_public_id)
        e=self._execution_row(c.tenant_id,c.execution_public_id,True)
        if not e or e.row_version!=c.expected_version or e.lifecycle_status!="in_progress" or c.occurred_at<e.started_at:return None
        r=self._reservation_row(c.tenant_id,e.reservation_public_id,True)
        if not r or r.lifecycle_status!="confirmed":return None
        self.db_session.execute(text("UPDATE so10_service_executions SET lifecycle_status='completed',completed_at=:at,result_code=:rc,evidence_reference=:ev,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v"),{"at":c.occurred_at,"rc":c.result_code,"ev":c.evidence_reference,"t":c.tenant_id,"id":e.id,"v":c.expected_version})
        self.db_session.execute(text("UPDATE so10_reservations SET lifecycle_status='completed',row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id"),{"t":c.tenant_id,"id":r.id})
        self.db_session.execute(text("INSERT INTO so10_execution_history(tenant_id,execution_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:e,'completed','in_progress','completed',:reason,:at,CAST(:payload AS jsonb))"),{"t":c.tenant_id,"e":e.id,"reason":c.result_code,"at":c.occurred_at,"payload":json.dumps({"evidence_reference":c.evidence_reference},sort_keys=True)})
        self.db_session.execute(text("INSERT INTO so10_reservation_history(tenant_id,reservation_id,event_type,from_status,to_status,reason_code,occurred_at,event_payload) VALUES(:t,:r,'service_completed','confirmed','completed',:reason,:at,'{}'::jsonb)"),{"t":c.tenant_id,"r":r.id,"reason":c.result_code,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"service_execution",c.execution_public_id);return self.execution(c.tenant_id,c.execution_public_id)
    def execution(self,t,p):return self._execution(self._execution_row(t,p))
    def executions(self,t,reservation_public_id):
        r=self._reservation_row(t,reservation_public_id)
        if not r:return ()
        rows=self.db_session.execute(text("SELECT public_id FROM so10_service_executions WHERE tenant_id=:t AND reservation_id=:r ORDER BY id"),{"t":t,"r":r.id}).all();return tuple(self.execution(t,UUID(str(x.public_id))) for x in rows)
