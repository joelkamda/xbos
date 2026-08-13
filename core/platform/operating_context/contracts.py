"""Immutable PC4 command/result contracts."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime,time
from decimal import Decimal
from enum import StrEnum
from typing import Any

class ConfigType(StrEnum):
    BOOLEAN="boolean";INTEGER="integer";DECIMAL="decimal";STRING="string";CODE="code";DATE="date";TIME="time";DURATION="duration";JSON="json"
class ConfigScope(StrEnum):
    PLATFORM="platform";TENANT="tenant";LEGAL_ENTITY="legal_entity";ORGANIZATION_UNIT="organization_unit";LOCATION="location"
class Lifecycle(StrEnum):ACTIVE="active";DEPRECATED="deprecated";RETIRED="retired"
class ModuleStatus(StrEnum):AVAILABLE="available";DEPRECATED="deprecated";RETIRED="retired"
class CalendarException(StrEnum):OPEN="open";CLOSED="closed"

@dataclass(frozen=True)
class DefineConfiguration:
    command_key:str;key:str;value_type:ConfigType;owner_code:str;allowed_scopes:tuple[ConfigScope,...];resolution_order:tuple[ConfigScope,...];required:bool=False;secret:bool=False;tenant_overridable:bool=True;constraints:dict[str,Any]|None=None;default_value:Any=None
@dataclass(frozen=True)
class SetConfiguration:
    command_key:str;tenant_id:int|None;key:str;scope:ConfigScope;scope_id:int|None;value:Any;effective_from:datetime;effective_to:datetime|None=None;expected_version:int|None=None
@dataclass(frozen=True)
class BindSecretReference:
    command_key:str;tenant_id:int|None;key:str;scope:ConfigScope;scope_id:int|None;reference_key:str
@dataclass(frozen=True)
class ConfigurationResult:
    key:str;value:Any;value_type:ConfigType;scope:ConfigScope;scope_id:int|None;effective_from:datetime;version:int

@dataclass(frozen=True)
class RegisterModule:
    command_key:str;module_code:str;owner_code:str;version:str;capabilities:tuple[str,...]=();dependencies:tuple[str,...]=()
@dataclass(frozen=True)
class SetModuleEnablement:
    command_key:str;tenant_id:int;module_code:str;enabled:bool;effective_from:datetime
@dataclass(frozen=True)
class GrantEntitlement:
    command_key:str;tenant_id:int;capability_code:str;effective_from:datetime;effective_to:datetime|None=None
@dataclass(frozen=True)
class SetFeatureFlag:
    command_key:str;tenant_id:int|None;flag_code:str;enabled:bool;effective_from:datetime;effective_to:datetime|None=None;expected_version:int|None=None
@dataclass(frozen=True)
class CapabilityContext:
    module_available:bool;module_enabled:bool;entitled:bool;feature_active:bool;permission_authorized:None=None

@dataclass(frozen=True)
class ShiftRule:
    code:str;display_name:str;starts_at:time;ends_at:time
    @property
    def overnight(self)->bool:return self.ends_at<=self.starts_at
@dataclass(frozen=True)
class CalendarExceptionRule:
    calendar_date:date;kind:CalendarException
@dataclass(frozen=True)
class BusinessCalendarVersion:
    tenant_id:int;calendar_code:str;version:int;timezone_name:str;business_day_boundary:time;operating_weekdays:tuple[int,...];effective_from:datetime;effective_to:datetime|None;shifts:tuple[ShiftRule,...];exceptions:tuple[CalendarExceptionRule,...]=()
@dataclass(frozen=True)
class BusinessTimeContext:
    instant_utc:datetime;local_wall_time:datetime;timezone_name:str;calendar_date:date;business_date:date;shift_code:str|None;calendar_code:str;calendar_version:int;is_open:bool
@dataclass(frozen=True)
class RegisterBusinessCalendar:
    command_key:str;calendar:BusinessCalendarVersion
@dataclass(frozen=True)
class LocalizationProfile:
    tenant_id:int;locale_code:str;timezone_name:str;date_format:str;decimal_separator:str;currency_display:str;business_display_name:str|None=None;branding_asset_reference:str|None=None;terminology:dict[str,str]|None=None
@dataclass(frozen=True)
class SetLocalizationProfile:
    command_key:str;profile:LocalizationProfile;effective_from:datetime
