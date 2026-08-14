"""SO10 neutral scheduling, reservation, capacity and service-execution authority."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from datetime import datetime,timezone,timedelta
from typing import Callable,Protocol
from uuid import UUID,uuid4
from core.platform.operating_context.service import BusinessTimeResolver,OperatingContextError
from .contracts import *

class SO10AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable
        super().__init__(code)

class SO10Repository(Protocol):
    def define_service(self,command,public_id,fingerprint,target_internal_id)->SchedulingService|None: ...
    def service(self,tenant_id,public_id)->SchedulingService|None: ...
    def list_services(self,tenant_id,status=None): ...
    def define_window(self,command,public_id,fingerprint,location_internal_id)->AvailabilityWindow|None: ...
    def window(self,tenant_id,public_id)->AvailabilityWindow|None: ...
    def windows(self,tenant_id,service_public_id,starts_at=None,ends_at=None): ...
    def create_reservation(self,command,public_id,fingerprint,party_internal_id,relationship_internal_id)->Reservation|None: ...
    def reservation(self,tenant_id,public_id)->Reservation|None: ...
    def reservations(self,tenant_id,service_public_id=None,status=None): ...
    def availability(self,tenant_id,service_public_id,location_public_id,starts_at,ends_at)->AvailabilityResult|None: ...
    def confirm(self,command,fingerprint,business_date,resource_ids)->Reservation|None: ...
    def reschedule(self,command,fingerprint,business_date,resource_ids)->Reservation|None: ...
    def cancel(self,command,fingerprint)->Reservation|None: ...
    def no_show(self,command,fingerprint)->Reservation|None: ...
    def allocations(self,tenant_id,reservation_public_id,current_only=True): ...
    def history(self,tenant_id,reservation_public_id): ...
    def start_service(self,command,public_id,fingerprint)->ServiceExecution|None: ...
    def complete_service(self,command,fingerprint)->ServiceExecution|None: ...
    def execution(self,tenant_id,public_id)->ServiceExecution|None: ...
    def executions(self,tenant_id,reservation_public_id): ...

class SO10Authority:
    def __init__(self,repository:SO10Repository,*,authorize:Callable,atomic_unit_resolver:Callable,offer_resolver:Callable,
                 calendar_resolver:Callable,party_resolver:Callable,relationship_resolver:Callable,resource_resolver:Callable,
                 location_resolver:Callable,public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository;self.authorize=authorize;self.atomic_unit_resolver=atomic_unit_resolver;self.offer_resolver=offer_resolver
        self.calendar_resolver=calendar_resolver;self.party_resolver=party_resolver;self.relationship_resolver=relationship_resolver
        self.resource_resolver=resource_resolver;self.location_resolver=location_resolver;self.public_id_factory=public_id_factory
    @staticmethod
    def _fingerprint(command):return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _aware(value:datetime,field:str):
        if value.tzinfo is None or value.utcoffset() is None:raise SO10AuthorityError("SO10_INVALID_"+field.upper(),"validation_failure",field+" must be timezone-aware")
        return value.astimezone(timezone.utc)
    @staticmethod
    def _code(value:str,field:str,max_length=160):
        value=value.strip().lower()
        if not value or len(value)>max_length or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):raise SO10AuthorityError("SO10_INVALID_"+field.upper(),"validation_failure",field+" must be a bounded neutral code")
        return value
    @staticmethod
    def _text(value:str,field:str,max_length=500):
        value=value.strip()
        if not value or len(value)>max_length:raise SO10AuthorityError("SO10_INVALID_"+field.upper(),"validation_failure",field+" is required and bounded")
        return value
    @staticmethod
    def _owned(value,tenant,public_id,code):
        if value is None or getattr(value,"tenant_id",None)!=tenant or UUID(str(getattr(value,"public_id",UUID(int=0))))!=public_id:raise SO10AuthorityError(code,"scope_mismatch","The referenced authority was not found in this tenant")
        return value
    def _permit(self,tenant,permission):
        if not self.authorize(tenant,permission,"tenant",tenant):raise SO10AuthorityError("SO10_PERMISSION_DENIED","permission_denied","The scheduling operation is not permitted")
    def _service_calendar(self,service:SchedulingService):
        calendar=self.calendar_resolver(service.tenant_id,service.calendar_code,service.calendar_version)
        if calendar is None or getattr(calendar,"tenant_id",None)!=service.tenant_id:raise SO10AuthorityError("SO10_CALENDAR_NOT_FOUND","scope_mismatch","The PC4 business calendar was not found in this tenant")
        return calendar
    def _period(self,start,end):
        start=self._aware(start,"starts_at");end=self._aware(end,"ends_at")
        if end<=start:raise SO10AuthorityError("SO10_INVALID_PERIOD","validation_failure","The scheduling end must be after the start")
        return start,end
    def _business_date(self,service,start,end):
        calendar=self._service_calendar(service)
        try:
            left=BusinessTimeResolver.resolve(calendar,start);right=BusinessTimeResolver.resolve(calendar,end-timedelta(microseconds=1))
        except OperatingContextError as exc:raise SO10AuthorityError("SO10_BUSINESS_TIME_INVALID","validation_failure","The requested time is outside the effective PC4 business calendar") from exc
        if not left.is_open or not right.is_open:raise SO10AuthorityError("SO10_BUSINESS_TIME_CLOSED","invalid_state_transition","The requested time is on a closed business date")
        if left.business_date!=right.business_date:raise SO10AuthorityError("SO10_CROSSES_BUSINESS_DATE","validation_failure","One reservation must resolve to one PC4 business date")
        return left.business_date
    def define_service(self,command:DefineSchedulingService):
        self._permit(command.tenant_id,"scheduling.service.define")
        code=self._code(command.service_code,"service_code");title=self._text(command.title,"title",240)
        if command.default_duration_minutes<1 or command.default_duration_minutes>10080:raise SO10AuthorityError("SO10_INVALID_DURATION","validation_failure","Default duration must be between one minute and seven days")
        if command.max_capacity<1:raise SO10AuthorityError("SO10_INVALID_CAPACITY","validation_failure","Service capacity must be positive")
        resolver=self.atomic_unit_resolver if command.target_type is SchedulableTarget.ATOMIC_UNIT else self.offer_resolver
        target=self._owned(resolver(command.tenant_id,command.target_public_id),command.tenant_id,command.target_public_id,"SO10_TARGET_NOT_FOUND")
        calendar=self.calendar_resolver(command.tenant_id,self._code(command.calendar_code,"calendar_code"),command.calendar_version)
        if calendar is None or getattr(calendar,"tenant_id",None)!=command.tenant_id:raise SO10AuthorityError("SO10_CALENDAR_NOT_FOUND","scope_mismatch","The PC4 business calendar was not found in this tenant")
        if not isinstance(command.metadata,dict):raise SO10AuthorityError("SO10_INVALID_METADATA","validation_failure","metadata must be an object")
        normalized=replace(command,service_code=code,title=title,calendar_code=self._code(command.calendar_code,"calendar_code"))
        internal=getattr(target,"id",None)
        return self.repository.define_service(normalized,self.public_id_factory(),self._fingerprint(normalized),internal)
    def service(self,tenant_id,public_id):
        self._permit(tenant_id,"scheduling.read");value=self.repository.service(tenant_id,public_id)
        if value is None:raise SO10AuthorityError("SO10_SERVICE_NOT_FOUND","not_found","The scheduling service was not found")
        return value
    def list_services(self,tenant_id,status=None):self._permit(tenant_id,"scheduling.read");return self.repository.list_services(tenant_id,status)
    def define_window(self,command:DefineAvailabilityWindow):
        self._permit(command.tenant_id,"scheduling.availability.define")
        service=self.repository.service(command.tenant_id,command.service_public_id)
        if service is None or service.status is not ServiceStatus.ACTIVE:raise SO10AuthorityError("SO10_SERVICE_NOT_ACTIVE","invalid_state_transition","Availability requires an active scheduling service")
        self._owned(self.location_resolver(command.tenant_id,command.location_public_id),command.tenant_id,command.location_public_id,"SO10_LOCATION_NOT_FOUND")
        start,end=self._period(command.starts_at,command.ends_at);self._business_date(service,start,end)
        if command.capacity<1 or command.capacity>service.max_capacity:raise SO10AuthorityError("SO10_INVALID_WINDOW_CAPACITY","validation_failure","Window capacity must fit the scheduling service capacity")
        normalized=replace(command,starts_at=start,ends_at=end,occurred_at=self._aware(command.occurred_at,"occurred_at"))
        location=self.location_resolver(command.tenant_id,command.location_public_id)
        result=self.repository.define_window(normalized,self.public_id_factory(),self._fingerprint(normalized),getattr(location,"id",None))
        if result is None:raise SO10AuthorityError("SO10_AVAILABILITY_CONFLICT","conflict","The availability window overlaps an existing active window")
        return result
    def windows(self,tenant_id,service_public_id,starts_at=None,ends_at=None):
        self._permit(tenant_id,"scheduling.read")
        return self.repository.windows(tenant_id,service_public_id,self._aware(starts_at,"starts_at") if starts_at else None,self._aware(ends_at,"ends_at") if ends_at else None)
    def create_reservation(self,command:CreateReservation):
        self._permit(command.tenant_id,"scheduling.reservation.create")
        service=self.repository.service(command.tenant_id,command.service_public_id)
        if service is None or service.status is not ServiceStatus.ACTIVE:raise SO10AuthorityError("SO10_SERVICE_NOT_ACTIVE","invalid_state_transition","Reservations require an active scheduling service")
        party=self._owned(self.party_resolver(command.tenant_id,command.party_public_id),command.tenant_id,command.party_public_id,"SO10_PARTY_NOT_FOUND")
        relationship=self._owned(self.relationship_resolver(command.tenant_id,command.relationship_public_id),command.tenant_id,command.relationship_public_id,"SO10_RELATIONSHIP_NOT_FOUND")
        linked=getattr(relationship,"party_public_id",None)
        if linked is not None and UUID(str(linked))!=command.party_public_id:raise SO10AuthorityError("SO10_RELATIONSHIP_PARTY_MISMATCH","scope_mismatch","The SO2 relationship does not belong to the requested Party")
        status=getattr(relationship,"status",None)
        if status is not None and getattr(status,"value",status)!="active":raise SO10AuthorityError("SO10_RELATIONSHIP_NOT_ACTIVE","invalid_state_transition","Reservations require an active SO2 relationship")
        if command.capacity_units<1 or command.capacity_units>service.max_capacity:raise SO10AuthorityError("SO10_INVALID_CAPACITY","validation_failure","Reservation capacity must fit the service")
        start,end=self._period(command.requested_start,command.requested_end);self._business_date(service,start,end)
        source=command.source_reference.strip() if command.source_reference else None
        normalized=replace(command,requested_start=start,requested_end=end,occurred_at=self._aware(command.occurred_at,"occurred_at"),source_reference=source)
        result=self.repository.create_reservation(normalized,self.public_id_factory(),self._fingerprint(normalized),getattr(party,"id",None),getattr(relationship,"id",None))
        if result is None:raise SO10AuthorityError("SO10_RESERVATION_CONFLICT","conflict","The reservation could not be created")
        return result
    def reservation(self,tenant_id,public_id):
        self._permit(tenant_id,"scheduling.read");r=self.repository.reservation(tenant_id,public_id)
        if r is None:raise SO10AuthorityError("SO10_RESERVATION_NOT_FOUND","not_found","The reservation was not found")
        return r
    def reservations(self,tenant_id,service_public_id=None,status=None):self._permit(tenant_id,"scheduling.read");return self.repository.reservations(tenant_id,service_public_id,status)
    def availability(self,tenant_id,service_public_id,location_public_id,starts_at,ends_at):
        self._permit(tenant_id,"scheduling.read");start,end=self._period(starts_at,ends_at)
        service=self.repository.service(tenant_id,service_public_id)
        if service is None:raise SO10AuthorityError("SO10_SERVICE_NOT_FOUND","not_found","The scheduling service was not found")
        self._business_date(service,start,end)
        result=self.repository.availability(tenant_id,service_public_id,location_public_id,start,end)
        if result is None:raise SO10AuthorityError("SO10_NO_AVAILABILITY_WINDOW","not_found","No active availability window covers the requested period")
        return result
    def _allocations(self,tenant,requests):
        seen=set();resolved=[]
        for item in sorted(requests,key=lambda x:str(x.resource_public_id)):
            if item.resource_public_id in seen:raise SO10AuthorityError("SO10_DUPLICATE_RESOURCE","validation_failure","A resource may appear only once in one reservation command")
            seen.add(item.resource_public_id)
            if item.capacity_units<1:raise SO10AuthorityError("SO10_INVALID_RESOURCE_CAPACITY","validation_failure","Resource capacity units must be positive")
            resource=self._owned(self.resource_resolver(tenant,item.resource_public_id),tenant,item.resource_public_id,"SO10_RESOURCE_NOT_FOUND")
            status=getattr(resource,"status",None)
            if status is not None and getattr(status,"value",status)!="active":raise SO10AuthorityError("SO10_RESOURCE_NOT_ACTIVE","invalid_state_transition","Only active SO5 resources can be booked")
            if item.capacity_units>getattr(resource,"capacity",0):raise SO10AuthorityError("SO10_RESOURCE_CAPACITY_EXCEEDED","validation_failure","Requested units exceed SO5 resource capacity")
            resolved.append((item,getattr(resource,"id",None)))
        return tuple(resolved)
    def _schedule_change(self,command,operation):
        service_reservation=self.repository.reservation(command.tenant_id,command.reservation_public_id)
        if service_reservation is None:raise SO10AuthorityError("SO10_RESERVATION_NOT_FOUND","not_found","The reservation was not found")
        if service_reservation.status not in ({ReservationStatus.REQUESTED,ReservationStatus.CONFIRMED} if operation=="confirm" else {ReservationStatus.CONFIRMED}):raise SO10AuthorityError("SO10_INVALID_RESERVATION_STATE","invalid_state_transition","The reservation state does not allow this scheduling change")
        service=self.repository.service(command.tenant_id,service_reservation.service_public_id)
        self._owned(self.location_resolver(command.tenant_id,command.location_public_id),command.tenant_id,command.location_public_id,"SO10_LOCATION_NOT_FOUND")
        start,end=self._period(command.confirmed_start,command.confirmed_end);business_date=self._business_date(service,start,end)
        resolved=self._allocations(command.tenant_id,command.resource_allocations)
        normalized=replace(command,confirmed_start=start,confirmed_end=end,occurred_at=self._aware(command.occurred_at,"occurred_at"))
        if operation=="reschedule":normalized=replace(normalized,reason_code=self._code(command.reason_code,"reason_code"))
        fn=self.repository.confirm if operation=="confirm" else self.repository.reschedule
        result=fn(normalized,self._fingerprint(normalized),business_date,tuple((x.resource_public_id,x.capacity_units,internal) for x,internal in resolved))
        if result is None:raise SO10AuthorityError("SO10_CAPACITY_CONFLICT","conflict","The requested time or resource capacity is no longer available",retryable=True)
        return result
    def confirm(self,command:ConfirmReservation):
        self._permit(command.tenant_id,"scheduling.reservation.confirm");return self._schedule_change(command,"confirm")
    def reschedule(self,command:RescheduleReservation):
        self._permit(command.tenant_id,"scheduling.reservation.reschedule");return self._schedule_change(command,"reschedule")
    def cancel(self,command:CancelReservation):
        self._permit(command.tenant_id,"scheduling.reservation.cancel")
        normalized=replace(command,occurred_at=self._aware(command.occurred_at,"occurred_at"),reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.cancel(normalized,self._fingerprint(normalized))
        if result is None:raise SO10AuthorityError("SO10_RESERVATION_STATE_CONFLICT","stale_version","The reservation changed or can no longer be cancelled",retryable=True)
        return result
    def no_show(self,command:MarkNoShow):
        self._permit(command.tenant_id,"scheduling.reservation.no_show")
        normalized=replace(command,occurred_at=self._aware(command.occurred_at,"occurred_at"),reason_code=self._code(command.reason_code,"reason_code"))
        result=self.repository.no_show(normalized,self._fingerprint(normalized))
        if result is None:raise SO10AuthorityError("SO10_RESERVATION_STATE_CONFLICT","stale_version","The reservation changed or is not eligible for no-show",retryable=True)
        return result
    def allocations(self,tenant_id,reservation_public_id,current_only=True):self._permit(tenant_id,"scheduling.read");return self.repository.allocations(tenant_id,reservation_public_id,current_only)
    def history(self,tenant_id,reservation_public_id):self._permit(tenant_id,"scheduling.read");return self.repository.history(tenant_id,reservation_public_id)
    def start_service(self,command:StartService):
        self._permit(command.tenant_id,"scheduling.service_execution.start")
        normalized=replace(command,occurred_at=self._aware(command.occurred_at,"occurred_at"))
        result=self.repository.start_service(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO10AuthorityError("SO10_SERVICE_EXECUTION_CONFLICT","invalid_state_transition","The reservation is not eligible to start service")
        return result
    def complete_service(self,command:CompleteService):
        self._permit(command.tenant_id,"scheduling.service_execution.complete")
        evidence=command.evidence_reference.strip() if command.evidence_reference else None
        normalized=replace(command,occurred_at=self._aware(command.occurred_at,"occurred_at"),result_code=self._code(command.result_code,"result_code"),evidence_reference=evidence)
        result=self.repository.complete_service(normalized,self._fingerprint(normalized))
        if result is None:raise SO10AuthorityError("SO10_SERVICE_EXECUTION_CONFLICT","stale_version","The service execution changed or is no longer completable",retryable=True)
        return result
    def execution(self,tenant_id,public_id):self._permit(tenant_id,"scheduling.read");return self.repository.execution(tenant_id,public_id)
    def executions(self,tenant_id,reservation_public_id):self._permit(tenant_id,"scheduling.read");return self.repository.executions(tenant_id,reservation_public_id)
