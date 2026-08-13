"""PC4 validation, deterministic resolution, and prospective business time."""
from __future__ import annotations
import hashlib,json,re
from dataclasses import asdict,is_dataclass
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from .contracts import *

class OperatingContextError(ValueError):
    def __init__(self,code):super().__init__(code);self.code=code

def _fingerprint(value)->str:
    def default(v):
        if isinstance(v,(date,datetime,time)):return v.isoformat()
        if isinstance(v,Decimal):return str(v)
        if hasattr(v,"value"):return v.value
        if is_dataclass(v):return asdict(v)
        raise TypeError(type(v).__name__)
    return hashlib.sha256(json.dumps(value,default=default,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
def _token(value,name):
    selected=str(value).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,119}",selected):raise OperatingContextError(f"invalid_{name}")
    return selected
def _aware(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:raise OperatingContextError("timezone_required")
    return value.astimezone(timezone.utc)

class OperatingContextAuthority:
    def __init__(self,repository):self.repository=repository
    def define(self,c:DefineConfiguration):
        key=_token(c.key,"configuration_key");owner=_token(c.owner_code,"owner")
        if not c.allowed_scopes or len(set(c.allowed_scopes))!=len(c.allowed_scopes):raise OperatingContextError("invalid_allowed_scopes")
        if set(c.resolution_order)!=set(c.allowed_scopes):raise OperatingContextError("resolution_order_must_exactly_cover_scopes")
        if c.secret and c.default_value is not None:raise OperatingContextError("secret_default_forbidden")
        normalized=DefineConfiguration(c.command_key,key,c.value_type,owner,c.allowed_scopes,c.resolution_order,c.required,c.secret,c.tenant_overridable,c.constraints or {},self._typed(c.value_type,c.default_value,c.constraints or {}) if c.default_value is not None else None)
        return self.repository.define(normalized,_fingerprint(normalized))
    def set_value(self,c:SetConfiguration):
        start=_aware(c.effective_from);end=_aware(c.effective_to) if c.effective_to else None
        if end and end<=start:raise OperatingContextError("invalid_effective_period")
        definition=self.repository.definition(_token(c.key,"configuration_key"))
        if definition is None:raise OperatingContextError("configuration_definition_not_found")
        if definition.secret:raise OperatingContextError("secret_material_forbidden")
        if c.scope not in definition.allowed_scopes:raise OperatingContextError("unsupported_configuration_scope")
        self._scope(c.tenant_id,c.scope,c.scope_id)
        normalized=SetConfiguration(c.command_key,c.tenant_id,definition.key,c.scope,c.scope_id,self._typed(definition.value_type,c.value,definition.constraints),start,end,c.expected_version)
        return self.repository.set_value(normalized,_fingerprint(normalized),definition)
    def bind_secret(self,c:BindSecretReference):
        definition=self.repository.definition(_token(c.key,"configuration_key"))
        if definition is None or not definition.secret:raise OperatingContextError("secret_definition_required")
        if c.scope not in definition.allowed_scopes:raise OperatingContextError("unsupported_configuration_scope")
        self._scope(c.tenant_id,c.scope,c.scope_id)
        reference=_token(c.reference_key,"secret_reference")
        if any(marker in reference for marker in ("password","token=","secret=")):raise OperatingContextError("secret_reference_not_material")
        normalized=BindSecretReference(c.command_key,c.tenant_id,definition.key,c.scope,c.scope_id,reference)
        return self.repository.bind_secret(normalized,_fingerprint(normalized))
    def resolve(self,*,tenant_id,key,as_of,legal_entity_id=None,organization_unit_id=None,location_id=None):
        return self.repository.resolve(tenant_id,_token(key,"configuration_key"),_aware(as_of),{"tenant":tenant_id,"legal_entity":legal_entity_id,"organization_unit":organization_unit_id,"location":location_id,"platform":None})
    def register_module(self,c:RegisterModule):
        normalized=RegisterModule(c.command_key,_token(c.module_code,"module_code"),_token(c.owner_code,"owner"),str(c.version).strip(),tuple(sorted({_token(x,"capability") for x in c.capabilities})),tuple(sorted({_token(x,"module_code") for x in c.dependencies})))
        if normalized.module_code in normalized.dependencies:raise OperatingContextError("module_self_dependency")
        return self.repository.register_module(normalized,_fingerprint(normalized))
    def set_module_enablement(self,c:SetModuleEnablement):
        normalized=SetModuleEnablement(c.command_key,c.tenant_id,_token(c.module_code,"module_code"),c.enabled,_aware(c.effective_from))
        return self.repository.set_module_enablement(normalized,_fingerprint(normalized))
    def grant_entitlement(self,c:GrantEntitlement):
        normalized=GrantEntitlement(c.command_key,c.tenant_id,_token(c.capability_code,"capability"),_aware(c.effective_from),_aware(c.effective_to) if c.effective_to else None)
        if normalized.effective_to and normalized.effective_to<=normalized.effective_from:raise OperatingContextError("invalid_entitlement_period")
        return self.repository.grant_entitlement(normalized,_fingerprint(normalized))
    def set_feature_flag(self,c:SetFeatureFlag):
        normalized=SetFeatureFlag(c.command_key,c.tenant_id,_token(c.flag_code,"feature_flag"),c.enabled,_aware(c.effective_from),_aware(c.effective_to) if c.effective_to else None,c.expected_version)
        if normalized.effective_to and normalized.effective_to<=normalized.effective_from:raise OperatingContextError("invalid_feature_flag_period")
        return self.repository.set_feature_flag(normalized,_fingerprint(normalized))
    def capability_context(self,tenant_id,module_code,capability_code,as_of):return self.repository.capability_context(tenant_id,_token(module_code,"module_code"),_token(capability_code,"capability"),_aware(as_of))
    def register_calendar(self,c:RegisterBusinessCalendar):
        item=c.calendar
        _token(item.calendar_code,"calendar_code");_aware(item.effective_from)
        if item.effective_to:_aware(item.effective_to)
        try:ZoneInfo(item.timezone_name)
        except ZoneInfoNotFoundError as exc:raise OperatingContextError("invalid_timezone") from exc
        if len(set(item.operating_weekdays))!=len(item.operating_weekdays) or any(x not in range(7) for x in item.operating_weekdays):raise OperatingContextError("invalid_operating_weekdays")
        if not item.shifts or len({x.code for x in item.shifts})!=len(item.shifts) or any(x.starts_at==x.ends_at for x in item.shifts):raise OperatingContextError("invalid_shift_definitions")
        return self.repository.register_calendar(c,_fingerprint(c))
    def set_localization(self,c:SetLocalizationProfile):
        try:ZoneInfo(c.profile.timezone_name)
        except ZoneInfoNotFoundError as exc:raise OperatingContextError("invalid_timezone") from exc
        if c.profile.branding_asset_reference and c.profile.branding_asset_reference.startswith(("data:","file:")):raise OperatingContextError("branding_binary_or_local_file_forbidden")
        normalized=SetLocalizationProfile(c.command_key,c.profile,_aware(c.effective_from))
        return self.repository.set_localization(normalized,_fingerprint(normalized))
    def export(self,tenant_id):return self.repository.export(tenant_id)
    @staticmethod
    def _scope(tenant_id,scope,scope_id):
        if scope is ConfigScope.PLATFORM:
            if tenant_id is not None or scope_id is not None:raise OperatingContextError("invalid_platform_scope")
        elif tenant_id is None:raise OperatingContextError("tenant_scope_required")
        elif scope is ConfigScope.TENANT and scope_id!=tenant_id:raise OperatingContextError("tenant_scope_id_mismatch")
        elif scope is not ConfigScope.TENANT and scope_id is None:raise OperatingContextError("structural_scope_id_required")
    @staticmethod
    def _typed(kind,value,constraints):
        if kind is ConfigType.BOOLEAN:
            if type(value) is not bool:raise OperatingContextError("invalid_boolean_configuration")
            return value
        if kind is ConfigType.INTEGER:
            if type(value) is not int:raise OperatingContextError("invalid_integer_configuration")
        elif kind is ConfigType.DECIMAL:
            try:value=Decimal(str(value))
            except (InvalidOperation,ValueError):raise OperatingContextError("invalid_decimal_configuration")
        elif kind in (ConfigType.STRING,ConfigType.CODE):
            if not isinstance(value,str) or not value.strip():raise OperatingContextError("invalid_string_configuration")
            value=value.strip() if kind is ConfigType.STRING else _token(value,"code_configuration")
        elif kind is ConfigType.DATE:
            if type(value) is not date:raise OperatingContextError("invalid_date_configuration")
        elif kind is ConfigType.TIME:
            if type(value) is not time:raise OperatingContextError("invalid_time_configuration")
        elif kind is ConfigType.DURATION:
            if not isinstance(value,timedelta) or value.total_seconds()<0:raise OperatingContextError("invalid_duration_configuration")
        elif kind is ConfigType.JSON:
            if not isinstance(value,(dict,list)):raise OperatingContextError("invalid_structured_configuration")
        if "enum" in constraints and value not in constraints["enum"]:raise OperatingContextError("configuration_not_in_enum")
        if "minimum" in constraints and value<constraints["minimum"]:raise OperatingContextError("configuration_below_minimum")
        if "maximum" in constraints and value>constraints["maximum"]:raise OperatingContextError("configuration_above_maximum")
        return value

class BusinessTimeResolver:
    @staticmethod
    def resolve(calendar:BusinessCalendarVersion,instant:datetime)->BusinessTimeContext:
        instant=_aware(instant)
        try:zone=ZoneInfo(calendar.timezone_name)
        except ZoneInfoNotFoundError as exc:raise OperatingContextError("invalid_timezone") from exc
        if not calendar.effective_from<=instant or calendar.effective_to and instant>=calendar.effective_to:raise OperatingContextError("calendar_not_effective")
        local=instant.astimezone(zone);business_date=local.date() if local.timetz().replace(tzinfo=None)>=calendar.business_day_boundary else local.date()-timedelta(days=1)
        override=next((x.kind for x in calendar.exceptions if x.calendar_date==business_date),None)
        is_open=override is CalendarException.OPEN or (override is None and business_date.weekday() in calendar.operating_weekdays)
        shift=None
        wall=local.timetz().replace(tzinfo=None)
        for item in calendar.shifts:
            if (not item.overnight and item.starts_at<=wall<item.ends_at) or (item.overnight and (wall>=item.starts_at or wall<item.ends_at)):shift=item.code;break
        return BusinessTimeContext(instant,local,calendar.timezone_name,local.date(),business_date,shift,calendar.calendar_code,calendar.version,is_open)
