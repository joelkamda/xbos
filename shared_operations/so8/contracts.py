"""Stable public contracts for SO8 communications, integration delivery, and offline synchronization."""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class DeliveryStatus(StrEnum):
    PENDING="pending"; IN_PROGRESS="in_progress"; RETRY_WAIT="retry_wait"; DELIVERED="delivered"; DEAD_LETTER="dead_letter"; CANCELLED="cancelled"
class AttemptOutcome(StrEnum):
    DELIVERED="delivered"; RETRYABLE_FAILURE="retryable_failure"; TERMINAL_FAILURE="terminal_failure"
class OfflineStatus(StrEnum):
    QUEUED="queued"; APPLIED="applied"; CONFLICT="conflict"; REJECTED="rejected"

@dataclass(frozen=True)
class DeliveryJob:
    public_id:UUID; tenant_id:int; delivery_kind:str; channel_code:str; destination_reference:str
    status:DeliveryStatus; available_at:datetime; max_attempts:int; attempt_count:int=0
    subject_authority:str|None=None; subject_reference:str|None=None; document_version_public_id:UUID|None=None
    payload:dict[str,Any]=field(default_factory=dict); payload_sha256:str=""; worker_reference:str|None=None
    lease_until:datetime|None=None; row_version:int=1

@dataclass(frozen=True)
class DeliveryAttempt:
    public_id:UUID; tenant_id:int; job_public_id:UUID; attempt_number:int; outcome:AttemptOutcome
    provider_code:str; attempted_at:datetime; provider_reference:str|None=None; error_code:str|None=None
    retry_at:datetime|None=None; response_metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class InboundDelivery:
    public_id:UUID; tenant_id:int; source_code:str; external_event_key:str; payload_sha256:str
    payload:dict[str,Any]; received_at:datetime; subject_authority:str|None=None; subject_reference:str|None=None

@dataclass(frozen=True)
class OfflineCommand:
    public_id:UUID; tenant_id:int; device_public_id:UUID; client_sequence:int; operation_code:str
    target_authority:str; target_reference:str; payload:dict[str,Any]; payload_sha256:str; captured_at:datetime
    status:OfflineStatus=OfflineStatus.QUEUED; base_version:int|None=None; server_result_reference:str|None=None
    resolution_code:str|None=None; resolved_at:datetime|None=None; row_version:int=1

@dataclass(frozen=True)
class OfflineHistory:
    public_id:UUID; tenant_id:int; offline_command_public_id:UUID; from_status:OfflineStatus|None
    to_status:OfflineStatus; reason_code:str; occurred_at:datetime; result_reference:str|None=None

@dataclass(frozen=True)
class CreateDeliveryJob:
    command_key:str; tenant_id:int; delivery_kind:str; channel_code:str; destination_reference:str
    payload:dict[str,Any]; available_at:datetime; max_attempts:int
    subject_authority:str|None=None; subject_reference:str|None=None; document_version_public_id:UUID|None=None

@dataclass(frozen=True)
class ClaimDeliveryJob:
    command_key:str; tenant_id:int; job_public_id:UUID; expected_version:int; worker_reference:str
    occurred_at:datetime; lease_until:datetime

@dataclass(frozen=True)
class RecordDeliveryAttempt:
    command_key:str; tenant_id:int; job_public_id:UUID; expected_version:int; outcome:AttemptOutcome
    provider_code:str; occurred_at:datetime; provider_reference:str|None=None; error_code:str|None=None
    retry_at:datetime|None=None; response_metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class CancelDeliveryJob:
    command_key:str; tenant_id:int; job_public_id:UUID; expected_version:int; reason_code:str; occurred_at:datetime

@dataclass(frozen=True)
class ReceiveInboundDelivery:
    command_key:str; tenant_id:int; source_code:str; external_event_key:str; payload_sha256:str
    payload:dict[str,Any]; occurred_at:datetime; subject_authority:str|None=None; subject_reference:str|None=None

@dataclass(frozen=True)
class QueueOfflineCommand:
    command_key:str; tenant_id:int; device_public_id:UUID; client_sequence:int; operation_code:str
    target_authority:str; target_reference:str; payload:dict[str,Any]; captured_at:datetime; base_version:int|None=None

@dataclass(frozen=True)
class ResolveOfflineCommand:
    command_key:str; tenant_id:int; offline_command_public_id:UUID; expected_version:int; to_status:OfflineStatus
    reason_code:str; occurred_at:datetime; server_result_reference:str|None=None
