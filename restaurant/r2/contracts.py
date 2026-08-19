from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

class TargetType(StrEnum): ATOMIC_UNIT='atomic_unit'; OFFER='offer'
class SelectionMode(StrEnum): SINGLE='single'; MULTIPLE='multiple'; QUANTITY='quantity'
class ModifierEffect(StrEnum): ADD='add'; REMOVE='remove'; REPLACE='replace'; INSTRUCTION='instruction'
class StationKind(StrEnum): KITCHEN='kitchen'; BAR='bar'; EXPO='expo'; PASTRY='pastry'; PREP='prep'; BEVERAGE='beverage'; PICKUP='pickup'; OTHER='other'
class TicketStatus(StrEnum): HELD='held'; QUEUED='queued'; IN_PROGRESS='in_progress'; PARTIALLY_READY='partially_ready'; READY='ready'; COMPLETED='completed'; VOIDED='voided'
class TicketItemStatus(StrEnum): HELD='held'; QUEUED='queued'; IN_PROGRESS='in_progress'; READY='ready'; COMPLETED='completed'; VOIDED='voided'
class PrepRunStatus(StrEnum): IN_PROGRESS='in_progress'; COMPLETED='completed'; VOIDED='voided'

@dataclass(frozen=True)
class MenuSection:
    public_id:UUID;tenant_id:int;catalog_public_id:UUID;section_code:str;display_name:str;sort_order:int;effective_from:datetime;effective_to:datetime|None;active:bool=True;metadata:dict[str,Any]=field(default_factory=dict);row_version:int=1
@dataclass(frozen=True)
class MenuSectionEntry:
    tenant_id:int;section_public_id:UUID;catalog_entry_public_id:UUID;sort_order:int;effective_from:datetime;effective_to:datetime|None
@dataclass(frozen=True)
class MenuEntryModifierBinding:
    tenant_id:int;catalog_entry_public_id:UUID;modifier_group_public_id:UUID;sequence:int;effective_from:datetime;effective_to:datetime|None
@dataclass(frozen=True)
class ModifierGroup:
    public_id:UUID;tenant_id:int;group_code:str;display_name:str;selection_mode:SelectionMode;minimum_selections:int;maximum_selections:int;effective_from:datetime;effective_to:datetime|None;active:bool=True;metadata:dict[str,Any]=field(default_factory=dict);row_version:int=1
@dataclass(frozen=True)
class ModifierOption:
    public_id:UUID;tenant_id:int;group_public_id:UUID;option_code:str;display_name:str;effect_type:ModifierEffect;target_type:TargetType|None;target_public_id:UUID|None;price_public_id:UUID|None;default_quantity:Decimal;preparation_instruction:str|None;active:bool=True;sort_order:int=0;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class ModifierSelection:
    group_public_id:UUID;option_public_id:UUID;quantity:Decimal=Decimal('1');price_amount_snapshot:Decimal=Decimal('0');currency:str|None=None;instruction_snapshot:str|None=None
@dataclass(frozen=True)
class ModifierSelectionSet:
    public_id:UUID;tenant_id:int;order_line_public_id:UUID;selection_version:int;selections:tuple[ModifierSelection,...];created_at:datetime
@dataclass(frozen=True)
class StationProfile:
    public_id:UUID;tenant_id:int;resource_public_id:UUID;station_code:str;display_name:str;station_kind:StationKind;output_channel_code:str|None=None;destination_reference:str|None=None;active:bool=True;metadata:dict[str,Any]=field(default_factory=dict);row_version:int=1
@dataclass(frozen=True)
class RoutingRule:
    public_id:UUID;tenant_id:int;rule_code:str;station_resource_public_id:UUID;target_type:TargetType|None;target_public_id:UUID|None;semantic_reference:str|None;service_mode_code:str|None;source_channel_code:str|None;course_code:str|None;priority:int;effective_from:datetime;effective_to:datetime|None;active:bool=True;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class PreparationComponent:
    component_type:str;atomic_unit_public_id:UUID|None=None;dependency_spec_public_id:UUID|None=None;required_stock_units:int=1;sequence:int=0;optional:bool=False;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class PreparationSpec:
    public_id:UUID;tenant_id:int;spec_code:str;spec_version:int;display_name:str;output_atomic_unit_public_id:UUID;yield_stock_units:int;effective_from:datetime;effective_to:datetime|None;components:tuple[PreparationComponent,...];lifecycle_status:str='active';metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class PreparationTicketItem:
    public_id:UUID;tenant_id:int;ticket_public_id:UUID;order_line_public_id:UUID;quantity:Decimal;status:TicketItemStatus;modifier_set_public_id:UUID|None=None;preparation_note:str|None=None;modifier_snapshot:tuple[dict[str,Any],...]=();row_version:int=1
@dataclass(frozen=True)
class PreparationTicket:
    public_id:UUID;tenant_id:int;order_public_id:UUID;station_resource_public_id:UUID;ticket_code:str;status:TicketStatus;course_code:str|None;priority:int;held:bool;released_at:datetime;fired_at:datetime|None=None;completed_at:datetime|None=None;items:tuple[PreparationTicketItem,...]=();row_version:int=1
@dataclass(frozen=True)
class PreparationRunInput:
    atomic_unit_public_id:UUID;planned_stock_units:int;consumed_stock_units:int|None=None;waste_stock_units:int|None=None
@dataclass(frozen=True)
class PreparationRun:
    public_id:UUID;tenant_id:int;preparation_spec_public_id:UUID;ticket_item_public_id:UUID|None;status:PrepRunStatus;planned_output_units:int;actual_output_units:int|None;waste_output_units:int|None;started_at:datetime;completed_at:datetime|None;inputs:tuple[PreparationRunInput,...];row_version:int=1
@dataclass(frozen=True)
class StockIntent:
    atomic_unit_public_id:UUID;movement_kind:str;quantity_units:int;reason_code:str;source_reference:str
@dataclass(frozen=True)
class InventoryHandoff:
    tenant_id:int;preparation_run_public_id:UUID;intents:tuple[StockIntent,...];authority:str='SO3';creates_inventory_truth:bool=False
@dataclass(frozen=True)
class DeliveryHandoff:
    tenant_id:int;ticket_public_id:UUID;delivery_kind:str;channel_code:str;destination_reference:str;payload:dict[str,Any];authority:str='SO8';creates_delivery_job:bool=False

@dataclass(frozen=True)
class DefineMenuSection:
    command_key:str;tenant_id:int;catalog_public_id:UUID;section_code:str;display_name:str;effective_from:datetime;effective_to:datetime|None=None;sort_order:int=0;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class PlaceMenuEntry:
    command_key:str;tenant_id:int;section_public_id:UUID;catalog_entry_public_id:UUID;effective_from:datetime;effective_to:datetime|None=None;sort_order:int=0
@dataclass(frozen=True)
class BindMenuEntryModifierGroup:
    command_key:str;tenant_id:int;catalog_entry_public_id:UUID;modifier_group_public_id:UUID;effective_from:datetime;effective_to:datetime|None=None;sequence:int=0
@dataclass(frozen=True)
class DefineModifierGroup:
    command_key:str;tenant_id:int;group_code:str;display_name:str;selection_mode:SelectionMode;minimum_selections:int;maximum_selections:int;effective_from:datetime;effective_to:datetime|None=None;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class AddModifierOption:
    command_key:str;tenant_id:int;group_public_id:UUID;option_code:str;display_name:str;effect_type:ModifierEffect;target_type:TargetType|None=None;target_public_id:UUID|None=None;price_public_id:UUID|None=None;default_quantity:Decimal=Decimal('1');preparation_instruction:str|None=None;sort_order:int=0;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class SetLineModifiers:
    command_key:str;tenant_id:int;order_line_public_id:UUID;selections:tuple[ModifierSelection,...];occurred_at:datetime;created_by_party_public_id:UUID|None=None
@dataclass(frozen=True)
class ProfileStation:
    command_key:str;tenant_id:int;resource_public_id:UUID;station_code:str;display_name:str;station_kind:StationKind;output_channel_code:str|None=None;destination_reference:str|None=None;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class DefineRoutingRule:
    command_key:str;tenant_id:int;rule_code:str;station_resource_public_id:UUID;effective_from:datetime;target_type:TargetType|None=None;target_public_id:UUID|None=None;semantic_reference:str|None=None;service_mode_code:str|None=None;source_channel_code:str|None=None;course_code:str|None=None;priority:int=100;effective_to:datetime|None=None;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class DefinePreparationSpec:
    command_key:str;tenant_id:int;spec_code:str;spec_version:int;display_name:str;output_atomic_unit_public_id:UUID;yield_stock_units:int;effective_from:datetime;components:tuple[PreparationComponent,...];effective_to:datetime|None=None;metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class ReleasePreparation:
    command_key:str;tenant_id:int;order_public_id:UUID;occurred_at:datetime;hold:bool=False;course_code:str|None=None;line_public_ids:tuple[UUID,...]=()
@dataclass(frozen=True)
class FireTicket:
    command_key:str;tenant_id:int;ticket_public_id:UUID;expected_version:int;occurred_at:datetime;reason_code:str='fire'
@dataclass(frozen=True)
class AdvanceTicketItem:
    command_key:str;tenant_id:int;ticket_item_public_id:UUID;expected_version:int;to_status:TicketItemStatus;occurred_at:datetime;reason_code:str
@dataclass(frozen=True)
class CompleteTicket:
    command_key:str;tenant_id:int;ticket_public_id:UUID;expected_version:int;occurred_at:datetime;reason_code:str='completed'
@dataclass(frozen=True)
class StartPreparationRun:
    command_key:str;tenant_id:int;preparation_spec_public_id:UUID;planned_output_units:int;started_at:datetime;ticket_item_public_id:UUID|None=None
@dataclass(frozen=True)
class CompletePreparationRun:
    command_key:str;tenant_id:int;preparation_run_public_id:UUID;expected_version:int;actual_output_units:int;waste_output_units:int;inputs:tuple[PreparationRunInput,...];occurred_at:datetime;reason_code:str='completed'
