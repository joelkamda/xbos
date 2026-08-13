"""SQLAlchemy persistence boundary for PC4 operating context."""
from __future__ import annotations
import json
from datetime import date,datetime,time,timedelta
from decimal import Decimal
from sqlalchemy import text
from .contracts import *
from .service import OperatingContextError

class SQLOperatingContextRepository:
    def __init__(self,session):self.session=session
    def _command(self,key,fingerprint,kind):
        self.session.execute(text("INSERT INTO operating_context_commands(command_key,request_fingerprint,command_type) VALUES(:k,:f,:t) ON CONFLICT(command_key) DO NOTHING"),{"k":key,"f":fingerprint,"t":kind})
        row=self.session.execute(text("SELECT * FROM operating_context_commands WHERE command_key=:k FOR UPDATE"),{"k":key}).one()
        if row.request_fingerprint!=fingerprint or row.command_type!=kind:raise OperatingContextError("conflicting_operating_context_command")
        return row
    def _complete(self,key,table,result_id):self.session.execute(text("UPDATE operating_context_commands SET result_table=:t,result_id=:i,completed_at=now() WHERE command_key=:k"),{"t":table,"i":result_id,"k":key})
    def definition(self,key):
        row=self.session.execute(text("SELECT * FROM configuration_definitions WHERE config_key=:k"),{"k":key}).first()
        if row is None:return None
        return DefineConfiguration("persisted",row.config_key,ConfigType(row.value_type),row.owner_code,tuple(ConfigScope(x) for x in row.allowed_scopes),tuple(ConfigScope(x) for x in row.resolution_order),row.required,row.secret,row.tenant_overridable,row.validation_constraints,row.default_value)
    def define(self,c,fingerprint):
        replay=self._command(c.command_key,fingerprint,"define_configuration")
        if replay.result_id:return self.definition(c.key)
        try:row=self.session.execute(text("""INSERT INTO configuration_definitions(config_key,value_type,owner_code,allowed_scopes,resolution_order,required,secret,tenant_overridable,validation_constraints,default_value)
          VALUES(:k,:t,:o,:scopes,:order,:required,:secret,:override,CAST(:constraints AS jsonb),CAST(:default AS jsonb)) RETURNING id"""),{"k":c.key,"t":c.value_type.value,"o":c.owner_code,"scopes":[x.value for x in c.allowed_scopes],"order":[x.value for x in c.resolution_order],"required":c.required,"secret":c.secret,"override":c.tenant_overridable,"constraints":json.dumps(c.constraints,default=str),"default":None if c.default_value is None else json.dumps(c.default_value,default=str)}).one()
        except Exception as exc:raise OperatingContextError("duplicate_or_conflicting_configuration_definition") from exc
        self._complete(c.command_key,"configuration_definitions",row.id);return self.definition(c.key)
    @staticmethod
    def _columns(kind,value):
        values={"boolean_value":None,"integer_value":None,"decimal_value":None,"string_value":None,"date_value":None,"time_value":None,"duration_seconds":None,"json_value":None}
        key={ConfigType.BOOLEAN:"boolean_value",ConfigType.INTEGER:"integer_value",ConfigType.DECIMAL:"decimal_value",ConfigType.STRING:"string_value",ConfigType.CODE:"string_value",ConfigType.DATE:"date_value",ConfigType.TIME:"time_value",ConfigType.DURATION:"duration_seconds",ConfigType.JSON:"json_value"}[kind]
        values[key]=value.total_seconds() if kind is ConfigType.DURATION else json.dumps(value,sort_keys=True) if kind is ConfigType.JSON else value
        return values
    @staticmethod
    def _value(row,kind):
        return {ConfigType.BOOLEAN:row.boolean_value,ConfigType.INTEGER:row.integer_value,ConfigType.DECIMAL:row.decimal_value,ConfigType.STRING:row.string_value,ConfigType.CODE:row.string_value,ConfigType.DATE:row.date_value,ConfigType.TIME:row.time_value,ConfigType.DURATION:timedelta(seconds=row.duration_seconds or 0),ConfigType.JSON:row.json_value}[kind]
    def set_value(self,c,fingerprint,definition):
        replay=self._command(c.command_key,fingerprint,"set_configuration")
        if replay.result_id:row=self.session.execute(text("SELECT * FROM configuration_values WHERE id=:i"),{"i":replay.result_id}).one()
        else:
            values=self._columns(definition.value_type,c.value)
            try:row=self.session.execute(text("""INSERT INTO configuration_values(definition_id,tenant_id,scope_type,scope_id,effective_from,effective_to,row_version,boolean_value,integer_value,decimal_value,string_value,date_value,time_value,duration_seconds,json_value)
             SELECT id,:tenant,:scope,:scope_id,:start,:end,1,:boolean_value,:integer_value,:decimal_value,:string_value,:date_value,:time_value,:duration_seconds,CAST(:json_value AS jsonb) FROM configuration_definitions WHERE config_key=:key RETURNING *"""),{"tenant":c.tenant_id,"scope":c.scope.value,"scope_id":c.scope_id,"start":c.effective_from,"end":c.effective_to,"key":c.key,**values}).one()
            except Exception as exc:raise OperatingContextError("overlapping_or_conflicting_configuration_value") from exc
            self._complete(c.command_key,"configuration_values",row.id)
        return ConfigurationResult(c.key,self._value(row,definition.value_type),definition.value_type,ConfigScope(row.scope_type),row.scope_id,row.effective_from,row.row_version)
    def bind_secret(self,c,fingerprint):
        replay=self._command(c.command_key,fingerprint,"bind_secret_reference")
        if not replay.result_id:
            try:row=self.session.execute(text("""INSERT INTO secret_references(definition_id,tenant_id,scope_type,scope_id,reference_key)
             SELECT id,:tenant,:scope,:scope_id,:reference FROM configuration_definitions WHERE config_key=:key AND secret=true RETURNING id"""),{"tenant":c.tenant_id,"scope":c.scope.value,"scope_id":c.scope_id,"reference":c.reference_key,"key":c.key}).one()
            except Exception as exc:raise OperatingContextError("duplicate_or_invalid_secret_reference") from exc
            self._complete(c.command_key,"secret_references",row.id)
        return {"key":c.key,"reference_key":c.reference_key,"secret_material":False}
    def resolve(self,tenant_id,key,as_of,scopes):
        definition=self.definition(key)
        if definition is None or definition.secret:raise OperatingContextError("ordinary_configuration_not_resolvable")
        for scope in definition.resolution_order:
            scope_id=scopes[scope.value]
            row=self.session.execute(text("""SELECT v.* FROM configuration_values v JOIN configuration_definitions d ON d.id=v.definition_id
             WHERE d.config_key=:key AND v.scope_type=:scope AND v.scope_id IS NOT DISTINCT FROM :scope_id
             AND v.tenant_id IS NOT DISTINCT FROM :tenant AND v.effective_from<=:at AND (v.effective_to IS NULL OR v.effective_to>:at)
             ORDER BY v.effective_from DESC"""),{"key":key,"scope":scope.value,"scope_id":scope_id,"tenant":None if scope is ConfigScope.PLATFORM else tenant_id,"at":as_of}).all()
            if len(row)>1:raise OperatingContextError("ambiguous_configuration_resolution")
            if row:return ConfigurationResult(key,self._value(row[0],definition.value_type),definition.value_type,scope,scope_id,row[0].effective_from,row[0].row_version)
        if definition.default_value is not None:return ConfigurationResult(key,definition.default_value,definition.value_type,ConfigScope.PLATFORM,None,as_of,0)
        if definition.required:raise OperatingContextError("required_configuration_missing")
        return None
    def register_module(self,c,fingerprint):
        replay=self._command(c.command_key,fingerprint,"register_module")
        if replay.result_id:return replay.result_id
        try:
            row=self.session.execute(text("INSERT INTO core_modules(module_code,owner_code,module_version,capabilities) VALUES(:m,:o,:v,:c) RETURNING id"),{"m":c.module_code,"o":c.owner_code,"v":c.version,"c":list(c.capabilities)}).one()
            for dependency in c.dependencies:self.session.execute(text("INSERT INTO core_module_dependencies(module_id,depends_on_module_id) SELECT :id,id FROM core_modules WHERE module_code=:d"),{"id":row.id,"d":dependency})
        except Exception as exc:raise OperatingContextError("duplicate_module_or_missing_dependency") from exc
        self._complete(c.command_key,"core_modules",row.id);return row.id
    def set_module_enablement(self,c,fingerprint):return self._simple_effective(c,fingerprint,"module_enablement","tenant_module_enablements","module_code",c.module_code,"enabled",c.enabled)
    def grant_entitlement(self,c,fingerprint):return self._simple_effective(c,fingerprint,"grant_entitlement","tenant_entitlements","capability_code",c.capability_code,None,None,c.effective_to)
    def set_feature_flag(self,c,fingerprint):return self._simple_effective(c,fingerprint,"set_feature_flag","feature_flags","flag_code",c.flag_code,"enabled",c.enabled,c.effective_to)
    def _simple_effective(self,c,fingerprint,kind,table,code_column,code,value_column,value,effective_to=None):
        replay=self._command(c.command_key,fingerprint,kind)
        if replay.result_id:return replay.result_id
        columns=f"tenant_id,{code_column},effective_from,effective_to"+(f",{value_column}" if value_column else "")
        params={"tenant":c.tenant_id,"code":_lower(code),"start":c.effective_from,"end":effective_to,"value":value}
        values=":tenant,:code,:start,:end"+(",:value" if value_column else "")
        try:row=self.session.execute(text(f"INSERT INTO {table}({columns}) VALUES({values}) RETURNING id"),params).one()
        except Exception as exc:raise OperatingContextError(f"duplicate_or_conflicting_{kind}") from exc
        self._complete(c.command_key,table,row.id);return row.id
    def capability_context(self,tenant,module,capability,at):
        row=self.session.execute(text("""SELECT EXISTS(SELECT 1 FROM core_modules WHERE module_code=:m AND status='available') available,
         EXISTS(SELECT 1 FROM tenant_module_enablements WHERE tenant_id=:t AND module_code=:m AND enabled=true AND effective_from<=:at AND (effective_to IS NULL OR effective_to>:at)) enabled,
         EXISTS(SELECT 1 FROM tenant_entitlements WHERE tenant_id=:t AND capability_code=:c AND effective_from<=:at AND (effective_to IS NULL OR effective_to>:at)) entitled,
         EXISTS(SELECT 1 FROM feature_flags WHERE (tenant_id=:t OR tenant_id IS NULL) AND flag_code=:c AND enabled=true AND effective_from<=:at AND (effective_to IS NULL OR effective_to>:at)) feature"""),{"t":tenant,"m":module,"c":capability,"at":at}).one()
        return CapabilityContext(row.available,row.enabled,row.entitled,row.feature,None)
    def register_calendar(self,c,fingerprint):
        replay=self._command(c.command_key,fingerprint,"register_calendar")
        if replay.result_id:return replay.result_id
        x=c.calendar
        try:
            row=self.session.execute(text("""INSERT INTO business_calendars(tenant_id,calendar_code,calendar_version,timezone_name,business_day_boundary,operating_weekdays,effective_from,effective_to)
             VALUES(:tenant,:code,:version,:zone,:boundary,:weekdays,:start,:end) RETURNING id"""),{"tenant":x.tenant_id,"code":x.calendar_code.lower(),"version":x.version,"zone":x.timezone_name,"boundary":x.business_day_boundary,"weekdays":list(x.operating_weekdays),"start":x.effective_from,"end":x.effective_to}).one()
            for e in x.exceptions:self.session.execute(text("INSERT INTO business_calendar_exceptions(business_calendar_id,calendar_date,exception_kind) VALUES(:id,:date,:kind)"),{"id":row.id,"date":e.calendar_date,"kind":e.kind.value})
            for shift in x.shifts:self.session.execute(text("INSERT INTO shift_definitions(business_calendar_id,shift_code,display_name,starts_at,ends_at) VALUES(:id,:code,:name,:start,:end)"),{"id":row.id,"code":shift.code.lower(),"name":shift.display_name,"start":shift.starts_at,"end":shift.ends_at})
        except Exception as exc:raise OperatingContextError("duplicate_overlapping_or_invalid_business_calendar") from exc
        self._complete(c.command_key,"business_calendars",row.id);return row.id
    def set_localization(self,c,fingerprint):
        replay=self._command(c.command_key,fingerprint,"set_localization")
        if replay.result_id:return replay.result_id
        p=c.profile
        try:row=self.session.execute(text("""INSERT INTO localization_profiles(tenant_id,locale_code,timezone_name,date_format,decimal_separator,currency_display,business_display_name,branding_asset_reference,terminology,effective_from)
         VALUES(:tenant,:locale,:zone,:date_format,:decimal,:currency,:name,:asset,CAST(:terms AS jsonb),:start) RETURNING id"""),{"tenant":p.tenant_id,"locale":p.locale_code,"zone":p.timezone_name,"date_format":p.date_format,"decimal":p.decimal_separator,"currency":p.currency_display,"name":p.business_display_name,"asset":p.branding_asset_reference,"terms":json.dumps(p.terminology or {},sort_keys=True),"start":c.effective_from}).one()
        except Exception as exc:raise OperatingContextError("duplicate_or_invalid_localization_profile") from exc
        self._complete(c.command_key,"localization_profiles",row.id);return row.id
    def export(self,tenant_id):
        values=[dict(r._mapping) for r in self.session.execute(text("""SELECT d.config_key,d.value_type,v.scope_type,v.scope_id,v.effective_from,v.effective_to,v.boolean_value,v.integer_value,v.decimal_value,v.string_value,v.date_value,v.time_value,v.duration_seconds,v.json_value
          FROM configuration_values v JOIN configuration_definitions d ON d.id=v.definition_id WHERE v.tenant_id=:t AND d.secret=false ORDER BY d.config_key,v.scope_type,v.scope_id,v.effective_from"""),{"t":tenant_id})]
        refs=[dict(r._mapping) for r in self.session.execute(text("SELECT d.config_key,s.scope_type,s.scope_id,s.reference_key FROM secret_references s JOIN configuration_definitions d ON d.id=s.definition_id WHERE s.tenant_id=:t ORDER BY d.config_key,s.scope_type,s.scope_id"),{"t":tenant_id})]
        return {"schema":"xbos.pc4.operating-context-export.v1","tenant_id":tenant_id,"configuration":values,"secret_references":refs,"secret_material_included":False}

def _lower(value):return str(value).strip().lower()
