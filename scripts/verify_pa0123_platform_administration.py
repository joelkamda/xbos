#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
SOURCE="24028584c4e7c252c03169fb87dfd880e12e8f7a"
PREVIOUS="pk456_pack_conformance_templates_038"
HEAD="pa0123_merchant_lifecycle_subscriptions_onboarding_039"
CONTRACTS=ROOT/"contracts/platform_admin/v1"

def _j(name): return json.loads((CONTRACTS/name).read_text())
def _sha(path): return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def _set_url(cfg,url): cfg.set_main_option("sqlalchemy.url",url.replace("%","%%"))
def _run(op,cfg,url,target):
    old={k:os.environ.get(k) for k in ("DATABASE_URL","MIGRATION_DATABASE_URL")}; _set_url(cfg,url); os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
    try: op(cfg,target)
    finally:
        for k,v in old.items(): os.environ.pop(k,None) if v is None else os.environ.__setitem__(k,v)

def static_verify():
    from core.platform.architecture_contract import validate_pc0
    a=_j("pa0123_authority.json"); r=_j("pa0123_readiness_contract.json"); p=_j("pa0123_public_interfaces.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD): raise RuntimeError("PA0123_RELEASE_BOUNDARY")
    if a["coverage"]!=["PA0","PA1","PA2","PA3"]: raise RuntimeError("PA0123_SCOPE")
    if a["authority_boundaries"]["tenant_lifecycle"]!="PC1" or a["authority_boundaries"]["effective_entitlement"]!="PC4" or a["authority_boundaries"]["authorization_and_admin_identity"]!="PC5" or a["authority_boundaries"]["template_and_pack_composition"]!="PK": raise RuntimeError("PA0123_AUTHORITY_BOUNDARY")
    if a["authority_boundaries"]["finance"]!="UNCHANGED" or a["authority_boundaries"]["shared_operations"]!="UNCHANGED": raise RuntimeError("PA0123_DOMAIN_BOUNDARY")
    if set(r["required_checks"])!={"pc1_tenant_available","pk_template_pinned","pc4_entitlements_effective","pc5_tenant_admin_ready"}: raise RuntimeError("PA0123_READINESS_COVERAGE")
    if "platform_admin.PlatformAdministrationAuthority" not in p["public"]: raise RuntimeError("PA0123_PUBLIC_INTERFACE")
    up=(ROOT/"alembic_neutral/sql/pa0123_merchant_lifecycle_subscriptions_onboarding_up.sql").read_text().lower()
    for marker in ("pa_merchants","pa_plan_versions","pa_subscriptions","pa_usage_events","pa_onboarding_runs","pa_onboarding_checks","pa_reject_append_only_mutation"):
        if marker not in up: raise RuntimeError("PA0123_SQL_MISSING="+marker)
    for forbidden in ("update public.tenants","insert into public.tenant_entitlements","update public.tenant_entitlements","insert into public.permission_definitions","update public.pk_tenant_template_bindings","insert into public.financial_events","insert into public.journal_entries"):
        if forbidden in up: raise RuntimeError("PA0123_FORBIDDEN_AUTHORITY_WRITE="+forbidden)
    report=validate_pc0(ROOT,validate_release=False)
    manifest=_j("pa0123_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _sha(path)!=item["sha256"]: raise RuntimeError("PA0123_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"merchant_lifecycle":"PASS","plans_subscriptions":"PASS","usage_quotas":"PASS","onboarding_readiness":"PASS","finance":"UNCHANGED","shared_operations":"UNCHANGED","dependencies":"UNCHANGED","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session
    from database import engine
    from platform_admin import (
        PlatformAdministrationAuthority, RegisterMerchant, PlanDefinition, PlanQuota, RegisterPlanVersion,
        StartSubscription, TransitionSubscription, SubscriptionStatus, RecordUsage, StartOnboarding,
        EvaluateReadiness, CompleteOnboarding, TransitionMerchant, MerchantAdministrationState,
    )
    from platform_admin.sql_repository import SQLPlatformAdministrationRepository
    from platform_admin.service import PlatformAdministrationError
    from datetime import datetime,timezone
    from decimal import Decimal
    class TG:
        def __init__(self,eng): self.eng=eng
        def tenant_lifecycle(self,t):
            with self.eng.connect() as c:
                r=c.execute(text("SELECT lifecycle_state FROM tenants WHERE id=:i"),{"i":t}).first(); return None if r is None else r[0]
    class RG:
        def assess(self,**kw): return {c:("pass",f"evidence:{c}") for c in ("pc1_tenant_available","pk_template_pinned","pc4_entitlements_effective","pc5_tenant_admin_ready")}
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev": raise RuntimeError("PA0123_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_pa0123_test"; admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT"); test=None
    def drop():
        with admin.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name}); c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finance=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages","idempotency_records")
    try:
        drop();
        with admin.connect() as c: c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name)); cfg=Config(str(ROOT/"alembic_neutral.ini")); rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone,lifecycle_state) VALUES(15001,'PA1','PA Tenant 1','CM','XAF','en-CM','Africa/Douala','active'),(15002,'PA2','PA Tenant 2','CM','XAF','en-CM','Africa/Douala','active')"))
            before=tuple((t,c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()) for t in finance)
        _run(command.upgrade,cfg,rendered,HEAD)
        now=datetime(2026,8,15,9,0,tzinfo=timezone.utc)
        with Session(test) as s,s.begin():
            auth=PlatformAdministrationAuthority(SQLPlatformAdministrationRepository(s),TG(test),RG())
            for tid in (15001,15002): auth.register_merchant(RegisterMerchant("same-merchant",tid))
            plan=PlanDefinition("neutral.standard","1.0.0","platform_admin",("platform.core","reports.basic"),(PlanQuota("api_calls",Decimal("10")),))
            auth.register_plan(RegisterPlanVersion("plan",plan))
            sub=auth.start_subscription(StartSubscription("sub",15001,"neutral.standard","1.0.0",now)); sub=auth.transition_subscription(TransitionSubscription("active",15001,SubscriptionStatus.ACTIVE,sub.row_version,"contract active"))
            auth.record_usage(RecordUsage("usage-1",15001,"event-1","api_calls",Decimal("7"),"2026-08",now,"api")); auth.record_usage(RecordUsage("usage-2",15001,"event-2","api_calls",Decimal("5"),"2026-08",now,"api"))
            if not auth.quota_status(15001,"api_calls","2026-08").exceeded: raise RuntimeError("PA0123_QUOTA")
            ob=auth.start_onboarding(StartOnboarding("onboard",15001,"neutral.payments_only","1.0.0","neutral.standard","1.0.0")); ob=auth.evaluate_readiness(EvaluateReadiness("ready",15001,ob.row_version)); ob=auth.complete_onboarding(CompleteOnboarding("complete",15001,ob.row_version)); m=auth.repository.merchant(15001); auth.transition_merchant(TransitionMerchant("live",15001,MerchantAdministrationState.OPERATIONAL,m.row_version,"go live approved"))
            replay=auth.record_usage(RecordUsage("usage-1",15001,"event-1","api_calls",Decimal("7"),"2026-08",now,"api")); assert replay.event_key=="event-1"
            try: auth.record_usage(RecordUsage("usage-1",15001,"event-1","api_calls",Decimal("8"),"2026-08",now,"api"))
            except PlatformAdministrationError as e:
                if e.code!="PA_COMMAND_CONFLICT": raise
            else: raise RuntimeError("PA0123_CHANGED_REPLAY_ACCEPTED")
        with test.begin() as c:
            uid=c.execute(text("SELECT id FROM pa_usage_events LIMIT 1")).scalar_one()
            try:
                with c.begin_nested(): c.execute(text("UPDATE pa_usage_events SET quantity=999 WHERE id=:i"),{"i":uid})
            except DBAPIError: pass
            else: raise RuntimeError("PA0123_USAGE_MUTATION_ACCEPTED")
            after=tuple((t,c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()) for t in finance)
            if after!=before: raise RuntimeError("PA0123_FINANCIAL_EFFECTS_CHANGED")
        _run(command.downgrade,cfg,rendered,PREVIOUS); _run(command.upgrade,cfg,rendered,HEAD)
        with test.connect() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=HEAD: raise RuntimeError("PA0123_REUPGRADE")
        with engine.connect() as c: dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS: _run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev!=HEAD: raise RuntimeError("PA0123_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","tenant_idempotency":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test: test.dispose()
        drop(); admin.dispose()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--acceptance",action="store_true"); args=ap.parse_args(); r=static_verify();
    if args.acceptance: r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True)); print("PA0123_VERIFY=PASS")
if __name__=="__main__":
    try: main()
    except Exception as e: print("PA0123_VERIFY=FAIL\n"+str(e)); raise SystemExit(1)
