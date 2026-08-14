"""Stable public contracts for neutral operational resources and assignments."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

class ResourceKind(StrEnum):
    PERSON="person"; NON_PERSON="non_person"
class ResourceStatus(StrEnum):
    ACTIVE="active"; INACTIVE="inactive"; UNAVAILABLE="unavailable"; RETIRED="retired"
class AssignmentStatus(StrEnum):
    ACTIVE="active"; ENDED="ended"; CANCELLED="cancelled"

@dataclass(frozen=True)
class Resource:
    public_id:UUID; tenant_id:int; resource_kind:ResourceKind; classification_code:str
    display_label:str; status:ResourceStatus; capacity:int; exclusive_assignment:bool
    party_public_id:UUID|None=None; identity_public_id:UUID|None=None
    organization_unit_public_id:UUID|None=None; location_public_id:UUID|None=None
    metadata:dict[str,Any]=field(default_factory=dict); row_version:int=1

@dataclass(frozen=True)
class OperationalAssignment:
    public_id:UUID; tenant_id:int; resource_public_id:UUID; capability_code:str
    status:AssignmentStatus; effective_from:datetime; effective_to:datetime|None
    organization_unit_public_id:UUID|None=None; location_public_id:UUID|None=None
    source_reference:str|None=None; row_version:int=1

@dataclass(frozen=True)
class CreateResource:
    command_key:str; tenant_id:int; resource_kind:ResourceKind; classification_code:str; display_label:str
    party_public_id:UUID|None=None; identity_public_id:UUID|None=None
    organization_unit_public_id:UUID|None=None; location_public_id:UUID|None=None
    capacity:int=1; exclusive_assignment:bool=False; metadata:dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class ChangeResourceStatus:
    command_key:str; tenant_id:int; resource_public_id:UUID; expected_version:int
    to_status:ResourceStatus; reason_code:str; occurred_at:datetime

@dataclass(frozen=True)
class AssignResource:
    command_key:str; tenant_id:int; resource_public_id:UUID; expected_resource_version:int
    capability_code:str; effective_from:datetime; effective_to:datetime|None=None
    organization_unit_public_id:UUID|None=None; location_public_id:UUID|None=None; source_reference:str|None=None

@dataclass(frozen=True)
class EndAssignment:
    command_key:str; tenant_id:int; assignment_public_id:UUID; expected_version:int
    ended_at:datetime; reason_code:str
