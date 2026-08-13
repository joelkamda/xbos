"""PC4 static validation and controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,json,os,sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date,datetime,time,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.platform.architecture_contract import validate_pc0
from core.platform.release_integrity import verify_historical_release
SOURCE="601a395";PREVIOUS="pc3_semantic_authority_023";HEAD="pc4_operating_context_024"
DEV="xbos_track_b_dev";TEST="xbos_platform_core_pc4_test";LOCAL={"localhost","127.0.0.1","::1"}
FINANCIAL=("financial_events","journal_entries","journal_lines","financial_obligations","value_sources","payment_allocations","canonical_payment_intents","payment_settlements","outbox_messages","reconciliation_controls","reconciliation_calendar_policies")

def static_verify():
    contract=json.loads((ROOT/"contracts/platform/v1/pc4_operating_context_authority.json").read_text())
    adoption=json.loads((ROOT/"contracts/platform/v1/pc4_compatibility_migration_manifest.json").read_text())
    interfaces=json.loads((ROOT/"contracts/platform/v1/pc4_public_interfaces.json").read_text())
    release=json.loads((ROOT/"contracts/platform/v1/pc4_release_manifest.json").read_text())
    if contract["scope"]!=[f"PC4.{n}" for n in range(1,15)]:raise RuntimeError("PC4 scope incomplete")
    if (contract["source_checkpoint"],contract["previous_head"],contract["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("PC4 checkpoint/lineage mismatch")
    if contract["authorities"]["permissions"]["owner"]!="PC5" or contract["authorities"]["module_registry"]["pack_lifecycle_owner"]!="PK":raise RuntimeError("PC4 external owner boundary mismatch")
    if len(adoption["entries"])<10 or not all(all(x.get(k) for k in ("canonical_owner","compatibility_path","retirement_owner","retirement_milestone")) for x in adoption["entries"]):raise RuntimeError("PC4 compatibility retirement path incomplete")
    if interfaces["module"]!="operating_context":raise RuntimeError("PC4 public interface declaration mismatch")
    version=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    if f'revision="{HEAD}"' not in version or f'down_revision="{PREVIOUS}"' not in version:raise RuntimeError("PC4 migration is not canonical child")
    up=(ROOT/"alembic_neutral/sql/pc4_operating_context_up.sql").read_text()
    if any(x in up for x in ("ALTER TABLE public.financial_","UPDATE public.financial_","DELETE FROM public.financial_","INSERT INTO public.reconciliation_calendar_policies")):raise RuntimeError("PC4 migration mutates frozen Finance")
    if "secret_material_forbidden" not in up or "does not dynamically import" not in up:raise RuntimeError("PC4 secret or composition boundary absent")
    pc3=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text()
    if "name,semantic_level,taxonomy_type,sort_order" not in pc3 or "'Child','domain','COMMERCE'" not in pc3:raise RuntimeError("accepted PC3 Revision 1 verifier repair not preserved")
    verify_historical_release(ROOT,4)
    pc0=validate_pc0(ROOT)
    return {"status":"PASS","pc0":pc0["status"],"previous_head":PREVIOUS,"accepted_head":HEAD,"compatibility_entries":len(adoption["entries"]),"release_artifacts":len(release["artifacts"]),"pc3_revision_1":"PRESERVED"}

def database_acceptance():
    from alembic import command as alembic_command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from database import engine as application_engine
    from core.platform.structure import SQLStructuralRepository,StructuralAuthority
    from core.platform.structure.contracts import ProvisionTenant
    from core.platform.operating_context import BindSecretReference,BusinessCalendarVersion,BusinessTimeResolver,ConfigScope,ConfigType,DefineConfiguration,GrantEntitlement,LocalizationProfile,OperatingContextAuthority,OperatingContextError,RegisterBusinessCalendar,RegisterModule,SetConfiguration,SetFeatureFlag,SetLocalizationProfile,SetModuleEnablement,ShiftRule,SQLOperatingContextRepository
    url=make_url(application_engine.url)
    if url.host not in LOCAL:raise RuntimeError("refusing non-local PostgreSQL target")
    if url.database!=DEV:raise RuntimeError("configured development database mismatch")
    def selected(name,auto=False):return create_engine(url.set(database=name),pool_pre_ping=True,**({"isolation_level":"AUTOCOMMIT"} if auto else {}))
    admin=selected("postgres",True)
    with admin.connect() as c:
        if c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"),{"n":TEST}).scalar_one_or_none():c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":TEST});c.exec_driver_sql(f'DROP DATABASE "{TEST}"')
        c.exec_driver_sql(f'CREATE DATABASE "{TEST}" TEMPLATE template0')
    admin.dispose()
    @contextmanager
    def target(name=TEST):
        prior=os.environ.get("DATABASE_URL");os.environ["DATABASE_URL"]=url.set(database=name).render_as_string(hide_password=False)
        try:yield
        finally:
            if prior is None:os.environ.pop("DATABASE_URL",None)
            else:os.environ["DATABASE_URL"]=prior
    config=Config(str(ROOT/"alembic.ini"));db=None;stamp=datetime(2026,8,13,tzinfo=timezone.utc)
    try:
        with target():alembic_command.upgrade(config,PREVIOUS)
        db=selected(TEST)
        with Session(db,expire_on_commit=False) as session,session.begin():context=StructuralAuthority(SQLStructuralRepository(session)).provision(ProvisionTenant("pc4-tenant","PC4","PC4 Tenant","CM","XAF","fr-CM","Africa/Douala","LE","PC4 Legal","ROOT","Root","HQ","HQ"))
        tenant=context.tenant.id
        with target():alembic_command.upgrade(config,HEAD)
        with Session(db,expire_on_commit=False) as session,session.begin():
            authority=OperatingContextAuthority(SQLOperatingContextRepository(session))
            definition=DefineConfiguration("pc4-def","ui.locale",ConfigType.CODE,"pc4",(ConfigScope.LOCATION,ConfigScope.TENANT,ConfigScope.PLATFORM),(ConfigScope.LOCATION,ConfigScope.TENANT,ConfigScope.PLATFORM),default_value="en-us")
            authority.define(definition);authority.set_value(SetConfiguration("pc4-tenant-value",tenant,"ui.locale",ConfigScope.TENANT,tenant,"fr-cm",stamp,stamp+timedelta(days=1)))
            authority.set_value(SetConfiguration("pc4-location-value",tenant,"ui.locale",ConfigScope.LOCATION,context.location.id,"fr-fr",stamp))
            if authority.resolve(tenant_id=tenant,key="ui.locale",as_of=stamp+timedelta(hours=1),location_id=context.location.id).value!="fr-fr":raise RuntimeError("hierarchical configuration resolution failed")
            authority.define(DefineConfiguration("pc4-secret-def","provider.api-key",ConfigType.STRING,"pc4",(ConfigScope.TENANT,),(ConfigScope.TENANT,),secret=True))
            authority.bind_secret(BindSecretReference("pc4-secret",tenant,"provider.api-key",ConfigScope.TENANT,tenant,"env.xafpay.api_key"))
            authority.register_module(RegisterModule("pc4-module","finance","finance","1",("reports",)))
            authority.set_module_enablement(SetModuleEnablement("pc4-module-enabled",tenant,"finance",True,stamp));authority.grant_entitlement(GrantEntitlement("pc4-entitlement",tenant,"reports",stamp));authority.set_feature_flag(SetFeatureFlag("pc4-flag",tenant,"reports",True,stamp))
            capability=authority.capability_context(tenant,"finance","reports",stamp+timedelta(hours=1))
            if not all((capability.module_available,capability.module_enabled,capability.entitled,capability.feature_active)) or capability.permission_authorized is not None:raise RuntimeError("capability dimensions collapsed")
            calendar=BusinessCalendarVersion(tenant,"operations",1,"America/New_York",time(6),tuple(range(7)),stamp-timedelta(days=1),None,(ShiftRule("ordinary","Ordinary",time(6),time(18)),ShiftRule("overnight","Overnight",time(18),time(6))))
            authority.register_calendar(RegisterBusinessCalendar("pc4-calendar",calendar));resolved=BusinessTimeResolver.resolve(calendar,datetime(2026,8,13,9,tzinfo=timezone.utc))
            if resolved.business_date!=date(2026,8,12) or resolved.shift_code!="overnight":raise RuntimeError("overnight/DST business time failed")
            authority.set_localization(SetLocalizationProfile("pc4-localization",LocalizationProfile(tenant,"fr-CM","Africa/Douala","dd/MM/yyyy",",","symbol","PC4 Tenant","so7://asset/logo",{"customer":"client"}),stamp))
            exported=authority.export(tenant)
            if exported!=authority.export(tenant) or exported["secret_material_included"] is not False or "actual-secret" in json.dumps(exported,default=str):raise RuntimeError("configuration export nondeterministic or leaked secret")
        try:
            with Session(db) as session,session.begin():OperatingContextAuthority(SQLOperatingContextRepository(session)).set_value(SetConfiguration("pc4-cross",tenant,"ui.locale",ConfigScope.TENANT,tenant+1,"en-us",stamp))
        except OperatingContextError as exc:
            if exc.code!="tenant_scope_id_mismatch":raise
        else:raise RuntimeError("cross-tenant configuration passed")
        feature_command=SetFeatureFlag("pc4-concurrent-flag",tenant,"concurrent",True,stamp)
        config_command=SetConfiguration("pc4-concurrent-config",tenant,"ui.locale",ConfigScope.TENANT,tenant,"de-de",stamp+timedelta(days=1))
        def concurrent(kind):
            with Session(db) as session,session.begin():
                authority=OperatingContextAuthority(SQLOperatingContextRepository(session))
                return authority.set_feature_flag(feature_command) if kind=="flag" else authority.set_value(config_command).version
        for kind in ("flag","configuration"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                if len(set(pool.map(lambda _:concurrent(kind),range(2))))!=1:raise RuntimeError(f"{kind} concurrent replay diverged")
        with target():alembic_command.downgrade(config,PREVIOUS);alembic_command.upgrade(config,HEAD)
        with application_engine.connect() as c:
            current=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one();tables=set(c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars());before={t:c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in FINANCIAL if t in tables}
        if current not in {PREVIOUS,HEAD}:raise RuntimeError(f"development lineage mismatch={current}")
        if current==PREVIOUS:
            with target(DEV):alembic_command.upgrade(config,HEAD)
        with application_engine.connect() as c:after_head=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one();after={t:c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in before}
        if after_head!=HEAD or after!=before:raise RuntimeError("development upgrade changed financial effects")
    except Exception:raise
    else:
        if db:db.dispose()
        admin=selected("postgres",True)
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":TEST});c.exec_driver_sql(f'DROP DATABASE "{TEST}"')
        admin.dispose()
    return {"disposable":"PASS","downgrade_reupgrade":"PASS","development_head":HEAD,"financial_effects":"UNCHANGED","cleanup":"PASS"}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance:result["database"]=database_acceptance()
    except Exception as exc:print(f"PC4_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("PC4_VERIFY=PASS");return 0
if __name__=="__main__":raise SystemExit(main())
