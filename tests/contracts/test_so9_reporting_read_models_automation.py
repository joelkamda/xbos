from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
import pytest

from shared_operations.so9 import *

ROOT=Path(__file__).resolve().parents[2]
NOW=datetime(2026,8,14,19,0,tzinfo=timezone.utc)
RID=UUID(int=9001);S1=UUID(int=9002);M1=UUID(int=9003);M2=UUID(int=9004);REP=UUID(int=9005);RUN=UUID(int=9006);AUTO=UUID(int=9007);ARUN=UUID(int=9008);AUTORUNREP=UUID(int=9009);DELIVERY=UUID(int=9010)

class FakeRepo:
    def __init__(self):
        self.read_models={};self.snapshots_by_id={};self.metrics={};self.reports={};self.report_runs_by_id={};self.automations={};self.automation_runs_by_id={};self.commands={}
    def command_result(self,t,key,fp,kind):
        old=self.commands.get((t,key))
        if not old:return None
        if old[:2]!=(fp,kind):raise SO9AuthorityError('SO9_COMMAND_CONFLICT','idempotency_conflict','conflict')
        return old[2]
    def _cmd(self,c,fp,kind):
        old=self.commands.get((c.tenant_id,c.command_key))
        if old and old[:2]!=(fp,kind):raise SO9AuthorityError('SO9_COMMAND_CONFLICT','idempotency_conflict','conflict')
        return old
    def _complete(self,c,fp,kind,p):self.commands[(c.tenant_id,c.command_key)]=(fp,kind,p)
    def define_read_model(self,c,p,fp):
        old=self._cmd(c,fp,'define_read_model')
        if old:return self.read_models[old[2]]
        if any(x.tenant_id==c.tenant_id and x.code==c.code for x in self.read_models.values()):return None
        r=ReadModelDefinition(p,c.tenant_id,c.code,c.title,c.source_authority,c.projection_code,c.parameter_schema);self.read_models[p]=r;self._complete(c,fp,'define_read_model',p);return r
    def read_model(self,t,p):
        r=self.read_models.get(p);return r if r and r.tenant_id==t else None
    def list_read_models(self,t,status=None):return tuple(x for x in self.read_models.values() if x.tenant_id==t and (status is None or x.status==status))
    def refresh_read_model(self,c,p,fp,sha):
        old=self._cmd(c,fp,'refresh_read_model')
        if old:return self.snapshots_by_id[old[2]]
        r=self.read_model(c.tenant_id,c.read_model_public_id)
        if not r or r.status is not DefinitionStatus.ACTIVE:return None
        n=1+max([x.revision_number for x in self.snapshots_by_id.values() if x.tenant_id==c.tenant_id and x.read_model_public_id==r.public_id] or [0])
        s=ProjectionSnapshot(p,c.tenant_id,r.public_id,n,c.occurred_at,c.source_fingerprint,c.payload,sha,c.source_watermark);self.snapshots_by_id[p]=s;self._complete(c,fp,'refresh_read_model',p);return s
    def snapshot(self,t,p):
        s=self.snapshots_by_id.get(p);return s if s and s.tenant_id==t else None
    def snapshots(self,t,p):return tuple(sorted((x for x in self.snapshots_by_id.values() if x.tenant_id==t and x.read_model_public_id==p),key=lambda x:x.revision_number))
    def latest_snapshot(self,t,p):
        xs=self.snapshots(t,p);return xs[-1] if xs else None
    def define_metric(self,c,p,fp):
        old=self._cmd(c,fp,'define_metric')
        if old:return next(x for x in self.metrics.values() if x.public_id==old[2])
        if not self.read_model(c.tenant_id,c.read_model_public_id) or (c.tenant_id,c.metric_code) in self.metrics:return None
        m=MetricDefinition(p,c.tenant_id,c.read_model_public_id,c.metric_code,c.label,c.aggregation,c.field_path,c.metadata);self.metrics[(c.tenant_id,c.metric_code)]=m;self._complete(c,fp,'define_metric',p);return m
    def metric(self,t,code):return self.metrics.get((t,code))
    def metrics_for_read_model(self,t,p):return tuple(x for (tenant,_),x in self.metrics.items() if tenant==t and x.read_model_public_id==p)
    def define_report(self,c,p,fp):
        old=self._cmd(c,fp,'define_report')
        if old:return self.reports[old[2]]
        if not self.read_model(c.tenant_id,c.read_model_public_id):return None
        if any(x.tenant_id==c.tenant_id and x.report_code==c.report_code for x in self.reports.values()):return None
        if any((not self.metric(c.tenant_id,m) or self.metric(c.tenant_id,m).read_model_public_id!=c.read_model_public_id) for m in c.metric_codes):return None
        r=ReportDefinition(p,c.tenant_id,c.read_model_public_id,c.report_code,c.title,c.parameter_schema,c.metric_codes);self.reports[p]=r;self._complete(c,fp,'define_report',p);return r
    def report(self,t,p):
        r=self.reports.get(p);return r if r and r.tenant_id==t else None
    def list_reports(self,t,status=None):return tuple(x for x in self.reports.values() if x.tenant_id==t and (status is None or x.status==status))
    def record_report_run(self,c,p,fp,snapshot,result_payload,result_sha256):
        old=self._cmd(c,fp,'run_report')
        if old:return self.report_runs_by_id[old[2]]
        r=self.report(c.tenant_id,c.report_public_id)
        if not r or snapshot.read_model_public_id!=r.read_model_public_id:return None
        rr=ReportRun(p,c.tenant_id,r.public_id,snapshot.public_id,c.parameters,result_payload,result_sha256,c.occurred_at);self.report_runs_by_id[p]=rr;self._complete(c,fp,'run_report',p);return rr
    def report_run(self,t,p):
        r=self.report_runs_by_id.get(p);return r if r and r.tenant_id==t else None
    def report_runs(self,t,p):return tuple(x for x in self.report_runs_by_id.values() if x.tenant_id==t and x.report_public_id==p)
    def configure_automation(self,c,p,fp):
        old=self._cmd(c,fp,'configure_automation')
        if old:return self.automations[old[2]]
        if not self.report(c.tenant_id,c.report_public_id):return None
        if any(x.tenant_id==c.tenant_id and x.automation_code==c.automation_code for x in self.automations.values()):return None
        a=AutomationRule(p,c.tenant_id,c.report_public_id,c.automation_code,c.trigger_code,c.trigger_config,AutomationStatus.ACTIVE,c.delivery_enabled,c.delivery_kind,c.channel_code,c.destination_reference,1);self.automations[p]=a;self._complete(c,fp,'configure_automation',p);return a
    def automation(self,t,p):
        a=self.automations.get(p);return a if a and a.tenant_id==t else None
    def list_automations(self,t,status=None):return tuple(x for x in self.automations.values() if x.tenant_id==t and (status is None or x.status==status))
    def change_automation_status(self,c,fp):
        old=self._cmd(c,fp,'change_automation_status')
        if old:return self.automations[old[2]]
        a=self.automation(c.tenant_id,c.automation_public_id)
        if not a or a.row_version!=c.expected_version or a.status is AutomationStatus.RETIRED:return None
        a=replace(a,status=c.to_status,row_version=a.row_version+1);self.automations[a.public_id]=a;self._complete(c,fp,'change_automation_status',a.public_id);return a
    def execute_automation(self,c,ap,rp,fp,snapshot,result_payload,result_sha256,delivery_job_public_id):
        old=self._cmd(c,fp,'execute_automation')
        if old:return self.automation_runs_by_id[old[2]]
        a=self.automation(c.tenant_id,c.automation_public_id)
        if not a or a.status is not AutomationStatus.ACTIVE:return None
        if any(x.tenant_id==c.tenant_id and x.automation_public_id==a.public_id and x.execution_key==c.execution_key for x in self.automation_runs_by_id.values()):return None
        rr=ReportRun(rp,c.tenant_id,a.report_public_id,snapshot.public_id,c.parameters,result_payload,result_sha256,c.occurred_at);self.report_runs_by_id[rp]=rr
        ar=AutomationRun(ap,c.tenant_id,a.public_id,rp,c.execution_key,RunOutcome.SUCCEEDED,c.occurred_at,delivery_job_public_id);self.automation_runs_by_id[ap]=ar;self._complete(c,fp,'execute_automation',ap);return ar
    def automation_run(self,t,p):
        a=self.automation_runs_by_id.get(p);return a if a and a.tenant_id==t else None
    def automation_runs(self,t,p):return tuple(x for x in self.automation_runs_by_id.values() if x.tenant_id==t and x.automation_public_id==p)

def authority(ids=None,permit=True,tenant=1,deliver=True):
    repo=FakeRepo();ids=iter(ids or [RID,S1,M1,M2,REP,RUN,AUTO,ARUN,AUTORUNREP,UUID(int=9011),UUID(int=9012)])
    deliveries={}
    def handoff(t,key,kind,channel,dest,payload,at):
        if not deliver:raise AssertionError('should not deliver')
        old=deliveries.get((t,key))
        value=(kind,channel,dest,payload,at)
        if old and old[0]!=value:raise SO9AuthorityError('SO8_COMMAND_CONFLICT','idempotency_conflict','changed delivery')
        if old:return old[1]
        deliveries[(t,key)]=(value,DELIVERY);return DELIVERY
    so9=SO9Authority(repo,authorize=lambda *x:permit,source_resolver=lambda t,s:t==tenant and s in {'so6.workflow','so5.resources','finance.reconciliation'},delivery_handoff=handoff,public_id_factory=lambda:next(ids))
    return so9,repo,deliveries

def base(so9):
    rm=so9.define_read_model(DefineReadModel('rm',1,'service.performance','Service Performance','so6.workflow','workflow.performance',{}))
    snap=so9.refresh_read_model(RefreshReadModel('refresh',1,rm.public_id,'a'*64,{'rows':[{'duration':10,'completed':1},{'duration':20,'completed':1},{'duration':30,'completed':0}]},NOW,'wf:42'))
    count=so9.define_metric(DefineMetric('m-count',1,rm.public_id,'job_count','Job Count',MetricAggregation.COUNT))
    total=so9.define_metric(DefineMetric('m-total',1,rm.public_id,'duration_sum','Duration Sum',MetricAggregation.SUM,'duration'))
    report=so9.define_report(DefineReport('report',1,rm.public_id,'service.summary','Service Summary',{},('job_count','duration_sum')))
    return rm,snap,count,total,report

def test_read_model_refresh_is_derived_versioned_and_exact_replay():
    so9,repo,_=authority();rm=so9.define_read_model(DefineReadModel('rm',1,'ops.view','Ops View','so6.workflow','ops.summary',{}));cmd=RefreshReadModel('r1',1,rm.public_id,'a'*64,{'rows':[{'value':1}]},NOW,'v1');s=so9.refresh_read_model(cmd)
    assert so9.refresh_read_model(cmd)==s and len(repo.snapshots_by_id)==1 and s.revision_number==1 and len(s.payload_sha256)==64
    s2=so9.refresh_read_model(replace(cmd,command_key='r2',source_fingerprint='b'*64,payload={'rows':[{'value':2}]},source_watermark='v2'))
    assert s2.revision_number==2 and [x.revision_number for x in so9.snapshots(1,rm.public_id)]==[1,2]
    with pytest.raises(SO9AuthorityError,match='SO9_COMMAND_CONFLICT'):so9.refresh_read_model(replace(cmd,payload={'rows':[{'value':9}]}))

def test_metrics_are_deterministic_derived_values():
    so9,_,_=authority();rm,snap,_,_,_=base(so9)
    assert so9.metric_value(1,'job_count',snap.public_id)==3
    assert so9.metric_value(1,'duration_sum',snap.public_id)=='60'
    avg=so9.define_metric(DefineMetric('m-avg',1,rm.public_id,'duration_avg','Average Duration',MetricAggregation.AVERAGE,'duration'))
    assert avg.metric_code=='duration_avg' and so9.metric_value(1,'duration_avg',snap.public_id)=='20'

def test_report_run_binds_one_snapshot_and_is_idempotent():
    so9,repo,_=authority();_,snap,_,_,report=base(so9);cmd=RunReport('run',1,report.public_id,NOW,{'period':'today'},snap.public_id);run=so9.run_report(cmd)
    assert so9.run_report(cmd)==run and len(repo.report_runs_by_id)==1 and run.result_payload['metrics']=={'job_count':3,'duration_sum':'60'} and run.result_payload['data']==snap.payload
    with pytest.raises(SO9AuthorityError,match='SO9_COMMAND_CONFLICT'):so9.run_report(replace(cmd,parameters={'period':'week'}))

def test_automation_uses_so8_handoff_without_becoming_delivery_authority():
    so9,repo,deliveries=authority();_,snap,_,_,report=base(so9);a=so9.configure_automation(ConfigureAutomation('auto',1,report.public_id,'daily.summary','daily_window_resolved',{'timezone':'Africa/Douala'},True,'report','email','ops@example.invalid'))
    cmd=ExecuteAutomation('exec',1,a.public_id,'2026-08-14',NOW,{'period':'day'},snap.public_id);run=so9.execute_automation(cmd)
    assert so9.execute_automation(cmd)==run and run.delivery_job_public_id==DELIVERY and len(deliveries)==1 and len(repo.automation_runs_by_id)==1
    with pytest.raises(SO9AuthorityError,match='SO9_COMMAND_CONFLICT'):so9.execute_automation(replace(cmd,parameters={'period':'changed'}))

def test_automation_execution_identity_deduplicates_so8_handoff_across_command_keys():
    so9,_,deliveries=authority();_,snap,_,_,report=base(so9);a=so9.configure_automation(ConfigureAutomation('auto',1,report.public_id,'daily.summary','daily_window_resolved',{},True,'report','email','ops@example.invalid'))
    cmd=ExecuteAutomation('exec-a',1,a.public_id,'window-42',NOW,{'period':'day'},snap.public_id);so9.execute_automation(cmd)
    with pytest.raises(SO9AuthorityError,match='SO9_AUTOMATION_EXECUTION_CONFLICT'):
        so9.execute_automation(replace(cmd,command_key='exec-b'))
    assert len(deliveries)==1
    with pytest.raises(SO9AuthorityError,match='SO8_COMMAND_CONFLICT'):
        so9.execute_automation(replace(cmd,command_key='exec-c',parameters={'period':'changed'}))
    assert len(deliveries)==1

def test_automation_status_is_explicit_and_server_enforced():
    so9,_,_=authority();_,_,_,_,report=base(so9);a=so9.configure_automation(ConfigureAutomation('auto',1,report.public_id,'ops.summary','manual',{},False));a=so9.change_automation_status(ChangeAutomationStatus('pause',1,a.public_id,a.row_version,AutomationStatus.PAUSED,NOW));assert a.status is AutomationStatus.PAUSED
    with pytest.raises(SO9AuthorityError,match='SO9_AUTOMATION_NOT_ACTIVE'):so9.execute_automation(ExecuteAutomation('x',1,a.public_id,'x',NOW,{}))

def test_tenant_scope_source_authority_and_permission_fail_closed():
    so9,_,_=authority()
    with pytest.raises(SO9AuthorityError,match='SO9_SOURCE_AUTHORITY_NOT_FOUND'):so9.define_read_model(DefineReadModel('bad',2,'ops','Ops','so6.workflow','ops',{}))
    denied,_,_=authority(permit=False)
    with pytest.raises(SO9AuthorityError,match='SO9_PERMISSION_DENIED'):denied.define_read_model(DefineReadModel('bad',1,'ops','Ops','so6.workflow','ops',{}))

def test_contracts_neutrality_finance_and_scheduling_boundaries():
    a=json.loads((ROOT/'contracts/shared_operations/v1/so9_authority.json').read_text());p1=json.loads((ROOT/'contracts/shared_operations/v1/examples/field_service_reporting_profile.json').read_text());p2=json.loads((ROOT/'contracts/shared_operations/v1/examples/clinical_reporting_profile.json').read_text())
    assert a['read_model_authority']=='SO9_DERIVED_REBUILDABLE' and a['financial_reporting_authority']=='NEUTRAL_FINANCE_PRESERVED' and a['delivery_authority']=='SO8_REUSED' and a['scheduling_authority']=='SO10_EXCLUDED'
    assert p1['terminology']!=p2['terminology'] and p1['metrics']!=p2['metrics'] and p1['financial_truth']==p2['financial_truth']=='NONE'

def test_pc0_reports_promotion_is_governed_not_a_hardcoded_exception():
    module=json.loads((ROOT/'contracts/platform/v1/pc0_module_map.json').read_text());authority=json.loads((ROOT/'contracts/platform/v1/pc0_data_authority_register.json').read_text());migration=json.loads((ROOT/'contracts/platform/v1/pc0_reference_authority_migration_register.json').read_text())
    reports=next(x for x in module['modules'] if x['code']=='reports');a=next(x for x in authority['authorities'] if x.get('module')=='reports');m=next(x for x in migration['entries'] if x.get('module_code')=='reports')
    assert (reports['owner'],reports['kind'])==('SO9','shared_operations_authority') and 'shared_operations/so9' in reports['source_roots']
    assert a['code']==m['target_data_authority']=='operational_reporting_read_models' and (m['previous_module_owner'],m['previous_module_kind'])==('SO9 / Neutral Finance by report authority','legacy_operational')

def test_sql_has_append_only_derived_history_and_no_source_or_finance_writer():
    up=(ROOT/'alembic_neutral/sql/so9_reporting_read_models_automation_up.sql').read_text()
    for marker in ('UNIQUE(tenant_id,command_key)','UNIQUE(tenant_id,read_model_id,revision_number)','UNIQUE(tenant_id,automation_id,execution_key)','so9_derived_history_immutable'):
        assert marker in up
    assert not any(x in up.lower() for x in ('insert into public.financial_events','insert into public.journal_entries','insert into public.financial_obligations','insert into public.payment_settlements','insert into public.so8_delivery_jobs','update public.so6_workflows'))
