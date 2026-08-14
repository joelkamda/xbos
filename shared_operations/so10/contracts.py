"""Stable public contracts for neutral scheduling, reservations and service execution."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class SchedulableTarget(StrEnum):
    ATOMIC_UNIT="atomic_unit"; OFFER="offer"
class ServiceStatus(StrEnum):
    ACTIVE="active"; INACTIVE="inactive"; RETIRED="retired"
class AvailabilityStatus(StrEnum):
    ACTIVE="active"; INACTIVE="inactive"
class ReservationStatus(StrEnum):
    REQUESTED="requested"; CONFIRMED="confirmed"; CANCELLED="cancelled"; NO_SHOW="no_show"; COMPLETED="completed"
class ExecutionStatus(StrEnum):
    IN_PROGRESS="in_progress"; COMPLETED="completed"; ABORTED="aborted"

@dataclass(frozen=True)
class ResourceAllocationRequest:
    resource_public_id:UUID; capacity_units:int=1
@dataclass(frozen=True)
class SchedulingService:
    public_id:UUID; tenant_id:int; service_code:str; title:str; target_type:SchedulableTarget; target_public_id:UUID
    calendar_code:str; calendar_version:int; default_duration_minutes:int; max_capacity:int; status:ServiceStatus
    metadata:dict[str,Any]=field(default_factory=dict); row_version:int=1
@dataclass(frozen=True)
class AvailabilityWindow:
    public_id:UUID; tenant_id:int; service_public_id:UUID; location_public_id:UUID
    starts_at:datetime; ends_at:datetime; capacity:int; status:AvailabilityStatus; row_version:int=1
@dataclass(frozen=True)
class Reservation:
    public_id:UUID; tenant_id:int; service_public_id:UUID; party_public_id:UUID; relationship_public_id:UUID
    requested_start:datetime; requested_end:datetime; capacity_units:int; status:ReservationStatus
    confirmed_start:datetime|None=None; confirmed_end:datetime|None=None; location_public_id:UUID|None=None
    business_date:date|None=None; source_reference:str|None=None; row_version:int=1
@dataclass(frozen=True)
class ResourceAllocation:
    tenant_id:int; reservation_public_id:UUID; resource_public_id:UUID; allocation_version:int
    starts_at:datetime; ends_at:datetime; capacity_units:int
@dataclass(frozen=True)
class AvailabilityResult:
    service_public_id:UUID; location_public_id:UUID; starts_at:datetime; ends_at:datetime
    window_public_id:UUID; capacity:int; reserved_capacity:int; available_capacity:int
@dataclass(frozen=True)
class ServiceExecution:
    public_id:UUID; tenant_id:int; reservation_public_id:UUID; status:ExecutionStatus; started_at:datetime
    completed_at:datetime|None=None; result_code:str|None=None; evidence_reference:str|None=None; row_version:int=1

@dataclass(frozen=True)
class DefineSchedulingService:
    command_key:str; tenant_id:int; service_code:str; title:str; target_type:SchedulableTarget; target_public_id:UUID
    calendar_code:str; calendar_version:int; default_duration_minutes:int=60; max_capacity:int=1; metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class DefineAvailabilityWindow:
    command_key:str; tenant_id:int; service_public_id:UUID; location_public_id:UUID
    starts_at:datetime; ends_at:datetime; capacity:int; occurred_at:datetime
@dataclass(frozen=True)
class CreateReservation:
    command_key:str; tenant_id:int; service_public_id:UUID; party_public_id:UUID; relationship_public_id:UUID
    requested_start:datetime; requested_end:datetime; capacity_units:int; occurred_at:datetime; source_reference:str|None=None
@dataclass(frozen=True)
class ConfirmReservation:
    command_key:str; tenant_id:int; reservation_public_id:UUID; expected_version:int
    location_public_id:UUID; confirmed_start:datetime; confirmed_end:datetime; resource_allocations:tuple[ResourceAllocationRequest,...]
    occurred_at:datetime
@dataclass(frozen=True)
class RescheduleReservation:
    command_key:str; tenant_id:int; reservation_public_id:UUID; expected_version:int
    location_public_id:UUID; confirmed_start:datetime; confirmed_end:datetime; resource_allocations:tuple[ResourceAllocationRequest,...]
    occurred_at:datetime; reason_code:str
@dataclass(frozen=True)
class CancelReservation:
    command_key:str; tenant_id:int; reservation_public_id:UUID; expected_version:int; occurred_at:datetime; reason_code:str
@dataclass(frozen=True)
class MarkNoShow:
    command_key:str; tenant_id:int; reservation_public_id:UUID; expected_version:int; occurred_at:datetime; reason_code:str="no_show"
@dataclass(frozen=True)
class StartService:
    command_key:str; tenant_id:int; reservation_public_id:UUID; expected_reservation_version:int; occurred_at:datetime
@dataclass(frozen=True)
class CompleteService:
    command_key:str; tenant_id:int; execution_public_id:UUID; expected_version:int; occurred_at:datetime
    result_code:str; evidence_reference:str|None=None
