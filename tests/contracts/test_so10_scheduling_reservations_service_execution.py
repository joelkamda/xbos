from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime,time,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import pytest
from core.platform.operating_context import BusinessCalendarVersion
from shared_operations.so2 import RelationshipStatus
from shared_operations.so5 import ResourceStatus
from shared_operations.so10 import *

ROOT=Path(__file__).resolve().parents[2]
NOW=datetime(2026,8,14,10,tzinfo=timezone.utc)
SERVICE=UUID(int=1001); WINDOW=UUID(int=1002); RES1=UUID(int=1003); RES2=UUID(int=1004); EXEC=UUID(int=1005)
TARGET=UUID(int=2001); PARTY=UUID(int=3001); REL=UUID(int=3002); LOC=UUID(int=4001); RESOURCE=UUID(int=5001); RESOURCE2=UUID(int=5002)

def entity(pid,tenant=1,**kw):return SimpleNamespace(id=int(pid.int%100000)+1,public_id=pid,tenant_id=tenant,**kw)
def calendar(tenant=1):
    return BusinessCalendarVersion(tenant,"operations",1,"Africa/Douala",time(0),tuple(range(7)),NOW-timedelta(days=30),None,())

class FakeRepo:
    def __init__(self):
        self.commands={};self.services={};self.windows_by_id={};self.reservations_by_id={};self.allocs=[];self.hist={};self.executions_by_id={};self.resource_caps={entity(RESOURCE).id:1,entity(RESOURCE2).id:2}
    def _cmd(self,c,fp,kind):
        old=self.commands.get((c.tenant_id,c.command_key))
        if old:
            if old[:2]!=(fp,kind):raise SO10AuthorityError("SO10_COMMAND_CONFLICT","idempotency_conflict","changed command")
            return old[2]
        self.commands[(c.tenant_id,c.command_key)]=(fp,kind,None);return None
    def _complete(self,c,fp,kind,p):self.commands[(c.tenant_id,c.command_key)]=(fp,kind,p)
    def define_service(self,c,p,fp,target_internal_id):
        old=self._cmd(c,fp,'define_service')
        if old:return self.service(c.tenant_id,old)
        if any(x.tenant_id==c.tenant_id and x.service_code==c.service_code for x in self.services.values()):return None
        s=SchedulingService(p,c.tenant_id,c.service_code,c.title,c.target_type,c.target_public_id,c.calendar_code,c.calendar_version,c.default_duration_minutes,c.max_capacity,ServiceStatus.ACTIVE,c.metadata,1);self.services[p]=s;self._complete(c,fp,'define_service',p);return s
    def service(self,t,p):
        x=self.services.get(p);return x if x and x.tenant_id==t else None
    def list_services(self,t,status=None):return tuple(x for x in self.services.values() if x.tenant_id==t and (status is None or x.status is status))
    def define_window(self,c,p,fp,location_internal_id):
        old=self._cmd(c,fp,'define_window')
        if old:return self.window(c.tenant_id,old)
        if any(x.tenant_id==c.tenant_id and x.service_public_id==c.service_public_id and x.location_public_id==c.location_public_id and x.status is AvailabilityStatus.ACTIVE and x.starts_at<c.ends_at and x.ends_at>c.starts_at for x in self.windows_by_id.values()):return None
        w=AvailabilityWindow(p,c.tenant_id,c.service_public_id,c.location_public_id,c.starts_at,c.ends_at,c.capacity,AvailabilityStatus.ACTIVE,1);self.windows_by_id[p]=w;self._complete(c,fp,'define_window',p);return w
    def window(self,t,p):
        x=self.windows_by_id.get(p);return x if x and x.tenant_id==t else None
    def windows(self,t,s,starts_at=None,ends_at=None):return tuple(x for x in self.windows_by_id.values() if x.tenant_id==t and x.service_public_id==s and (starts_at is None or x.ends_at>starts_at) and (ends_at is None or x.starts_at<ends_at))
    def create_reservation(self,c,p,fp,party_internal_id,relationship_internal_id):
        old=self._cmd(c,fp,'create_reservation')
        if old:return self.reservation(c.tenant_id,old)
        r=Reservation(p,c.tenant_id,c.service_public_id,c.party_public_id,c.relationship_public_id,c.requested_start,c.requested_end,c.capacity_units,ReservationStatus.REQUESTED,None,None,None,None,c.source_reference,1);self.reservations_by_id[p]=r;self.hist[p]=[('created','requested')];self._complete(c,fp,'create_reservation',p);return r
    def reservation(self,t,p):
        x=self.reservations_by_id.get(p);return x if x and x.tenant_id==t else None
    def reservations(self,t,service_public_id=None,status=None):return tuple(x for x in self.reservations_by_id.values() if x.tenant_id==t and (service_public_id is None or x.service_public_id==service_public_id) and (status is None or x.status is status))
    def _window_for(self,t,service,location,b,e):
        return next((x for x in self.windows_by_id.values() if x.tenant_id==t and x.service_public_id==service and x.location_public_id==location and x.status is AvailabilityStatus.ACTIVE and x.starts_at<=b and x.ends_at>=e),None)
    def _reserved(self,t,service,b,e,exclude=None):return sum(x.capacity_units for x in self.reservations_by_id.values() if x.tenant_id==t and x.service_public_id==service and x.public_id!=exclude and x.status is ReservationStatus.CONFIRMED and x.confirmed_start<e and x.confirmed_end>b)
    def availability(self,t,s,l,b,e):
        w=next((x for x in self.windows_by_id.values() if x.tenant_id==t and x.service_public_id==s and x.location_public_id==l and x.starts_at<=b and x.ends_at>=e and x.status is AvailabilityStatus.ACTIVE),None)
        if not w:return None
        reserved=self._reserved(t,s,b,e);return AvailabilityResult(s,l,b,e,w.public_id,w.capacity,reserved,max(0,w.capacity-reserved))
    def _resource_used(self,t,p,b,e,exclude):
        total=0
        for a in self.allocs:
            if a.resource_public_id!=p or a.tenant_id!=t:continue
            r=self.reservations_by_id[a.reservation_public_id]
            if r.public_id!=exclude and r.status is ReservationStatus.CONFIRMED and a.allocation_version==r.row_version and a.starts_at<e and a.ends_at>b:total+=a.capacity_units
        return total
    def _schedule(self,c,fp,business_date,resource_ids,kind):
        old=self._cmd(c,fp,kind)
        if old:return self.reservation(c.tenant_id,old)
        r=self.reservation(c.tenant_id,c.reservation_public_id)
        if not r or r.row_version!=c.expected_version:return None
        if kind=='confirm' and r.status not in {ReservationStatus.REQUESTED,ReservationStatus.CONFIRMED}:return None
        if kind=='reschedule' and r.status is not ReservationStatus.CONFIRMED:return None
        w=self._window_for(c.tenant_id,r.service_public_id,c.location_public_id,c.confirmed_start,c.confirmed_end)
        if not w or self._reserved(c.tenant_id,r.service_public_id,c.confirmed_start,c.confirmed_end,r.public_id)+r.capacity_units>w.capacity:return None
        for public_id,units,internal in resource_ids:
            if self._resource_used(c.tenant_id,public_id,c.confirmed_start,c.confirmed_end,r.public_id)+units>self.resource_caps[internal]:return None
        nv=r.row_version+1
        nr=replace(r,status=ReservationStatus.CONFIRMED,confirmed_start=c.confirmed_start,confirmed_end=c.confirmed_end,location_public_id=w.location_public_id,business_date=business_date,row_version=nv);self.reservations_by_id[r.public_id]=nr
        for public_id,units,_ in resource_ids:self.allocs.append(ResourceAllocation(c.tenant_id,r.public_id,public_id,nv,c.confirmed_start,c.confirmed_end,units))
        self.hist[r.public_id].append((kind,'confirmed'));self._complete(c,fp,kind,r.public_id);return nr
    def confirm(self,c,fp,business_date,resource_ids):return self._schedule(c,fp,business_date,resource_ids,'confirm')
    def reschedule(self,c,fp,business_date,resource_ids):return self._schedule(c,fp,business_date,resource_ids,'reschedule')
    def _terminal(self,c,fp,kind,status):
        old=self._cmd(c,fp,kind)
        if old:return self.reservation(c.tenant_id,old)
        r=self.reservation(c.tenant_id,c.reservation_public_id)
        if not r or r.row_version!=c.expected_version or (status is ReservationStatus.NO_SHOW and r.status is not ReservationStatus.CONFIRMED) or (status is ReservationStatus.CANCELLED and r.status not in {ReservationStatus.REQUESTED,ReservationStatus.CONFIRMED}):return None
        nr=replace(r,status=status,row_version=r.row_version+1);self.reservations_by_id[r.public_id]=nr;self.hist[r.public_id].append((kind,status.value));self._complete(c,fp,kind,r.public_id);return nr
    def cancel(self,c,fp):return self._terminal(c,fp,'cancel',ReservationStatus.CANCELLED)
    def no_show(self,c,fp):
        r=self.reservation(c.tenant_id,c.reservation_public_id)
        if r and r.confirmed_start and c.occurred_at<r.confirmed_start:return None
        return self._terminal(c,fp,'no_show',ReservationStatus.NO_SHOW)
    def allocations(self,t,p,current_only=True):
        r=self.reservation(t,p)
        return tuple(a for a in self.allocs if a.tenant_id==t and a.reservation_public_id==p and (not current_only or a.allocation_version==r.row_version)) if r else ()
    def history(self,t,p):return tuple(self.hist.get(p,())) if self.reservation(t,p) else ()
    def start_service(self,c,p,fp):
        old=self._cmd(c,fp,'start_service')
        if old:return self.execution(c.tenant_id,old)
        r=self.reservation(c.tenant_id,c.reservation_public_id)
        if not r or r.row_version!=c.expected_reservation_version or r.status is not ReservationStatus.CONFIRMED or any(x.reservation_public_id==r.public_id for x in self.executions_by_id.values()):return None
        e=ServiceExecution(p,c.tenant_id,r.public_id,ExecutionStatus.IN_PROGRESS,c.occurred_at,None,None,None,1);self.executions_by_id[p]=e;self._complete(c,fp,'start_service',p);return e
    def complete_service(self,c,fp):
        old=self._cmd(c,fp,'complete_service')
        if old:return self.execution(c.tenant_id,old)
        e=self.execution(c.tenant_id,c.execution_public_id)
        if not e or e.row_version!=c.expected_version or e.status is not ExecutionStatus.IN_PROGRESS:return None
        ne=replace(e,status=ExecutionStatus.COMPLETED,completed_at=c.occurred_at,result_code=c.result_code,evidence_reference=c.evidence_reference,row_version=e.row_version+1);self.executions_by_id[e.public_id]=ne
        r=self.reservations_by_id[e.reservation_public_id];self.reservations_by_id[r.public_id]=replace(r,status=ReservationStatus.COMPLETED,row_version=r.row_version+1);self.hist[r.public_id].append(('service_completed','completed'));self._complete(c,fp,'complete_service',e.public_id);return ne
    def execution(self,t,p):
        x=self.executions_by_id.get(p);return x if x and x.tenant_id==t else None
    def executions(self,t,p):return tuple(x for x in self.executions_by_id.values() if x.tenant_id==t and x.reservation_public_id==p)

def authority(ids=None,permit=True,tenant=1):
    repo=FakeRepo();ids=iter(ids or [SERVICE,WINDOW,RES1,RES2,EXEC,UUID(int=1006),UUID(int=1007)])
    parties={PARTY:entity(PARTY,tenant)}
    rels={REL:entity(REL,tenant,party_public_id=PARTY,status=RelationshipStatus.ACTIVE)}
    resources={RESOURCE:entity(RESOURCE,tenant,status=ResourceStatus.ACTIVE,capacity=1),RESOURCE2:entity(RESOURCE2,tenant,status=ResourceStatus.ACTIVE,capacity=2)}
    targets={TARGET:entity(TARGET,tenant)};locs={LOC:entity(LOC,tenant)}
    a=SO10Authority(repo,authorize=lambda *x:permit,atomic_unit_resolver=lambda t,p:targets.get(p) if t==tenant else None,offer_resolver=lambda t,p:targets.get(p) if t==tenant else None,calendar_resolver=lambda t,c,v:calendar(tenant) if t==tenant and c=='operations' and v==1 else None,party_resolver=lambda t,p:parties.get(p) if t==tenant else None,relationship_resolver=lambda t,p:rels.get(p) if t==tenant else None,resource_resolver=lambda t,p:resources.get(p) if t==tenant else None,location_resolver=lambda t,p:locs.get(p) if t==tenant else None,public_id_factory=lambda:next(ids))
    return a,repo

def setup(a,capacity=1):
    s=a.define_service(DefineSchedulingService('service',1,'consultation','Consultation',SchedulableTarget.ATOMIC_UNIT,TARGET,'operations',1,60,capacity,{}))
    w=a.define_window(DefineAvailabilityWindow('window',1,s.public_id,LOC,NOW,NOW+timedelta(hours=8),capacity,NOW))
    return s,w

def request(a,key='r1',start=None,end=None):
    start=start or NOW+timedelta(hours=1);end=end or start+timedelta(hours=1)
    return a.create_reservation(CreateReservation(key,1,SERVICE,PARTY,REL,start,end,1,NOW,'source-1'))

def test_service_availability_reservation_and_exact_replay():
    a,repo=authority();s,w=setup(a);cmd=CreateReservation('r1',1,s.public_id,PARTY,REL,NOW+timedelta(hours=1),NOW+timedelta(hours=2),1,NOW,'source-1');r=a.create_reservation(cmd)
    assert a.create_reservation(cmd)==r and len(repo.reservations_by_id)==1
    with pytest.raises(SO10AuthorityError,match='SO10_COMMAND_CONFLICT'):a.create_reservation(replace(cmd,source_reference='changed'))
    av=a.availability(1,s.public_id,LOC,NOW+timedelta(hours=1),NOW+timedelta(hours=2));assert av.available_capacity==1 and av.window_public_id==w.public_id

def test_confirm_capacity_conflict_and_resource_double_booking():
    a,repo=authority(ids=[SERVICE,WINDOW,RES1,RES2]);s,_=setup(a,2)
    r1=request(a,'r1');r2=request(a,'r2')
    c1=ConfirmReservation('c1',1,r1.public_id,r1.row_version,LOC,NOW+timedelta(hours=1),NOW+timedelta(hours=2),(ResourceAllocationRequest(RESOURCE,1),),NOW)
    r1=a.confirm(c1);assert r1.status is ReservationStatus.CONFIRMED and len(a.allocations(1,r1.public_id))==1
    c2=ConfirmReservation('c2',1,r2.public_id,r2.row_version,LOC,NOW+timedelta(hours=1,minutes=15),NOW+timedelta(hours=1,minutes=45),(ResourceAllocationRequest(RESOURCE,1),),NOW)
    with pytest.raises(SO10AuthorityError,match='SO10_CAPACITY_CONFLICT'):a.confirm(c2)
    assert a.availability(1,s.public_id,LOC,NOW+timedelta(hours=1,minutes=15),NOW+timedelta(hours=1,minutes=45)).available_capacity==1

def test_reschedule_preserves_allocation_versions_and_history():
    a,repo=authority(ids=[SERVICE,WINDOW,RES1]);setup(a,2);r=request(a);r=a.confirm(ConfirmReservation('c',1,r.public_id,1,LOC,NOW+timedelta(hours=1),NOW+timedelta(hours=2),(ResourceAllocationRequest(RESOURCE2,1),),NOW))
    old=list(a.allocations(1,r.public_id,False));r=a.reschedule(RescheduleReservation('rs',1,r.public_id,r.row_version,LOC,NOW+timedelta(hours=3),NOW+timedelta(hours=4),(ResourceAllocationRequest(RESOURCE2,1),),NOW,'client_request'))
    all_alloc=list(a.allocations(1,r.public_id,False));assert len(all_alloc)==2 and old[0].allocation_version<all_alloc[-1].allocation_version and len(a.history(1,r.public_id))==3
    with pytest.raises(SO10AuthorityError,match='SO10_COMMAND_CONFLICT'):a.reschedule(RescheduleReservation('rs',1,r.public_id,r.row_version,LOC,NOW+timedelta(hours=4),NOW+timedelta(hours=5),(),NOW,'client_request'))

def test_service_execution_is_operational_and_completes_reservation():
    a,_=authority(ids=[SERVICE,WINDOW,RES1,EXEC]);setup(a);r=request(a);r=a.confirm(ConfirmReservation('c',1,r.public_id,1,LOC,NOW+timedelta(hours=1),NOW+timedelta(hours=2),(),NOW));e=a.start_service(StartService('start',1,r.public_id,r.row_version,NOW+timedelta(hours=1)))
    e=a.complete_service(CompleteService('done',1,e.public_id,e.row_version,NOW+timedelta(hours=2),'completed_normally','doc:123'))
    assert e.status is ExecutionStatus.COMPLETED and a.reservation(1,r.public_id).status is ReservationStatus.COMPLETED and e.evidence_reference=='doc:123'

def test_pc4_time_party_resource_tenant_and_permission_fail_closed():
    a,_=authority();setup(a)
    with pytest.raises(SO10AuthorityError,match='SO10_INVALID_STARTS_AT'):a.create_reservation(CreateReservation('bad-time',1,SERVICE,PARTY,REL,datetime(2026,8,14,11),datetime(2026,8,14,12),1,NOW))
    with pytest.raises(SO10AuthorityError,match='SO10_SERVICE_NOT_ACTIVE'):a.create_reservation(CreateReservation('cross-tenant',2,SERVICE,PARTY,REL,NOW+timedelta(hours=1),NOW+timedelta(hours=2),1,NOW))
    with pytest.raises(SO10AuthorityError,match='SO10_PARTY_NOT_FOUND'):a.create_reservation(CreateReservation('bad-party',1,SERVICE,UUID(int=3999),REL,NOW+timedelta(hours=1),NOW+timedelta(hours=2),1,NOW))
    denied,_=authority(permit=False)
    with pytest.raises(SO10AuthorityError,match='SO10_PERMISSION_DENIED'):denied.define_service(DefineSchedulingService('x',1,'x','X',SchedulableTarget.ATOMIC_UNIT,TARGET,'operations',1))

def test_no_show_and_cancellation_are_explicit_terminal_states():
    a,_=authority(ids=[SERVICE,WINDOW,RES1,RES2]);setup(a,2);r1=request(a,'r1');r1=a.confirm(ConfirmReservation('c1',1,r1.public_id,1,LOC,NOW+timedelta(hours=1),NOW+timedelta(hours=2),(),NOW));
    with pytest.raises(SO10AuthorityError,match='SO10_RESERVATION_STATE_CONFLICT'):a.no_show(MarkNoShow('ns-early',1,r1.public_id,r1.row_version,NOW+timedelta(minutes=30)))
    r1=a.no_show(MarkNoShow('ns',1,r1.public_id,r1.row_version,NOW+timedelta(hours=1)));assert r1.status is ReservationStatus.NO_SHOW
    r2=request(a,'r2',NOW+timedelta(hours=3),NOW+timedelta(hours=4));r2=a.cancel(CancelReservation('cancel',1,r2.public_id,r2.row_version,NOW,'client_cancelled'));assert r2.status is ReservationStatus.CANCELLED

def test_neutral_profiles_and_finance_workflow_boundaries():
    a=json.loads((ROOT/'contracts/shared_operations/v1/so10_authority.json').read_text());p1=json.loads((ROOT/'contracts/shared_operations/v1/examples/clinical_appointment_profile.json').read_text());p2=json.loads((ROOT/'contracts/shared_operations/v1/examples/field_service_schedule_profile.json').read_text())
    assert a['time_authority']=='PC4_REUSED' and a['resource_authority']=='SO5_REUSED' and a['financial_authority']=='NEUTRAL_FINANCE_PRESERVED' and a['workflow_authority']=='SO6_EXTERNAL'
    assert p1['terminology']!=p2['terminology'] and p1['capabilities']!=p2['capabilities'] and p1['financial_truth']==p2['financial_truth']=='NONE'

def test_pc0_scheduling_authority_is_registered_and_public():
    module=json.loads((ROOT/'contracts/platform/v1/pc0_module_map.json').read_text());authority=json.loads((ROOT/'contracts/platform/v1/pc0_data_authority_register.json').read_text());interfaces=json.loads((ROOT/'contracts/platform/v1/pc0_public_private_interfaces.json').read_text())
    m=next(x for x in module['modules'] if x['code']=='scheduling');a=next(x for x in authority['authorities'] if x.get('module')=='scheduling');i=next(x for x in interfaces['interfaces'] if x['module']=='scheduling')
    assert (m['owner'],m['kind'])==('SO10','shared_operations_authority') and a['code']=='operational_scheduling_reservations' and 'shared_operations.so10.SO10Authority' in i['public']

def test_sql_serializes_booking_and_never_writes_finance_or_workflow():
    up=(ROOT/'alembic_neutral/sql/so10_scheduling_reservations_service_execution_up.sql').read_text();repo=(ROOT/'shared_operations/so10/sql_repository.py').read_text()
    for marker in ('UNIQUE(tenant_id,command_key)','so10_history_immutable','so10_resource_allocations','FOREIGN KEY(tenant_id,calendar_code,calendar_version)'):
        assert marker in up
    for marker in ('FOR UPDATE OF r','FOR UPDATE OF w','FOR UPDATE OF s','FOR UPDATE OF e','SO10_COMMAND_CONFLICT'):
        assert marker in repo
    lower=(up+'\n'+repo).lower()
    assert not any(x in lower for x in ('insert into public.financial_events','insert into public.journal_entries','insert into public.financial_obligations','insert into public.payment_settlements','update public.so6_workflows','insert into public.so8_delivery_jobs'))
