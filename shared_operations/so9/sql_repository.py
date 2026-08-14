"""SQLAlchemy repository for SO9 derived read models, reports, metrics, and report automation."""
from __future__ import annotations
import json
from uuid import UUID
from sqlalchemy import text
from .contracts import *
from .service import SO9AuthorityError

class SQLSO9Repository:
    def __init__(self,db_session):self.db_session=db_session
    def command_result(self,tenant_id,command_key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so9_commands WHERE tenant_id=:t AND command_key=:k"),{"t":tenant_id,"k":command_key}).first()
        if not row:return None
        if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO9AuthorityError("SO9_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
        return UUID(str(row.result_public_id)) if row.result_public_id else None
    def _command(self,tenant,key,fingerprint,kind):
        row=self.db_session.execute(text("SELECT * FROM so9_commands WHERE tenant_id=:t AND command_key=:k FOR UPDATE"),{"t":tenant,"k":key}).first()
        if row:
            if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise SO9AuthorityError("SO9_COMMAND_CONFLICT","idempotency_conflict","The command key was already used with different content")
            return row
        return self.db_session.execute(text("INSERT INTO so9_commands(tenant_id,command_key,request_fingerprint,command_type) VALUES(:t,:k,:f,:y) RETURNING *"),{"t":tenant,"k":key,"f":fingerprint,"y":kind}).one()
    def _complete(self,tenant,key,result_type,public_id):
        self.db_session.execute(text("UPDATE so9_commands SET result_type=:y,result_public_id=:p,completed_at=now() WHERE tenant_id=:t AND command_key=:k"),{"y":result_type,"p":str(public_id),"t":tenant,"k":key})
    def _read_model_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF r" if lock else ""
        return self.db_session.execute(text("SELECT r.* FROM so9_read_models r WHERE r.tenant_id=:t AND r.public_id=:p"+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _read_model(v):
        if not v:return None
        return ReadModelDefinition(UUID(str(v.public_id)),v.tenant_id,v.code,v.title,v.source_authority,v.projection_code,v.parameter_schema,DefinitionStatus(v.lifecycle_status),v.row_version)
    def define_read_model(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"define_read_model")
        if replay.result_public_id:return self.read_model(c.tenant_id,replay.result_public_id)
        existing=self.db_session.execute(text("SELECT public_id FROM so9_read_models WHERE tenant_id=:t AND code=:c"),{"t":c.tenant_id,"c":c.code}).first()
        if existing:return None
        self.db_session.execute(text("""INSERT INTO so9_read_models(public_id,tenant_id,code,title,source_authority,projection_code,parameter_schema,lifecycle_status) VALUES(:p,:t,:c,:title,:s,:pc,CAST(:schema AS jsonb),'active')"""),{"p":str(p),"t":c.tenant_id,"c":c.code,"title":c.title,"s":c.source_authority,"pc":c.projection_code,"schema":json.dumps(c.parameter_schema,sort_keys=True)})
        self._complete(c.tenant_id,c.command_key,"read_model",p);return self.read_model(c.tenant_id,p)
    def read_model(self,t,p):return self._read_model(self._read_model_row(t,p))
    def list_read_models(self,t,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so9_read_models WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY code"),{"t":t,"s":getattr(status,"value",status)}).all()
        return tuple(self.read_model(t,UUID(str(x.public_id))) for x in rows)
    def _snapshot_row(self,t,p):
        return self.db_session.execute(text("""SELECT s.*,r.public_id read_model_public_id FROM so9_projection_snapshots s JOIN so9_read_models r ON (r.tenant_id,r.id)=(s.tenant_id,s.read_model_id) WHERE s.tenant_id=:t AND s.public_id=:p"""),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _snapshot(v):
        if not v:return None
        return ProjectionSnapshot(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.read_model_public_id)),v.revision_number,v.as_of_at,v.source_fingerprint,v.payload,v.payload_sha256,v.source_watermark)
    def refresh_read_model(self,c,p,fp,payload_sha256):
        replay=self._command(c.tenant_id,c.command_key,fp,"refresh_read_model")
        if replay.result_public_id:return self.snapshot(c.tenant_id,replay.result_public_id)
        r=self._read_model_row(c.tenant_id,c.read_model_public_id,True)
        if not r or r.lifecycle_status!="active":return None
        revision=self.db_session.execute(text("SELECT COALESCE(max(revision_number),0)+1 FROM so9_projection_snapshots WHERE tenant_id=:t AND read_model_id=:r"),{"t":c.tenant_id,"r":r.id}).scalar_one()
        self.db_session.execute(text("""INSERT INTO so9_projection_snapshots(public_id,tenant_id,read_model_id,revision_number,as_of_at,source_fingerprint,payload,payload_sha256,source_watermark) VALUES(:p,:t,:r,:n,:at,:sf,CAST(:payload AS jsonb),:sha,:w)"""),{"p":str(p),"t":c.tenant_id,"r":r.id,"n":revision,"at":c.occurred_at,"sf":c.source_fingerprint,"payload":json.dumps(c.payload,sort_keys=True),"sha":payload_sha256,"w":c.source_watermark})
        self._complete(c.tenant_id,c.command_key,"snapshot",p);return self.snapshot(c.tenant_id,p)
    def snapshot(self,t,p):return self._snapshot(self._snapshot_row(t,p))
    def snapshots(self,t,read_model_public_id):
        r=self._read_model_row(t,read_model_public_id)
        if not r:return ()
        rows=self.db_session.execute(text("SELECT public_id FROM so9_projection_snapshots WHERE tenant_id=:t AND read_model_id=:r ORDER BY revision_number"),{"t":t,"r":r.id}).all()
        return tuple(self.snapshot(t,UUID(str(x.public_id))) for x in rows)
    def latest_snapshot(self,t,read_model_public_id):
        r=self._read_model_row(t,read_model_public_id)
        if not r:return None
        row=self.db_session.execute(text("SELECT public_id FROM so9_projection_snapshots WHERE tenant_id=:t AND read_model_id=:r ORDER BY revision_number DESC LIMIT 1"),{"t":t,"r":r.id}).first()
        return self.snapshot(t,UUID(str(row.public_id))) if row else None
    def _metric_row(self,t,code):
        return self.db_session.execute(text("""SELECT m.*,r.public_id read_model_public_id FROM so9_metric_definitions m JOIN so9_read_models r ON (r.tenant_id,r.id)=(m.tenant_id,m.read_model_id) WHERE m.tenant_id=:t AND m.metric_code=:c"""),{"t":t,"c":code}).first()
    @staticmethod
    def _metric(v):
        if not v:return None
        return MetricDefinition(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.read_model_public_id)),v.metric_code,v.label,MetricAggregation(v.aggregation_code),v.field_path,v.metadata)
    def define_metric(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"define_metric")
        if replay.result_public_id:
            row=self.db_session.execute(text("SELECT metric_code FROM so9_metric_definitions WHERE tenant_id=:t AND public_id=:p"),{"t":c.tenant_id,"p":str(replay.result_public_id)}).first();return self.metric(c.tenant_id,row.metric_code) if row else None
        r=self._read_model_row(c.tenant_id,c.read_model_public_id)
        if not r or r.lifecycle_status!="active" or self._metric_row(c.tenant_id,c.metric_code):return None
        self.db_session.execute(text("""INSERT INTO so9_metric_definitions(public_id,tenant_id,read_model_id,metric_code,label,aggregation_code,field_path,metadata) VALUES(:p,:t,:r,:c,:l,:a,:f,CAST(:m AS jsonb))"""),{"p":str(p),"t":c.tenant_id,"r":r.id,"c":c.metric_code,"l":c.label,"a":c.aggregation.value,"f":c.field_path,"m":json.dumps(c.metadata,sort_keys=True)})
        self._complete(c.tenant_id,c.command_key,"metric",p);return self.metric(c.tenant_id,c.metric_code)
    def metric(self,t,metric_code):return self._metric(self._metric_row(t,metric_code))
    def metrics_for_read_model(self,t,read_model_public_id):
        r=self._read_model_row(t,read_model_public_id)
        if not r:return ()
        rows=self.db_session.execute(text("SELECT metric_code FROM so9_metric_definitions WHERE tenant_id=:t AND read_model_id=:r ORDER BY metric_code"),{"t":t,"r":r.id}).all()
        return tuple(self.metric(t,x.metric_code) for x in rows)
    def _report_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF d" if lock else ""
        return self.db_session.execute(text("""SELECT d.*,r.public_id read_model_public_id FROM so9_report_definitions d JOIN so9_read_models r ON (r.tenant_id,r.id)=(d.tenant_id,d.read_model_id) WHERE d.tenant_id=:t AND d.public_id=:p"""+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _report(v):
        if not v:return None
        return ReportDefinition(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.read_model_public_id)),v.report_code,v.title,v.parameter_schema,tuple(v.metric_codes),DefinitionStatus(v.lifecycle_status),v.row_version)
    def define_report(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"define_report")
        if replay.result_public_id:return self.report(c.tenant_id,replay.result_public_id)
        r=self._read_model_row(c.tenant_id,c.read_model_public_id)
        if not r or r.lifecycle_status!="active":return None
        if self.db_session.execute(text("SELECT 1 FROM so9_report_definitions WHERE tenant_id=:t AND report_code=:c"),{"t":c.tenant_id,"c":c.report_code}).scalar():return None
        for code in c.metric_codes:
            m=self._metric_row(c.tenant_id,code)
            if not m or m.read_model_id!=r.id:return None
        self.db_session.execute(text("""INSERT INTO so9_report_definitions(public_id,tenant_id,read_model_id,report_code,title,parameter_schema,metric_codes,lifecycle_status) VALUES(:p,:t,:r,:c,:title,CAST(:schema AS jsonb),CAST(:metrics AS jsonb),'active')"""),{"p":str(p),"t":c.tenant_id,"r":r.id,"c":c.report_code,"title":c.title,"schema":json.dumps(c.parameter_schema,sort_keys=True),"metrics":json.dumps(list(c.metric_codes))})
        self._complete(c.tenant_id,c.command_key,"report",p);return self.report(c.tenant_id,p)
    def report(self,t,p):return self._report(self._report_row(t,p))
    def list_reports(self,t,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so9_report_definitions WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY report_code"),{"t":t,"s":getattr(status,"value",status)}).all();return tuple(self.report(t,UUID(str(x.public_id))) for x in rows)
    def _report_run_row(self,t,p):
        return self.db_session.execute(text("""SELECT rr.*,d.public_id report_public_id,s.public_id snapshot_public_id FROM so9_report_runs rr JOIN so9_report_definitions d ON (d.tenant_id,d.id)=(rr.tenant_id,rr.report_id) JOIN so9_projection_snapshots s ON (s.tenant_id,s.id)=(rr.tenant_id,rr.snapshot_id) WHERE rr.tenant_id=:t AND rr.public_id=:p"""),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _report_run(v):
        if not v:return None
        return ReportRun(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.report_public_id)),UUID(str(v.snapshot_public_id)),v.parameters,v.result_payload,v.result_sha256,v.generated_at,RunOutcome(v.outcome))
    def record_report_run(self,c,p,fp,snapshot,result_payload,result_sha256):
        replay=self._command(c.tenant_id,c.command_key,fp,"run_report")
        if replay.result_public_id:return self.report_run(c.tenant_id,replay.result_public_id)
        d=self._report_row(c.tenant_id,c.report_public_id)
        s=self._snapshot_row(c.tenant_id,snapshot.public_id)
        if not d or d.lifecycle_status!="active" or not s or s.read_model_id!=d.read_model_id:return None
        self.db_session.execute(text("""INSERT INTO so9_report_runs(public_id,tenant_id,report_id,snapshot_id,parameters,result_payload,result_sha256,generated_at,outcome) VALUES(:p,:t,:d,:s,CAST(:params AS jsonb),CAST(:result AS jsonb),:sha,:at,'succeeded')"""),{"p":str(p),"t":c.tenant_id,"d":d.id,"s":s.id,"params":json.dumps(c.parameters,sort_keys=True),"result":json.dumps(result_payload,sort_keys=True),"sha":result_sha256,"at":c.occurred_at})
        self._complete(c.tenant_id,c.command_key,"report_run",p);return self.report_run(c.tenant_id,p)
    def report_run(self,t,p):return self._report_run(self._report_run_row(t,p))
    def report_runs(self,t,report_public_id):
        d=self._report_row(t,report_public_id)
        if not d:return ()
        rows=self.db_session.execute(text("SELECT public_id FROM so9_report_runs WHERE tenant_id=:t AND report_id=:d ORDER BY id"),{"t":t,"d":d.id}).all();return tuple(self.report_run(t,UUID(str(x.public_id))) for x in rows)
    def _automation_row(self,t,p,lock=False):
        suffix=" FOR UPDATE OF a" if lock else ""
        return self.db_session.execute(text("""SELECT a.*,d.public_id report_public_id,d.read_model_id report_read_model_id FROM so9_automation_rules a JOIN so9_report_definitions d ON (d.tenant_id,d.id)=(a.tenant_id,a.report_id) WHERE a.tenant_id=:t AND a.public_id=:p"""+suffix),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _automation(v):
        if not v:return None
        return AutomationRule(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.report_public_id)),v.automation_code,v.trigger_code,v.trigger_config,AutomationStatus(v.lifecycle_status),v.delivery_enabled,v.delivery_kind,v.channel_code,v.destination_reference,v.row_version)
    def configure_automation(self,c,p,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"configure_automation")
        if replay.result_public_id:return self.automation(c.tenant_id,replay.result_public_id)
        d=self._report_row(c.tenant_id,c.report_public_id)
        if not d or d.lifecycle_status!="active" or self.db_session.execute(text("SELECT 1 FROM so9_automation_rules WHERE tenant_id=:t AND automation_code=:c"),{"t":c.tenant_id,"c":c.automation_code}).scalar():return None
        self.db_session.execute(text("""INSERT INTO so9_automation_rules(public_id,tenant_id,report_id,automation_code,trigger_code,trigger_config,lifecycle_status,delivery_enabled,delivery_kind,channel_code,destination_reference) VALUES(:p,:t,:d,:c,:tr,CAST(:cfg AS jsonb),'active',:de,:dk,:ch,:dest)"""),{"p":str(p),"t":c.tenant_id,"d":d.id,"c":c.automation_code,"tr":c.trigger_code,"cfg":json.dumps(c.trigger_config,sort_keys=True),"de":c.delivery_enabled,"dk":c.delivery_kind,"ch":c.channel_code,"dest":c.destination_reference})
        self._complete(c.tenant_id,c.command_key,"automation",p);return self.automation(c.tenant_id,p)
    def automation(self,t,p):return self._automation(self._automation_row(t,p))
    def list_automations(self,t,status=None):
        rows=self.db_session.execute(text("SELECT public_id FROM so9_automation_rules WHERE tenant_id=:t AND (:s IS NULL OR lifecycle_status=:s) ORDER BY automation_code"),{"t":t,"s":getattr(status,"value",status)}).all();return tuple(self.automation(t,UUID(str(x.public_id))) for x in rows)
    def change_automation_status(self,c,fp):
        replay=self._command(c.tenant_id,c.command_key,fp,"change_automation_status")
        if replay.result_public_id:return self.automation(c.tenant_id,replay.result_public_id)
        a=self._automation_row(c.tenant_id,c.automation_public_id,True)
        if not a or a.row_version!=c.expected_version:return None
        if a.lifecycle_status=="retired":return None
        updated=self.db_session.execute(text("UPDATE so9_automation_rules SET lifecycle_status=:s,row_version=row_version+1,updated_at=now() WHERE tenant_id=:t AND id=:id AND row_version=:v RETURNING id"),{"s":c.to_status.value,"t":c.tenant_id,"id":a.id,"v":c.expected_version}).first()
        if not updated:return None
        self._complete(c.tenant_id,c.command_key,"automation",c.automation_public_id);return self.automation(c.tenant_id,c.automation_public_id)
    def _automation_run_row(self,t,p):
        return self.db_session.execute(text("""SELECT ar.*,a.public_id automation_public_id,rr.public_id report_run_public_id FROM so9_automation_runs ar JOIN so9_automation_rules a ON (a.tenant_id,a.id)=(ar.tenant_id,ar.automation_id) JOIN so9_report_runs rr ON (rr.tenant_id,rr.id)=(ar.tenant_id,ar.report_run_id) WHERE ar.tenant_id=:t AND ar.public_id=:p"""),{"t":t,"p":str(p)}).first()
    @staticmethod
    def _automation_run(v):
        if not v:return None
        return AutomationRun(UUID(str(v.public_id)),v.tenant_id,UUID(str(v.automation_public_id)),UUID(str(v.report_run_public_id)),v.execution_key,RunOutcome(v.outcome),v.occurred_at,UUID(str(v.delivery_job_public_id)) if v.delivery_job_public_id else None)
    def execute_automation(self,c,ap,rp,fp,snapshot,result_payload,result_sha256,delivery_job_public_id):
        replay=self._command(c.tenant_id,c.command_key,fp,"execute_automation")
        if replay.result_public_id:return self.automation_run(c.tenant_id,replay.result_public_id)
        a=self._automation_row(c.tenant_id,c.automation_public_id,True)
        if not a or a.lifecycle_status!="active":return None
        existing=self.db_session.execute(text("SELECT public_id FROM so9_automation_runs WHERE tenant_id=:t AND automation_id=:a AND execution_key=:e"),{"t":c.tenant_id,"a":a.id,"e":c.execution_key}).first()
        if existing:return None
        s=self._snapshot_row(c.tenant_id,snapshot.public_id)
        if not s or s.read_model_id!=a.report_read_model_id:return None
        rr=self.db_session.execute(text("""INSERT INTO so9_report_runs(public_id,tenant_id,report_id,snapshot_id,parameters,result_payload,result_sha256,generated_at,outcome) VALUES(:p,:t,:d,:s,CAST(:params AS jsonb),CAST(:result AS jsonb),:sha,:at,'succeeded') RETURNING id"""),{"p":str(rp),"t":c.tenant_id,"d":a.report_id,"s":s.id,"params":json.dumps(c.parameters,sort_keys=True),"result":json.dumps(result_payload,sort_keys=True),"sha":result_sha256,"at":c.occurred_at}).one()
        self.db_session.execute(text("""INSERT INTO so9_automation_runs(public_id,tenant_id,automation_id,report_run_id,execution_key,outcome,occurred_at,delivery_job_public_id) VALUES(:p,:t,:a,:r,:e,'succeeded',:at,:d)"""),{"p":str(ap),"t":c.tenant_id,"a":a.id,"r":rr.id,"e":c.execution_key,"at":c.occurred_at,"d":str(delivery_job_public_id) if delivery_job_public_id else None})
        self._complete(c.tenant_id,c.command_key,"automation_run",ap);return self.automation_run(c.tenant_id,ap)
    def automation_run(self,t,p):return self._automation_run(self._automation_run_row(t,p))
    def automation_runs(self,t,automation_public_id):
        a=self._automation_row(t,automation_public_id)
        if not a:return ()
        rows=self.db_session.execute(text("SELECT public_id FROM so9_automation_runs WHERE tenant_id=:t AND automation_id=:a ORDER BY id"),{"t":t,"a":a.id}).all();return tuple(self.automation_run(t,UUID(str(x.public_id))) for x in rows)
