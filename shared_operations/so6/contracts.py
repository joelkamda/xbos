"""Stable public contracts for neutral workflows, tasks, and operational approvals."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class WorkflowStatus(StrEnum):
    OPEN="open"; COMPLETED="completed"; CANCELLED="cancelled"
class TaskStatus(StrEnum):
    PENDING="pending"; IN_PROGRESS="in_progress"; COMPLETED="completed"; CANCELLED="cancelled"
class ApprovalStatus(StrEnum):
    PENDING="pending"; APPROVED="approved"; REJECTED="rejected"; CANCELLED="cancelled"
class Priority(StrEnum):
    LOW="low"; NORMAL="normal"; HIGH="high"; URGENT="urgent"

@dataclass(frozen=True)
class Workflow:
    public_id:UUID; tenant_id:int; workflow_type_code:str; title:str; status:WorkflowStatus; priority:Priority
    subject_authority:str; subject_reference:str; due_at:datetime|None
    organization_unit_public_id:UUID|None=None; location_public_id:UUID|None=None
    metadata:dict[str,Any]=field(default_factory=dict); row_version:int=1

@dataclass(frozen=True)
class WorkflowTask:
    public_id:UUID; tenant_id:int; workflow_public_id:UUID; task_type_code:str; title:str; status:TaskStatus; priority:Priority
    due_at:datetime|None; assignee_resource_public_id:UUID|None=None; required_capability_code:str|None=None
    metadata:dict[str,Any]=field(default_factory=dict); row_version:int=1

@dataclass(frozen=True)
class OperationalApproval:
    public_id:UUID; tenant_id:int; workflow_public_id:UUID; approval_type_code:str; status:ApprovalStatus
    task_public_id:UUID|None=None; approver_resource_public_id:UUID|None=None; due_at:datetime|None=None
    evidence_reference:str|None=None; decision_note:str|None=None; row_version:int=1

@dataclass(frozen=True)
class CreateWorkflow:
    command_key:str; tenant_id:int; workflow_type_code:str; title:str; subject_authority:str; subject_reference:str
    organization_unit_public_id:UUID|None=None; location_public_id:UUID|None=None
    priority:Priority=Priority.NORMAL; due_at:datetime|None=None; metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class AddTask:
    command_key:str; tenant_id:int; workflow_public_id:UUID; expected_workflow_version:int; task_type_code:str; title:str
    assignee_resource_public_id:UUID|None=None; required_capability_code:str|None=None
    priority:Priority=Priority.NORMAL; due_at:datetime|None=None; metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class ChangeTaskStatus:
    command_key:str; tenant_id:int; task_public_id:UUID; expected_version:int; to_status:TaskStatus; reason_code:str; occurred_at:datetime

@dataclass(frozen=True)
class ReassignTask:
    command_key:str; tenant_id:int; task_public_id:UUID; expected_version:int; assignee_resource_public_id:UUID|None; reason_code:str; occurred_at:datetime

@dataclass(frozen=True)
class RequestOperationalApproval:
    command_key:str; tenant_id:int; workflow_public_id:UUID; expected_workflow_version:int; approval_type_code:str
    task_public_id:UUID|None=None; approver_resource_public_id:UUID|None=None; due_at:datetime|None=None; evidence_reference:str|None=None

@dataclass(frozen=True)
class DecideOperationalApproval:
    command_key:str; tenant_id:int; approval_public_id:UUID; expected_version:int; decision:ApprovalStatus
    reason_code:str; occurred_at:datetime; decision_note:str|None=None

@dataclass(frozen=True)
class CompleteWorkflow:
    command_key:str; tenant_id:int; workflow_public_id:UUID; expected_version:int; reason_code:str; occurred_at:datetime

@dataclass(frozen=True)
class CancelWorkflow:
    command_key:str; tenant_id:int; workflow_public_id:UUID; expected_version:int; reason_code:str; occurred_at:datetime
