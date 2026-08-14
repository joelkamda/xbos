"""SO9 derived reporting, read-model, metric, and report-automation authority."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,replace
from decimal import Decimal,InvalidOperation
from typing import Callable,Protocol
from uuid import UUID,uuid4
from .contracts import *

class SO9AuthorityError(RuntimeError):
    def __init__(self,code:str,category:str,explanation:str,*,retryable:bool=False):
        self.code=code;self.category=category;self.safe_explanation=explanation;self.retryable=retryable
        super().__init__(code)

class SO9Repository(Protocol):
    def command_result(self,tenant_id,command_key,fingerprint,kind): ...
    def define_read_model(self,command,public_id,fingerprint)->ReadModelDefinition: ...
    def read_model(self,tenant_id,public_id)->ReadModelDefinition|None: ...
    def list_read_models(self,tenant_id,status=None): ...
    def refresh_read_model(self,command,public_id,fingerprint,payload_sha256)->ProjectionSnapshot|None: ...
    def snapshot(self,tenant_id,public_id)->ProjectionSnapshot|None: ...
    def snapshots(self,tenant_id,read_model_public_id): ...
    def latest_snapshot(self,tenant_id,read_model_public_id)->ProjectionSnapshot|None: ...
    def define_metric(self,command,public_id,fingerprint)->MetricDefinition|None: ...
    def metric(self,tenant_id,metric_code)->MetricDefinition|None: ...
    def metrics_for_read_model(self,tenant_id,read_model_public_id): ...
    def define_report(self,command,public_id,fingerprint)->ReportDefinition|None: ...
    def report(self,tenant_id,public_id)->ReportDefinition|None: ...
    def list_reports(self,tenant_id,status=None): ...
    def record_report_run(self,command,public_id,fingerprint,snapshot,result_payload,result_sha256)->ReportRun|None: ...
    def report_run(self,tenant_id,public_id)->ReportRun|None: ...
    def report_runs(self,tenant_id,report_public_id): ...
    def configure_automation(self,command,public_id,fingerprint)->AutomationRule|None: ...
    def automation(self,tenant_id,public_id)->AutomationRule|None: ...
    def list_automations(self,tenant_id,status=None): ...
    def change_automation_status(self,command,fingerprint)->AutomationRule|None: ...
    def execute_automation(self,command,automation_run_public_id,report_run_public_id,fingerprint,snapshot,result_payload,result_sha256,delivery_job_public_id)->AutomationRun|None: ...
    def automation_run(self,tenant_id,public_id)->AutomationRun|None: ...
    def automation_runs(self,tenant_id,automation_public_id): ...

class SO9Authority:
    def __init__(self,repository:SO9Repository,*,authorize:Callable,source_resolver:Callable|None=None,
                 delivery_handoff:Callable|None=None,public_id_factory:Callable[[],UUID]=uuid4):
        self.repository=repository;self.authorize=authorize;self.source_resolver=source_resolver
        self.delivery_handoff=delivery_handoff;self.public_id_factory=public_id_factory
    @staticmethod
    def _fingerprint(command):return hashlib.sha256(json.dumps(asdict(command),sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _payload_hash(payload):return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
    @staticmethod
    def _code(value,field):
        value=value.strip().lower()
        if not value or len(value)>160 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in value):
            raise SO9AuthorityError("SO9_INVALID_"+field.upper(),"validation_failure",field+" must be a bounded neutral code")
        return value
    @staticmethod
    def _text(value,field,max_length=500):
        value=value.strip()
        if not value or len(value)>max_length:raise SO9AuthorityError("SO9_INVALID_"+field.upper(),"validation_failure",field+" is required and bounded")
        return value
    @staticmethod
    def _object(value,field="payload"):
        if not isinstance(value,dict):raise SO9AuthorityError("SO9_INVALID_"+field.upper(),"validation_failure",field+" must be an object")
        return value
    @staticmethod
    def _sha(value,field="source_fingerprint"):
        value=value.strip().lower()
        if len(value)!=64 or any(c not in "0123456789abcdef" for c in value):raise SO9AuthorityError("SO9_INVALID_"+field.upper(),"validation_failure",field+" must be lowercase SHA-256")
        return value
    def _permit(self,tenant,permission):
        if not self.authorize(tenant,permission,"tenant",tenant):raise SO9AuthorityError("SO9_PERMISSION_DENIED","permission_denied","The reporting operation is not permitted")
    def define_read_model(self,command:DefineReadModel):
        self._permit(command.tenant_id,"report.read_model.define")
        source=self._code(command.source_authority,"source_authority")
        if self.source_resolver and not self.source_resolver(command.tenant_id,source):raise SO9AuthorityError("SO9_SOURCE_AUTHORITY_NOT_FOUND","scope_mismatch","The source authority is not available in this tenant")
        normalized=replace(command,code=self._code(command.code,"code"),title=self._text(command.title,"title"),source_authority=source,projection_code=self._code(command.projection_code,"projection_code"),parameter_schema=self._object(command.parameter_schema,"parameter_schema"))
        return self.repository.define_read_model(normalized,self.public_id_factory(),self._fingerprint(normalized))
    def read_model(self,tenant_id,public_id):self._permit(tenant_id,"report.view");return self.repository.read_model(tenant_id,public_id)
    def list_read_models(self,tenant_id,status=None):self._permit(tenant_id,"report.view");return self.repository.list_read_models(tenant_id,status)
    def refresh_read_model(self,command:RefreshReadModel):
        self._permit(command.tenant_id,"report.read_model.refresh")
        payload=self._object(command.payload);rows=payload.get("rows")
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise SO9AuthorityError("SO9_INVALID_PROJECTION_ROWS","validation_failure","derived projection payload must contain a rows array of objects")
        normalized=replace(command,source_fingerprint=self._sha(command.source_fingerprint),payload=payload,source_watermark=self._text(command.source_watermark,"source_watermark",240) if command.source_watermark else None)
        result=self.repository.refresh_read_model(normalized,self.public_id_factory(),self._fingerprint(normalized),self._payload_hash(payload))
        if result is None:raise SO9AuthorityError("SO9_READ_MODEL_REFRESH_CONFLICT","conflict","The read model is absent, archived, or changed concurrently")
        return result
    def snapshot(self,tenant_id,public_id):self._permit(tenant_id,"report.view");return self.repository.snapshot(tenant_id,public_id)
    def snapshots(self,tenant_id,read_model_public_id):self._permit(tenant_id,"report.view");return self.repository.snapshots(tenant_id,read_model_public_id)
    def latest_snapshot(self,tenant_id,read_model_public_id):self._permit(tenant_id,"report.view");return self.repository.latest_snapshot(tenant_id,read_model_public_id)
    def define_metric(self,command:DefineMetric):
        self._permit(command.tenant_id,"report.metric.define")
        field=command.field_path.strip() if command.field_path else None
        if command.aggregation is not MetricAggregation.COUNT and not field:raise SO9AuthorityError("SO9_METRIC_FIELD_REQUIRED","validation_failure","non-count metrics require a field path")
        if field and (len(field)>240 or any(not part or not part.replace("_","").replace("-","").isalnum() for part in field.split("."))):raise SO9AuthorityError("SO9_INVALID_FIELD_PATH","validation_failure","metric field path is invalid")
        normalized=replace(command,metric_code=self._code(command.metric_code,"metric_code"),label=self._text(command.label,"label"),field_path=field,metadata=self._object(command.metadata,"metadata"))
        result=self.repository.define_metric(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO9AuthorityError("SO9_METRIC_DEFINITION_CONFLICT","conflict","The metric read model is absent or incompatible")
        return result
    @staticmethod
    def _field(row,path):
        value=row
        for part in path.split("."):
            if not isinstance(value,dict) or part not in value:return None
            value=value[part]
        return value
    @classmethod
    def _metric_value(cls,metric:MetricDefinition,snapshot:ProjectionSnapshot):
        rows=snapshot.payload.get("rows",[])
        if metric.aggregation is MetricAggregation.COUNT:return len(rows)
        values=[]
        for row in rows:
            raw=cls._field(row,metric.field_path or "")
            if raw is None:continue
            try:values.append(Decimal(str(raw)))
            except (InvalidOperation,ValueError,TypeError):raise SO9AuthorityError("SO9_METRIC_NON_NUMERIC","validation_failure","metric source contains a non-numeric value")
        if not values:return None
        if metric.aggregation is MetricAggregation.SUM:value=sum(values,Decimal("0"))
        elif metric.aggregation is MetricAggregation.AVERAGE:value=sum(values,Decimal("0"))/Decimal(len(values))
        elif metric.aggregation is MetricAggregation.MIN:value=min(values)
        else:value=max(values)
        return str(value.normalize()) if value!=value.to_integral() else str(value.quantize(Decimal("1")))
    def metric_value(self,tenant_id,metric_code,snapshot_public_id=None):
        self._permit(tenant_id,"report.view");metric=self.repository.metric(tenant_id,self._code(metric_code,"metric_code"))
        if not metric:raise SO9AuthorityError("SO9_METRIC_NOT_FOUND","not_found","The metric was not found")
        snapshot=self.repository.snapshot(tenant_id,snapshot_public_id) if snapshot_public_id else self.repository.latest_snapshot(tenant_id,metric.read_model_public_id)
        if not snapshot or snapshot.read_model_public_id!=metric.read_model_public_id:raise SO9AuthorityError("SO9_SNAPSHOT_NOT_FOUND","not_found","A compatible projection snapshot was not found")
        return self._metric_value(metric,snapshot)
    def define_report(self,command:DefineReport):
        self._permit(command.tenant_id,"report.define")
        codes=tuple(self._code(code,"metric_code") for code in command.metric_codes)
        if len(codes)!=len(set(codes)):raise SO9AuthorityError("SO9_DUPLICATE_METRIC","validation_failure","report metric codes must be unique")
        normalized=replace(command,report_code=self._code(command.report_code,"report_code"),title=self._text(command.title,"title"),parameter_schema=self._object(command.parameter_schema,"parameter_schema"),metric_codes=codes)
        result=self.repository.define_report(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO9AuthorityError("SO9_REPORT_DEFINITION_CONFLICT","conflict","The report read model or metrics are absent or incompatible")
        return result
    def report(self,tenant_id,public_id):self._permit(tenant_id,"report.view");return self.repository.report(tenant_id,public_id)
    def list_reports(self,tenant_id,status=None):self._permit(tenant_id,"report.view");return self.repository.list_reports(tenant_id,status)
    def _render(self,tenant_id,report_public_id,snapshot_public_id,parameters):
        report=self.repository.report(tenant_id,report_public_id)
        if not report or report.status is not DefinitionStatus.ACTIVE:raise SO9AuthorityError("SO9_REPORT_NOT_FOUND","not_found","The active report was not found")
        snapshot=self.repository.snapshot(tenant_id,snapshot_public_id) if snapshot_public_id else self.repository.latest_snapshot(tenant_id,report.read_model_public_id)
        if not snapshot or snapshot.read_model_public_id!=report.read_model_public_id:raise SO9AuthorityError("SO9_SNAPSHOT_NOT_FOUND","not_found","A compatible projection snapshot was not found")
        metrics={}
        for code in report.metric_codes:
            metric=self.repository.metric(tenant_id,code)
            if not metric or metric.read_model_public_id!=report.read_model_public_id:raise SO9AuthorityError("SO9_METRIC_NOT_FOUND","not_found","A report metric was not found")
            metrics[code]=self._metric_value(metric,snapshot)
        result={"report_code":report.report_code,"snapshot_public_id":str(snapshot.public_id),"parameters":parameters,"metrics":metrics,"data":snapshot.payload}
        return report,snapshot,result,self._payload_hash(result)
    def run_report(self,command:RunReport):
        self._permit(command.tenant_id,"report.run");params=self._object(command.parameters,"parameters");normalized=replace(command,parameters=params)
        _,snapshot,result,sha=self._render(command.tenant_id,command.report_public_id,command.snapshot_public_id,params)
        run=self.repository.record_report_run(normalized,self.public_id_factory(),self._fingerprint(normalized),snapshot,result,sha)
        if run is None:raise SO9AuthorityError("SO9_REPORT_RUN_CONFLICT","conflict","The report run could not be recorded")
        return run
    def report_run(self,tenant_id,public_id):self._permit(tenant_id,"report.view");return self.repository.report_run(tenant_id,public_id)
    def report_runs(self,tenant_id,report_public_id):self._permit(tenant_id,"report.view");return self.repository.report_runs(tenant_id,report_public_id)
    def configure_automation(self,command:ConfigureAutomation):
        self._permit(command.tenant_id,"report.automation.manage")
        values={"automation_code":self._code(command.automation_code,"automation_code"),"trigger_code":self._code(command.trigger_code,"trigger_code"),"trigger_config":self._object(command.trigger_config,"trigger_config")}
        if command.delivery_enabled:
            if not command.delivery_kind or not command.channel_code or not command.destination_reference:raise SO9AuthorityError("SO9_DELIVERY_CONFIGURATION_REQUIRED","validation_failure","delivery-enabled automation requires kind, channel, and destination")
            values.update(delivery_kind=self._code(command.delivery_kind,"delivery_kind"),channel_code=self._code(command.channel_code,"channel_code"),destination_reference=self._text(command.destination_reference,"destination_reference"))
        else:values.update(delivery_kind=None,channel_code=None,destination_reference=None)
        normalized=replace(command,**values)
        result=self.repository.configure_automation(normalized,self.public_id_factory(),self._fingerprint(normalized))
        if result is None:raise SO9AuthorityError("SO9_AUTOMATION_CONFIGURATION_CONFLICT","conflict","The report was absent or automation configuration conflicted")
        return result
    def automation(self,tenant_id,public_id):self._permit(tenant_id,"report.view");return self.repository.automation(tenant_id,public_id)
    def list_automations(self,tenant_id,status=None):self._permit(tenant_id,"report.view");return self.repository.list_automations(tenant_id,status)
    def change_automation_status(self,command:ChangeAutomationStatus):
        self._permit(command.tenant_id,"report.automation.manage")
        result=self.repository.change_automation_status(command,self._fingerprint(command))
        if result is None:raise SO9AuthorityError("SO9_AUTOMATION_STATUS_CONFLICT","conflict","The automation rule is absent or changed concurrently")
        return result
    @staticmethod
    def _delivery_command_key(tenant_id,automation_public_id,execution_key):
        raw=f"{tenant_id}|{automation_public_id}|{execution_key}".encode()
        return "so9.auto."+hashlib.sha256(raw).hexdigest()
    def execute_automation(self,command:ExecuteAutomation):
        self._permit(command.tenant_id,"report.automation.execute");params=self._object(command.parameters,"parameters")
        normalized=replace(command,execution_key=self._text(command.execution_key,"execution_key",240),parameters=params)
        fingerprint=self._fingerprint(normalized)
        replay=self.repository.command_result(normalized.tenant_id,normalized.command_key,fingerprint,"execute_automation")
        if replay is not None:
            return self.repository.automation_run(normalized.tenant_id,replay)
        automation=self.repository.automation(normalized.tenant_id,normalized.automation_public_id)
        if not automation or automation.status is not AutomationStatus.ACTIVE:raise SO9AuthorityError("SO9_AUTOMATION_NOT_ACTIVE","conflict","The automation rule is not active")
        _,snapshot,result,sha=self._render(normalized.tenant_id,automation.report_public_id,normalized.snapshot_public_id,params)
        delivery=None
        if automation.delivery_enabled:
            if not self.delivery_handoff:raise SO9AuthorityError("SO9_DELIVERY_HANDOFF_UNAVAILABLE","dependency_unavailable","SO8 delivery handoff is unavailable",retryable=True)
            delivery_key=self._delivery_command_key(normalized.tenant_id,normalized.automation_public_id,normalized.execution_key)
            delivery=self.delivery_handoff(normalized.tenant_id,delivery_key,automation.delivery_kind,automation.channel_code,automation.destination_reference,{"report":result},normalized.occurred_at)
            if not isinstance(delivery,UUID):delivery=UUID(str(delivery))
        run=self.repository.execute_automation(normalized,self.public_id_factory(),self.public_id_factory(),fingerprint,snapshot,result,sha,delivery)
        if run is None:raise SO9AuthorityError("SO9_AUTOMATION_EXECUTION_CONFLICT","conflict","The automation execution identity or rule conflicted")
        return run
    def automation_run(self,tenant_id,public_id):self._permit(tenant_id,"report.view");return self.repository.automation_run(tenant_id,public_id)
    def automation_runs(self,tenant_id,automation_public_id):self._permit(tenant_id,"report.view");return self.repository.automation_runs(tenant_id,automation_public_id)
