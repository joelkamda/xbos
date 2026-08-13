from __future__ import annotations
from dataclasses import replace
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
import json
import pytest
from core.platform.operating_context import *

ROOT=Path(__file__).resolve().parents[2]
UTC=timezone.utc
STAMP=datetime(2026,8,13,tzinfo=UTC)
UP=(ROOT/"alembic_neutral/sql/pc4_operating_context_up.sql").read_text(encoding="utf-8")
DOWN=(ROOT/"alembic_neutral/sql/pc4_operating_context_down.sql").read_text(encoding="utf-8")

class MemoryRepository:
    def __init__(self):self.commands={};self.definitions={};self.values=[];self.secrets=[];self.modules={};self.enablements={};self.entitlements=set();self.flags={};self.calendars=[];self.localizations=[]
    def _replay(self,key,fingerprint,create):
        prior=self.commands.get(key)
        if prior and prior[0]!=fingerprint:raise OperatingContextError("conflicting_operating_context_command")
        if prior:return prior[1]
        result=create();self.commands[key]=(fingerprint,result);return result
    def definition(self,key):return self.definitions.get(key)
    def define(self,c,f):
        def create():
            if c.key in self.definitions:raise OperatingContextError("duplicate_or_conflicting_configuration_definition")
            self.definitions[c.key]=c;return c
        return self._replay(c.command_key,f,create)
    def set_value(self,c,f,d):
        def create():
            for prior in self.values:
                if (prior.tenant_id,prior.key,prior.scope,prior.scope_id)==(c.tenant_id,c.key,c.scope,c.scope_id) and prior.effective_from<(c.effective_to or datetime.max.replace(tzinfo=UTC)) and c.effective_from<(prior.effective_to or datetime.max.replace(tzinfo=UTC)):raise OperatingContextError("overlapping_or_conflicting_configuration_value")
            result=ConfigurationResult(c.key,c.value,d.value_type,c.scope,c.scope_id,c.effective_from,1);self.values.append(c);return result
        return self._replay(c.command_key,f,create)
    def bind_secret(self,c,f):
        return self._replay(c.command_key,f,lambda:(self.secrets.append(c) or {"key":c.key,"reference_key":c.reference_key,"secret_material":False}))
    def resolve(self,tenant,key,as_of,scopes):
        d=self.definition(key)
        if not d or d.secret:raise OperatingContextError("ordinary_configuration_not_resolvable")
        for scope in d.resolution_order:
            candidates=[v for v in self.values if v.key==key and v.scope is scope and v.scope_id==scopes[scope.value] and v.tenant_id==(None if scope is ConfigScope.PLATFORM else tenant) and v.effective_from<=as_of and (v.effective_to is None or as_of<v.effective_to)]
            if len(candidates)>1:raise OperatingContextError("ambiguous_configuration_resolution")
            if candidates:
                v=candidates[0];return ConfigurationResult(key,v.value,d.value_type,scope,v.scope_id,v.effective_from,1)
        if d.default_value is not None:return ConfigurationResult(key,d.default_value,d.value_type,ConfigScope.PLATFORM,None,as_of,0)
        if d.required:raise OperatingContextError("required_configuration_missing")
    def register_module(self,c,f):
        def create():
            if c.module_code in self.modules:raise OperatingContextError("duplicate_module_or_missing_dependency")
            if any(d not in self.modules for d in c.dependencies):raise OperatingContextError("duplicate_module_or_missing_dependency")
            self.modules[c.module_code]=c;return c
        return self._replay(c.command_key,f,create)
    def set_module_enablement(self,c,f):return self._replay(c.command_key,f,lambda:(self.enablements.__setitem__((c.tenant_id,c.module_code),c.enabled) or c))
    def grant_entitlement(self,c,f):return self._replay(c.command_key,f,lambda:(self.entitlements.add((c.tenant_id,c.capability_code)) or c))
    def set_feature_flag(self,c,f):return self._replay(c.command_key,f,lambda:(self.flags.__setitem__((c.tenant_id,c.flag_code),c.enabled) or c))
    def capability_context(self,t,m,c,at):return CapabilityContext(m in self.modules,self.enablements.get((t,m),False),(t,c) in self.entitlements,self.flags.get((t,c),self.flags.get((None,c),False)),None)
    def register_calendar(self,c,f):return self._replay(c.command_key,f,lambda:(self.calendars.append(c.calendar) or c.calendar))
    def set_localization(self,c,f):return self._replay(c.command_key,f,lambda:(self.localizations.append(c) or c.profile))
    def export(self,tenant):return {"schema":"xbos.pc4.operating-context-export.v1","tenant_id":tenant,"configuration":[v.key for v in self.values if v.tenant_id==tenant],"secret_references":[s.reference_key for s in self.secrets if s.tenant_id==tenant],"secret_material_included":False}

def authority():return OperatingContextAuthority(MemoryRepository())
def definition(**changes):
    values=dict(command_key="def",key="ui.locale",value_type=ConfigType.CODE,owner_code="pc4",allowed_scopes=(ConfigScope.TENANT,ConfigScope.PLATFORM),resolution_order=(ConfigScope.TENANT,ConfigScope.PLATFORM),default_value="en-us")
    values.update(changes);return DefineConfiguration(**values)

def test_contract_covers_exact_pc4_scope_and_owner_boundaries():
    c=json.loads((ROOT/"contracts/platform/v1/pc4_operating_context_authority.json").read_text())
    assert c["scope"]==[f"PC4.{n}" for n in range(1,15)]
    assert c["authorities"]["permissions"]["owner"]=="PC5" and c["authorities"]["module_registry"]["pack_lifecycle_owner"]=="PK"

def test_typed_configuration_replay_validation_and_conflict():
    a=authority();d=definition();assert a.define(d)==a.define(d)
    with pytest.raises(OperatingContextError,match="conflicting_operating_context_command"):a.define(replace(d,value_type=ConfigType.INTEGER,default_value=1))
    with pytest.raises(OperatingContextError,match="invalid_code_configuration"):a.set_value(SetConfiguration("set",1,"ui.locale",ConfigScope.TENANT,1,"bad code!",STAMP))

def test_hierarchical_resolution_is_definition_specific_and_effective_dated():
    a=authority();a.define(definition())
    a.set_value(SetConfiguration("platform",None,"ui.locale",ConfigScope.PLATFORM,None,"fr-fr",STAMP-timedelta(days=2)))
    a.set_value(SetConfiguration("tenant",1,"ui.locale",ConfigScope.TENANT,1,"en-gb",STAMP-timedelta(days=1)))
    assert a.resolve(tenant_id=1,key="ui.locale",as_of=STAMP).value=="en-gb"
    assert a.resolve(tenant_id=2,key="ui.locale",as_of=STAMP).value=="fr-fr"

def test_unsupported_scope_cross_tenant_and_overlap_fail_closed():
    a=authority();a.define(definition())
    with pytest.raises(OperatingContextError,match="unsupported_configuration_scope"):a.set_value(SetConfiguration("bad-scope",1,"ui.locale",ConfigScope.LOCATION,7,"fr-fr",STAMP))
    with pytest.raises(OperatingContextError,match="tenant_scope_id_mismatch"):a.set_value(SetConfiguration("bad-tenant",1,"ui.locale",ConfigScope.TENANT,2,"fr-fr",STAMP))
    a.set_value(SetConfiguration("first",1,"ui.locale",ConfigScope.TENANT,1,"fr-fr",STAMP,STAMP+timedelta(days=2)))
    with pytest.raises(OperatingContextError,match="overlapping_or_conflicting_configuration_value"):a.set_value(SetConfiguration("overlap",1,"ui.locale",ConfigScope.TENANT,1,"en-us",STAMP+timedelta(days=1)))

def test_secrets_are_references_and_never_ordinary_values_or_exports():
    a=authority();a.define(definition(command_key="secret-def",key="provider.api-key",value_type=ConfigType.STRING,secret=True,default_value=None))
    with pytest.raises(OperatingContextError,match="secret_material_forbidden"):a.set_value(SetConfiguration("material",1,"provider.api-key",ConfigScope.TENANT,1,"actual-secret",STAMP))
    result=a.bind_secret(BindSecretReference("bind",1,"provider.api-key",ConfigScope.TENANT,1,"env.xafpay.api_key"));assert result["secret_material"] is False
    exported=a.export(1);assert exported["secret_material_included"] is False and "actual-secret" not in json.dumps(exported)

def test_availability_enablement_entitlement_flag_and_permission_are_distinct():
    a=authority();a.register_module(RegisterModule("module","finance","finance","1",("reports",)))
    a.set_module_enablement(SetModuleEnablement("enabled",1,"finance",True,STAMP));a.grant_entitlement(GrantEntitlement("entitled",1,"reports",STAMP));a.set_feature_flag(SetFeatureFlag("flag",1,"reports",True,STAMP))
    c=a.capability_context(1,"finance","reports",STAMP);assert c==CapabilityContext(True,True,True,True,None)
    assert c.permission_authorized is None

def test_module_registry_has_no_runtime_dynamic_import_authority():
    contract=json.loads((ROOT/"contracts/platform/v1/pc4_operating_context_authority.json").read_text())
    assert contract["authorities"]["module_registry"]["runtime_dynamic_import"] is False
    assert "importlib" not in (ROOT/"core/platform/operating_context").joinpath("service.py").read_text()

def calendar(zone="Africa/Douala",effective_from=STAMP-timedelta(days=10),effective_to=None,exceptions=()):
    return BusinessCalendarVersion(1,"operations",1,zone,time(8),tuple(range(7)),effective_from,effective_to,(ShiftRule("morning","Morning",time(8),time(18)),ShiftRule("overnight","Overnight",time(18),time(8))),exceptions)

def test_business_time_distinguishes_instant_local_calendar_business_date_and_overnight_shift():
    result=BusinessTimeResolver.resolve(calendar(),datetime(2026,8,13,5,tzinfo=UTC))
    assert result.local_wall_time.hour==6 and result.calendar_date==date(2026,8,13) and result.business_date==date(2026,8,12) and result.shift_code=="overnight"

def test_dst_timezone_and_exceptional_open_closed_dates_are_explicit():
    closed=calendar("America/New_York",exceptions=(CalendarExceptionRule(date(2026,8,13),CalendarException.CLOSED),))
    result=BusinessTimeResolver.resolve(closed,datetime(2026,8,13,16,tzinfo=UTC));assert result.local_wall_time.hour==12 and result.is_open is False
    opened=replace(closed,operating_weekdays=(),exceptions=(CalendarExceptionRule(date(2026,8,13),CalendarException.OPEN),));assert BusinessTimeResolver.resolve(opened,datetime(2026,8,13,16,tzinfo=UTC)).is_open

def test_effective_calendar_version_fails_outside_period():
    with pytest.raises(OperatingContextError,match="calendar_not_effective"):BusinessTimeResolver.resolve(calendar(effective_from=STAMP+timedelta(days=1)),STAMP)

def test_calendar_and_localization_registration_replay_and_asset_reference_boundary():
    a=authority();command=RegisterBusinessCalendar("calendar",calendar());assert a.register_calendar(command)==a.register_calendar(command)
    profile=LocalizationProfile(1,"fr-CM","Africa/Douala","dd/MM/yyyy",",","symbol","Tenant", "so7://asset/logo",{"customer":"client"})
    assert a.set_localization(SetLocalizationProfile("localization",profile,STAMP))==profile
    with pytest.raises(OperatingContextError,match="branding_binary_or_local_file_forbidden"):a.set_localization(SetLocalizationProfile("bad-asset",replace(profile,branding_asset_reference="data:image/png;base64,abc"),STAMP))

def test_migration_is_one_canonical_child_typed_and_schema_neutral_to_finance():
    version=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    assert 'revision="pc4_operating_context_024"' in version and 'down_revision="pc3_semantic_authority_023"' in version
    assert "num_nonnulls" in UP and "secret_material_forbidden" in UP and "secret_definition_required" in UP and "does not dynamically import" in UP
    assert not any(marker in UP for marker in ("ALTER TABLE public.financial_","UPDATE public.financial_","DELETE FROM public.financial_","INSERT INTO public.reconciliation_calendar_policies"))


def test_migration_executes_plpgsql_percent_tokens_through_dbapi_cursor():
    version=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    assert "%ROWTYPE" in UP
    assert ".connection.cursor()" in version and "cursor.execute" in version and "cursor.close()" in version
    assert "exec_driver_sql" not in version


def test_typed_configuration_trigger_parenthesizes_boolean_case_under_not():
    assert "OR NOT (CASE d.value_type" in UP
    assert "ELSE false END) THEN RAISE EXCEPTION 'typed_configuration_value_mismatch'" in UP
    assert "OR NOT CASE d.value_type" not in UP

def test_migration_downgrade_preserves_pc1_pc2_pc3_and_finance_authorities():
    for table in ("tenants","organization_units","legal_entities","locations","parties","semantic_concepts","taxonomy_nodes","financial_events","reconciliation_calendar_policies"):
        assert f"DROP TABLE IF EXISTS public.{table}" not in DOWN

def test_compatibility_manifest_has_owner_path_and_retirement_for_every_entry():
    manifest=json.loads((ROOT/"contracts/platform/v1/pc4_compatibility_migration_manifest.json").read_text())
    assert len(manifest["entries"])>=10
    assert all({"classification","canonical_owner","compatibility_path","retirement_owner","retirement_milestone"}<=set(x) for x in manifest["entries"])

def test_pc3_revision_1_taxonomy_fixture_repair_is_preserved():
    source=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text()
    assert "name,semantic_level,taxonomy_type,sort_order" in source and "'Child','domain','COMMERCE'" in source

def test_localization_and_branding_do_not_own_semantics_currency_or_files():
    c=json.loads((ROOT/"contracts/platform/v1/pc4_operating_context_authority.json").read_text())
    assert c["authorities"]["localization"]["semantic_identity_owner"]=="PC3"
    assert c["authorities"]["localization"]["financial_currency_owner"]=="Finance"
    assert "SO7 binary assets" in c["exclusions"]
