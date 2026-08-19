from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

class TargetType(StrEnum): ATOMIC_UNIT='atomic_unit'; OFFER='offer'
class ResourceRole(StrEnum): DINING_AREA='dining_area'; TABLE='table'; COUNTER_SEAT='counter_seat'; BAR_SEAT='bar_seat'; SERVICE_STATION='service_station'; PICKUP_POINT='pickup_point'
class SessionStatus(StrEnum): OPEN='open'; CLOSED='closed'; CANCELLED='cancelled'
class OrderStatus(StrEnum): OPEN='open'; SUBMITTED='submitted'; CANCELLED='cancelled'
class TabStatus(StrEnum): OPEN='open'; CLOSED='closed'; CANCELLED='cancelled'

@dataclass(frozen=True)
class StaffAttribution:
    role_code:str; party_public_id:UUID; identity_public_id:UUID|None=None
@dataclass(frozen=True)
class ServiceMode:
    public_id:UUID; tenant_id:int; mode_code:str; display_name:str; requires_session:bool; requires_resource:bool; supports_tabs:bool; supports_reservations:bool; allows_remote_origin:bool; active:bool=True; metadata:dict[str,Any]=field(default_factory=dict); row_version:int=1
@dataclass(frozen=True)
class ResourceProfile:
    tenant_id:int; resource_public_id:UUID; role:ResourceRole; parent_resource_public_id:UUID|None=None; service_mode_codes:tuple[str,...]=(); metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class ServiceSession:
    public_id:UUID; tenant_id:int; mode_code:str; guest_count:int; status:SessionStatus; opened_at:datetime; closed_at:datetime|None=None; reservation_public_id:UUID|None=None; party_public_id:UUID|None=None; resource_public_ids:tuple[UUID,...]=(); staff:tuple[StaffAttribution,...]=(); row_version:int=1
@dataclass(frozen=True)
class OrderLine:
    public_id:UUID; tenant_id:int; order_public_id:UUID; target_type:TargetType; target_public_id:UUID; price_public_id:UUID; quantity:Decimal; unit_price_snapshot:Decimal; currency:str; note:str|None=None; row_version:int=1
    @property
    def commercial_total(self)->Decimal:return self.quantity*self.unit_price_snapshot
@dataclass(frozen=True)
class RestaurantOrder:
    public_id:UUID; tenant_id:int; order_code:str; mode_code:str; source_channel_code:str; status:OrderStatus; opened_at:datetime; submitted_at:datetime|None=None; cancelled_at:datetime|None=None; session_public_id:UUID|None=None; party_public_id:UUID|None=None; staff:tuple[StaffAttribution,...]=(); lines:tuple[OrderLine,...]=(); row_version:int=1
@dataclass(frozen=True)
class RestaurantTab:
    public_id:UUID; tenant_id:int; tab_code:str; status:TabStatus; opened_at:datetime; closed_at:datetime|None=None; session_public_id:UUID|None=None; party_public_id:UUID|None=None; order_public_ids:tuple[UUID,...]=(); partition_version:int=0; row_version:int=1
@dataclass(frozen=True)
class LineAllocation: line_public_id:UUID; quantity:Decimal
@dataclass(frozen=True)
class PartitionSpec: partition_code:str; allocations:tuple[LineAllocation,...]
@dataclass(frozen=True)
class TabPartition: public_id:UUID; tenant_id:int; tab_public_id:UUID; partition_version:int; partition_code:str; allocations:tuple[LineAllocation,...]
@dataclass(frozen=True)
class ObligationHandoffLine:
    order_line_public_id:UUID; target_type:TargetType; target_public_id:UUID; quantity:Decimal; unit_price_snapshot:Decimal; currency:str; commercial_amount:Decimal
@dataclass(frozen=True)
class ObligationHandoff:
    tenant_id:int; source_type:str; source_public_id:UUID; mode_code:str; party_public_id:UUID|None; currency:str; lines:tuple[ObligationHandoffLine,...]; commercial_total:Decimal; finance_authority:str='Neutral Finance'; creates_financial_truth:bool=False

@dataclass(frozen=True)
class DefineServiceMode:
    command_key:str; tenant_id:int; mode_code:str; display_name:str; requires_session:bool=False; requires_resource:bool=False; supports_tabs:bool=False; supports_reservations:bool=False; allows_remote_origin:bool=False; metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class ProfileResource:
    command_key:str; tenant_id:int; resource_public_id:UUID; role:ResourceRole; parent_resource_public_id:UUID|None=None; service_mode_codes:tuple[str,...]=(); metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class OpenSession:
    command_key:str; tenant_id:int; mode_code:str; guest_count:int; opened_at:datetime; reservation_public_id:UUID|None=None; party_public_id:UUID|None=None; resource_public_ids:tuple[UUID,...]=(); staff:tuple[StaffAttribution,...]=()
@dataclass(frozen=True)
class CloseSession:
    command_key:str; tenant_id:int; session_public_id:UUID; expected_version:int; occurred_at:datetime; reason_code:str='completed'
@dataclass(frozen=True)
class OpenOrder:
    command_key:str; tenant_id:int; order_code:str; mode_code:str; source_channel_code:str; opened_at:datetime; session_public_id:UUID|None=None; party_public_id:UUID|None=None; staff:tuple[StaffAttribution,...]=()
@dataclass(frozen=True)
class AddLine:
    command_key:str; tenant_id:int; order_public_id:UUID; expected_order_version:int; target_type:TargetType; target_public_id:UUID; price_public_id:UUID; quantity:Decimal; occurred_at:datetime; note:str|None=None
@dataclass(frozen=True)
class SubmitOrder:
    command_key:str; tenant_id:int; order_public_id:UUID; expected_version:int; occurred_at:datetime
@dataclass(frozen=True)
class CancelOrder:
    command_key:str; tenant_id:int; order_public_id:UUID; expected_version:int; occurred_at:datetime; reason_code:str
@dataclass(frozen=True)
class OpenTab:
    command_key:str; tenant_id:int; tab_code:str; opened_at:datetime; session_public_id:UUID|None=None; party_public_id:UUID|None=None
@dataclass(frozen=True)
class AttachOrder:
    command_key:str; tenant_id:int; tab_public_id:UUID; order_public_id:UUID; expected_tab_version:int; occurred_at:datetime
@dataclass(frozen=True)
class PartitionTab:
    command_key:str; tenant_id:int; tab_public_id:UUID; expected_tab_version:int; partitions:tuple[PartitionSpec,...]; occurred_at:datetime
@dataclass(frozen=True)
class CloseTab:
    command_key:str; tenant_id:int; tab_public_id:UUID; expected_version:int; occurred_at:datetime; reason_code:str='billing_handoff_complete'
