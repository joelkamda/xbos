"""Stable public contracts for SO9 reporting, read models, metrics, and report automation."""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class DefinitionStatus(StrEnum):
    ACTIVE="active"; ARCHIVED="archived"
class AutomationStatus(StrEnum):
    ACTIVE="active"; PAUSED="paused"; RETIRED="retired"
class MetricAggregation(StrEnum):
    COUNT="count"; SUM="sum"; AVERAGE="average"; MIN="min"; MAX="max"
class RunOutcome(StrEnum):
    SUCCEEDED="succeeded"; FAILED="failed"

@dataclass(frozen=True)
class ReadModelDefinition:
    public_id:UUID; tenant_id:int; code:str; title:str; source_authority:str; projection_code:str
    parameter_schema:dict[str,Any]=field(default_factory=dict); status:DefinitionStatus=DefinitionStatus.ACTIVE; row_version:int=1

@dataclass(frozen=True)
class ProjectionSnapshot:
    public_id:UUID; tenant_id:int; read_model_public_id:UUID; revision_number:int; as_of_at:datetime
    source_fingerprint:str; payload:dict[str,Any]; payload_sha256:str; source_watermark:str|None=None

@dataclass(frozen=True)
class MetricDefinition:
    public_id:UUID; tenant_id:int; read_model_public_id:UUID; metric_code:str; label:str
    aggregation:MetricAggregation; field_path:str|None=None; metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class ReportDefinition:
    public_id:UUID; tenant_id:int; read_model_public_id:UUID; report_code:str; title:str
    parameter_schema:dict[str,Any]=field(default_factory=dict); metric_codes:tuple[str,...]=(); status:DefinitionStatus=DefinitionStatus.ACTIVE; row_version:int=1

@dataclass(frozen=True)
class ReportRun:
    public_id:UUID; tenant_id:int; report_public_id:UUID; snapshot_public_id:UUID; parameters:dict[str,Any]
    result_payload:dict[str,Any]; result_sha256:str; generated_at:datetime; outcome:RunOutcome=RunOutcome.SUCCEEDED

@dataclass(frozen=True)
class AutomationRule:
    public_id:UUID; tenant_id:int; report_public_id:UUID; automation_code:str; trigger_code:str
    trigger_config:dict[str,Any]; status:AutomationStatus; delivery_enabled:bool=False
    delivery_kind:str|None=None; channel_code:str|None=None; destination_reference:str|None=None; row_version:int=1

@dataclass(frozen=True)
class AutomationRun:
    public_id:UUID; tenant_id:int; automation_public_id:UUID; report_run_public_id:UUID; execution_key:str
    outcome:RunOutcome; occurred_at:datetime; delivery_job_public_id:UUID|None=None

@dataclass(frozen=True)
class DefineReadModel:
    command_key:str; tenant_id:int; code:str; title:str; source_authority:str; projection_code:str
    parameter_schema:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class RefreshReadModel:
    command_key:str; tenant_id:int; read_model_public_id:UUID; source_fingerprint:str; payload:dict[str,Any]
    occurred_at:datetime; source_watermark:str|None=None

@dataclass(frozen=True)
class DefineMetric:
    command_key:str; tenant_id:int; read_model_public_id:UUID; metric_code:str; label:str
    aggregation:MetricAggregation; field_path:str|None=None; metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class DefineReport:
    command_key:str; tenant_id:int; read_model_public_id:UUID; report_code:str; title:str
    parameter_schema:dict[str,Any]=field(default_factory=dict); metric_codes:tuple[str,...]=()

@dataclass(frozen=True)
class RunReport:
    command_key:str; tenant_id:int; report_public_id:UUID; occurred_at:datetime
    parameters:dict[str,Any]=field(default_factory=dict); snapshot_public_id:UUID|None=None

@dataclass(frozen=True)
class ConfigureAutomation:
    command_key:str; tenant_id:int; report_public_id:UUID; automation_code:str; trigger_code:str
    trigger_config:dict[str,Any]; delivery_enabled:bool=False; delivery_kind:str|None=None
    channel_code:str|None=None; destination_reference:str|None=None

@dataclass(frozen=True)
class ChangeAutomationStatus:
    command_key:str; tenant_id:int; automation_public_id:UUID; expected_version:int; to_status:AutomationStatus; occurred_at:datetime

@dataclass(frozen=True)
class ExecuteAutomation:
    command_key:str; tenant_id:int; automation_public_id:UUID; execution_key:str; occurred_at:datetime
    parameters:dict[str,Any]=field(default_factory=dict); snapshot_public_id:UUID|None=None
