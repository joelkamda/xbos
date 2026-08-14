from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import UUID
import pytest

from shared_operations.so8 import *

ROOT=Path(__file__).resolve().parents[2]
NOW=datetime(2026,8,14,14,0,tzinfo=timezone.utc)
J=UUID(int=8001);A1=UUID(int=8002);A2=UUID(int=8003);I=UUID(int=8004);O=UUID(int=8005);H1=UUID(int=8006);H2=UUID(int=8007);DEV=UUID(int=8010);DOCV=UUID(int=8011)

class FakeRepo:
    def __init__(self):self.jobs={};self.attempt_rows={};self.inbounds={};self.offlines={};self.histories={};self.commands={}
    def _cmd(self,c,fp,kind):
        old=self.commands.get((c.tenant_id,c.command_key))
        if old and old[:2]!=(fp,kind):raise SO8AuthorityError('SO8_COMMAND_CONFLICT','idempotency_conflict','conflict')
        return old
    def _complete(self,c,fp,kind,p):self.commands[(c.tenant_id,c.command_key)]=(fp,kind,p)
    def create_delivery(self,c,p,fp,sha):
        old=self._cmd(c,fp,'create_delivery')
        if old:return self.jobs[old[2]]
        j=DeliveryJob(p,c.tenant_id,c.delivery_kind,c.channel_code,c.destination_reference,DeliveryStatus.PENDING,c.available_at,c.max_attempts,0,c.subject_authority,c.subject_reference,c.document_version_public_id,c.payload,sha,None,None,1);self.jobs[p]=j;self._complete(c,fp,'create_delivery',p);return j
    def delivery(self,t,p):
        j=self.jobs.get(p);return j if j and j.tenant_id==t else None
    def list_deliveries(self,t,status=None):return tuple(j for j in self.jobs.values() if j.tenant_id==t and (status is None or j.status==status))
    def due_deliveries(self,t,as_of,limit=50):return tuple(j for j in self.jobs.values() if j.tenant_id==t and j.status in {DeliveryStatus.PENDING,DeliveryStatus.RETRY_WAIT} and j.available_at<=as_of)[:limit]
    def claim_delivery(self,c,fp):
        old=self._cmd(c,fp,'claim_delivery')
        if old:return self.jobs[old[2]]
        j=self.delivery(c.tenant_id,c.job_public_id)
        if not j or j.row_version!=c.expected_version or j.status not in {DeliveryStatus.PENDING,DeliveryStatus.RETRY_WAIT} or j.available_at>c.occurred_at:return None
        j=replace(j,status=DeliveryStatus.IN_PROGRESS,worker_reference=c.worker_reference,lease_until=c.lease_until,row_version=j.row_version+1);self.jobs[j.public_id]=j;self._complete(c,fp,'claim_delivery',j.public_id);return j
    def record_attempt(self,c,p,fp):
        old=self._cmd(c,fp,'record_attempt')
        if old:return self.jobs[old[2]]
        j=self.delivery(c.tenant_id,c.job_public_id)
        if not j or j.row_version!=c.expected_version or j.status is not DeliveryStatus.IN_PROGRESS:return None
        n=j.attempt_count+1
        a=DeliveryAttempt(p,c.tenant_id,j.public_id,n,c.outcome,c.provider_code,c.occurred_at,c.provider_reference,c.error_code,c.retry_at,c.response_metadata);self.attempt_rows[p]=a
        if c.outcome is AttemptOutcome.DELIVERED:status=DeliveryStatus.DELIVERED;at=j.available_at
        elif c.outcome is AttemptOutcome.RETRYABLE_FAILURE and n<j.max_attempts:status=DeliveryStatus.RETRY_WAIT;at=c.retry_at
        else:status=DeliveryStatus.DEAD_LETTER;at=j.available_at
        j=replace(j,status=status,available_at=at,attempt_count=n,worker_reference=None,lease_until=None,row_version=j.row_version+1);self.jobs[j.public_id]=j;self._complete(c,fp,'record_attempt',j.public_id);return j
    def attempts(self,t,p):return tuple(sorted((a for a in self.attempt_rows.values() if a.tenant_id==t and a.job_public_id==p),key=lambda a:a.attempt_number))
    def cancel_delivery(self,c,fp):
        old=self._cmd(c,fp,'cancel_delivery')
        if old:return self.jobs[old[2]]
        j=self.delivery(c.tenant_id,c.job_public_id)
        if not j or j.row_version!=c.expected_version or j.status not in {DeliveryStatus.PENDING,DeliveryStatus.RETRY_WAIT}:return None
        j=replace(j,status=DeliveryStatus.CANCELLED,row_version=j.row_version+1);self.jobs[j.public_id]=j;self._complete(c,fp,'cancel_delivery',j.public_id);return j
    def receive_inbound(self,c,p,fp):
        old=self._cmd(c,fp,'receive_inbound')
        if old:return self.inbounds[old[2]]
        existing=next((i for i in self.inbounds.values() if i.tenant_id==c.tenant_id and i.source_code==c.source_code and i.external_event_key==c.external_event_key),None)
        if existing:
            if (existing.payload_sha256,existing.payload,existing.subject_authority,existing.subject_reference)!=(c.payload_sha256,c.payload,c.subject_authority,c.subject_reference):raise SO8AuthorityError('SO8_EXTERNAL_EVENT_CONFLICT','conflict','changed')
            self._complete(c,fp,'receive_inbound',existing.public_id);return existing
        i=InboundDelivery(p,c.tenant_id,c.source_code,c.external_event_key,c.payload_sha256,c.payload,c.occurred_at,c.subject_authority,c.subject_reference);self.inbounds[p]=i;self._complete(c,fp,'receive_inbound',p);return i
    def inbound(self,t,p):
        i=self.inbounds.get(p);return i if i and i.tenant_id==t else None
    def list_inbound(self,t,source_code=None):return tuple(i for i in self.inbounds.values() if i.tenant_id==t and (source_code is None or i.source_code==source_code))
    def queue_offline(self,c,p,hp,fp,sha):
        old=self._cmd(c,fp,'queue_offline')
        if old:return self.offlines[old[2]]
        existing=next((o for o in self.offlines.values() if o.tenant_id==c.tenant_id and o.device_public_id==c.device_public_id and o.client_sequence==c.client_sequence),None)
        if existing:
            if (existing.operation_code,existing.target_authority,existing.target_reference,existing.payload_sha256,existing.payload,existing.base_version)!=(c.operation_code,c.target_authority,c.target_reference,sha,c.payload,c.base_version):raise SO8AuthorityError('SO8_OFFLINE_SEQUENCE_CONFLICT','conflict','changed')
            self._complete(c,fp,'queue_offline',existing.public_id);return existing
        o=OfflineCommand(p,c.tenant_id,c.device_public_id,c.client_sequence,c.operation_code,c.target_authority,c.target_reference,c.payload,sha,c.captured_at,OfflineStatus.QUEUED,c.base_version,None,None,None,1);self.offlines[p]=o
        self.histories[hp]=OfflineHistory(hp,c.tenant_id,p,None,OfflineStatus.QUEUED,'captured',c.captured_at,None);self._complete(c,fp,'queue_offline',p);return o
    def offline(self,t,p):
        o=self.offlines.get(p);return o if o and o.tenant_id==t else None
    def list_offline(self,t,status=None):return tuple(o for o in self.offlines.values() if o.tenant_id==t and (status is None or o.status==status))
    def resolve_offline(self,c,hp,fp):
        old=self._cmd(c,fp,'resolve_offline')
        if old:return self.offlines[old[2]]
        o=self.offline(c.tenant_id,c.offline_command_public_id)
        if not o or o.row_version!=c.expected_version or o.status is not OfflineStatus.QUEUED:return None
        prior=o.status;o=replace(o,status=c.to_status,server_result_reference=c.server_result_reference,resolution_code=c.reason_code,resolved_at=c.occurred_at,row_version=o.row_version+1);self.offlines[o.public_id]=o
        self.histories[hp]=OfflineHistory(hp,c.tenant_id,o.public_id,prior,c.to_status,c.reason_code,c.occurred_at,c.server_result_reference);self._complete(c,fp,'resolve_offline',o.public_id);return o
    def offline_history(self,t,p):return tuple(h for h in self.histories.values() if h.tenant_id==t and h.offline_command_public_id==p)

def authority(ids=None,permit=True,tenant=1):
    repo=FakeRepo();ids=iter(ids or [J,A1,A2,I,O,H1,H2,UUID(int=8012),UUID(int=8013)])
    so8=SO8Authority(repo,authorize=lambda *x:permit,subject_resolver=lambda t,a,r:t==tenant and a in {'workflow','case'},document_version_resolver=lambda t,p:t==tenant and p==DOCV,device_resolver=lambda t,p:t==tenant and p==DEV,public_id_factory=lambda:next(ids))
    return so8,repo

def job_cmd(key='job',max_attempts=3):return CreateDeliveryJob(key,1,'notification','staff_in_app','resource:42',{'message':'ready'},NOW,max_attempts,'workflow','WF-1',DOCV)

def test_delivery_exact_replay_and_changed_command_conflict():
    so8,repo=authority();cmd=job_cmd();j=so8.create_delivery(cmd);assert so8.create_delivery(cmd)==j and len(repo.jobs)==1 and len(j.payload_sha256)==64
    with pytest.raises(SO8AuthorityError,match='SO8_COMMAND_CONFLICT'):so8.create_delivery(replace(cmd,destination_reference='resource:99'))

def test_claim_retry_then_delivery_preserves_attempt_history():
    so8,_=authority();j=so8.create_delivery(job_cmd());j=so8.claim_delivery(ClaimDeliveryJob('claim1',1,j.public_id,j.row_version,'worker:a',NOW,NOW+timedelta(minutes=5)))
    j=so8.record_attempt(RecordDeliveryAttempt('attempt1',1,j.public_id,j.row_version,AttemptOutcome.RETRYABLE_FAILURE,'adapter',NOW+timedelta(minutes=1),error_code='temporary',retry_at=NOW+timedelta(minutes=10)))
    assert j.status is DeliveryStatus.RETRY_WAIT and j.attempt_count==1 and not so8.due_deliveries(1,NOW+timedelta(minutes=5))
    j=so8.claim_delivery(ClaimDeliveryJob('claim2',1,j.public_id,j.row_version,'worker:b',NOW+timedelta(minutes=10),NOW+timedelta(minutes=15)))
    j=so8.record_attempt(RecordDeliveryAttempt('attempt2',1,j.public_id,j.row_version,AttemptOutcome.DELIVERED,'adapter',NOW+timedelta(minutes=11),provider_reference='provider:ok'))
    assert j.status is DeliveryStatus.DELIVERED and [a.outcome for a in so8.attempts(1,j.public_id)]==[AttemptOutcome.RETRYABLE_FAILURE,AttemptOutcome.DELIVERED]

def test_retry_capacity_dead_letters_and_cancel_is_bounded():
    so8,_=authority();j=so8.create_delivery(job_cmd(max_attempts=1));j=so8.claim_delivery(ClaimDeliveryJob('c',1,j.public_id,j.row_version,'w',NOW,NOW+timedelta(minutes=1)))
    j=so8.record_attempt(RecordDeliveryAttempt('a',1,j.public_id,j.row_version,AttemptOutcome.RETRYABLE_FAILURE,'adapter',NOW+timedelta(seconds=5),error_code='down',retry_at=NOW+timedelta(minutes=2)))
    assert j.status is DeliveryStatus.DEAD_LETTER
    with pytest.raises(SO8AuthorityError,match='SO8_DELIVERY_CANCEL_CONFLICT'):so8.cancel_delivery(CancelDeliveryJob('x',1,j.public_id,j.row_version,'operator',NOW))

def test_inbound_external_identity_dedupes_but_changed_evidence_conflicts():
    so8,repo=authority();c=ReceiveInboundDelivery('in1',1,'partner_webhook','evt-1','a'*64,{'value':1},NOW,'case','CASE-1');i=so8.receive_inbound(c)
    i2=so8.receive_inbound(replace(c,command_key='in2',occurred_at=NOW+timedelta(seconds=1)));assert i2==i and len(repo.inbounds)==1
    with pytest.raises(SO8AuthorityError,match='SO8_EXTERNAL_EVENT_CONFLICT'):so8.receive_inbound(replace(c,command_key='in3',payload_sha256='b'*64,payload={'value':2}))

def test_offline_queue_replay_server_resolution_and_history():
    so8,repo=authority(ids=[O,H1,H2,UUID(int=8020),UUID(int=8021),UUID(int=8022),UUID(int=8023),UUID(int=8024)]);c=QueueOfflineCommand('off1',1,DEV,7,'inspection.capture','workflow','WF-1',{'reading':42},NOW,3);o=so8.queue_offline(c);assert so8.queue_offline(c)==o and len(repo.offlines)==1
    with pytest.raises(SO8AuthorityError,match='SO8_COMMAND_CONFLICT'):so8.queue_offline(replace(c,payload={'reading':43}))
    o=so8.resolve_offline(ResolveOfflineCommand('resolve',1,o.public_id,o.row_version,OfflineStatus.APPLIED,'accepted',NOW+timedelta(minutes=1),'workflow-result:1'))
    assert o.status is OfflineStatus.APPLIED and len(so8.offline_history(1,o.public_id))==2

def test_pc5_device_so7_document_and_tenant_scope_fail_closed():
    so8,_=authority();
    with pytest.raises(SO8AuthorityError,match='SO8_DEVICE_NOT_FOUND'):so8.queue_offline(QueueOfflineCommand('bad',2,DEV,1,'capture','workflow','WF',{},NOW))
    with pytest.raises(SO8AuthorityError,match='SO8_DOCUMENT_VERSION_NOT_FOUND'):so8.create_delivery(replace(job_cmd(),document_version_public_id=UUID(int=999)))
    denied,_=authority(permit=False)
    with pytest.raises(SO8AuthorityError,match='SO8_PERMISSION_DENIED'):denied.create_delivery(job_cmd())

def test_contracts_neutrality_and_finance_boundary():
    a=json.loads((ROOT/'contracts/shared_operations/v1/so8_authority.json').read_text());p1=json.loads((ROOT/'contracts/shared_operations/v1/examples/field_service_delivery_profile.json').read_text());p2=json.loads((ROOT/'contracts/shared_operations/v1/examples/clinical_communications_profile.json').read_text())
    assert a['financial_outbox_authority']=='NEUTRAL_FINANCE_PRESERVED' and a['reporting_automation_authority']=='SO9_EXCLUDED' and a['scheduling_authority']=='SO10_EXCLUDED'
    assert p1['terminology']!=p2['terminology'] and p1['channels']!=p2['channels'] and p1['server_truth'] and p2['server_truth']

def test_sql_has_append_only_history_tenant_scopes_and_no_finance_writer():
    up=(ROOT/'alembic_neutral/sql/so8_communications_delivery_offline_up.sql').read_text()
    for marker in ('UNIQUE(tenant_id,command_key)','UNIQUE(tenant_id,job_id,attempt_number)','UNIQUE(tenant_id,source_code,external_event_key)','UNIQUE(tenant_id,device_public_id,client_sequence)','so8_append_only_history'):
        assert marker in up
    assert not any(x in up.lower() for x in ('insert into public.outbox_messages','financial_events','journal_entries','financial_obligations','payment_settlements'))
