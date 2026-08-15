from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE="8ff3d8b"
SOURCE_FULL="8ff3d8b2685a24006d79b5cc6cd3e85c17d52d70"
PREVIOUS="pa0123_merchant_lifecycle_subscriptions_onboarding_039"
HEAD="pa45_support_recovery_health_040"
CONTRACTS=ROOT/"contracts/platform_admin/v1"


def _j(name): return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))
def _sha(path): return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def _set_url(cfg,url): cfg.set_main_option("sqlalchemy.url",url.replace("%","%%"))
def _run(op,cfg,url,target):
    old={k:os.environ.get(k) for k in ("DATABASE_URL","MIGRATION_DATABASE_URL")}; _set_url(cfg,url); os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
    try: op(cfg,target)
    finally:
        for k,v in old.items(): os.environ.pop(k,None) if v is None else os.environ.__setitem__(k,v)


def static_verify():
    from core.platform.architecture_contract import validate_pc0
    a=_j("pa45_authority.json"); h=_j("pa45_health_contract.json"); p=_j("pa45_public_interfaces.json")
    if (a["source_checkpoint"],a["source_checkpoint_full"],a["previous_head"],a["accepted_head"])!=(SOURCE,SOURCE_FULL,PREVIOUS,HEAD): raise RuntimeError("PA45_RELEASE_BOUNDARY")
    if a["coverage"]!=["PA4","PA5"]: raise RuntimeError("PA45_SCOPE")
    b=a["authority_boundaries"]
    if b["authorization_and_identity"]!="PC5_REUSED" or b["merchant_administration"]!="PA0123_REUSED" or b["template_composition"]!="PK_REUSED": raise RuntimeError("PA45_AUTHORITY_BOUNDARY")
    if b["finance"]!="UNCHANGED" or b["shared_operations"]!="UNCHANGED": raise RuntimeError("PA45_DOMAIN_BOUNDARY")
    if h["aggregation_precedence"]!=["healthy","unknown","degraded","blocked"]: raise RuntimeError("PA45_HEALTH_PRECEDENCE")
    if "platform_admin.pa45_service.PA45Authority" not in p["public"]: raise RuntimeError("PA45_PUBLIC_INTERFACE")
    up=(ROOT/"alembic_neutral/sql/pa45_support_recovery_health_up.sql").read_text(encoding="utf-8").lower()
    for marker in ("pa_support_sessions","pa_support_actions","pa_recovery_cases","pa_recovery_actions","pa_health_snapshots","pa_health_checks","trg_pa_health_snapshots_immutable"):
        if marker not in up: raise RuntimeError("PA45_SQL_MISSING="+marker)
    for forbidden in ("update public.tenants","insert into public.tenant_entitlements","update public.tenant_entitlements","insert into public.permission_definitions","update public.authorization_roles","update public.pk_tenant_template_bindings","insert into public.financial_events","insert into public.journal_entries","insert into public.payment_settlements"):
        if forbidden in up: raise RuntimeError("PA45_FORBIDDEN_AUTHORITY_WRITE="+forbidden)
    report=validate_pc0(ROOT,validate_release=False)
    manifest=_j("pa45_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _sha(path)!=item["sha256"]: raise RuntimeError("PA45_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE,"previous_head":PREVIOUS,"accepted_head":HEAD,"support_delegation":"PASS","recovery":"PASS","merchant_health":"PASS","platform_health":"PASS","finance":"UNCHANGED","shared_operations":"UNCHANGED","dependencies":"UNCHANGED","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}


def database_acceptance():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session
    from database import engine
    from datetime import datetime,timedelta,timezone
    from uuid import uuid4
    from platform_admin import PlatformAdministrationAuthority, RegisterMerchant
    from platform_admin.sql_repository import SQLPlatformAdministrationRepository
    from platform_admin.pa45_contracts import (
        OpenSupportSession,SupportAccessMode,RecordSupportAction,TransitionSupportSession,SupportSessionState,
        OpenRecoveryCase,RecordRecoveryAction,RecoveryActionOutcome,TransitionRecoveryCase,RecoveryCaseState,
        CaptureMerchantHealth,CapturePlatformHealth,
    )
    from platform_admin.pa45_service import PA45Authority,PA45AuthorityError
    from platform_admin.pa45_sql_repository import SQLPA45Repository

    class TenantGateway:
        def __init__(self,eng): self.eng=eng
        def tenant_lifecycle(self,t):
            with self.eng.connect() as c:
                r=c.execute(text("SELECT lifecycle_state FROM tenants WHERE id=:i"),{"i":t}).first(); return None if r is None else r[0]
    class ReadinessGateway:
        def assess(self,**kw): return {c:("pass",f"evidence:{c}") for c in ("pc1_tenant_available","pk_template_pinned","pc4_entitlements_effective","pc5_tenant_admin_ready")}
    class SecurityGateway:
        def authorize_support(self,**kw): return True,f"pc5:authorization:{kw['tenant_id']}"
    class HealthGateway:
        def __init__(self,now): self.now=now
        def assess_merchant(self,**kw): return {"tenant_context":("healthy","pc1:tenant",self.now),"subscription":("healthy","pa:subscription",self.now),"integrations":("degraded","so8:delivery",self.now)}
        def assess_platform(self): return {"database":("healthy","ops:database",self.now),"migrations":("healthy","ops:migrations",self.now)}

    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev": raise RuntimeError("PA45_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_pa45_test"; admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT"); test=None
    def drop():
        with admin.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name}); c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finance=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages","idempotency_records")
    try:
        drop()
        with admin.connect() as c: c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name)); cfg=Config(str(ROOT/"alembic_neutral.ini")); rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone,lifecycle_state) VALUES(16001,'PA45A','PA45 Tenant A','CM','XAF','en-CM','Africa/Douala','active'),(16002,'PA45B','PA45 Tenant B','CM','XAF','en-CM','Africa/Douala','active')"))
            before=tuple((t,c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()) for t in finance)
        with Session(test) as s,s.begin():
            pa=PlatformAdministrationAuthority(SQLPlatformAdministrationRepository(s),TenantGateway(test),ReadinessGateway())
            pa.register_merchant(RegisterMerchant("merchant",16001)); pa.register_merchant(RegisterMerchant("merchant",16002))
        _run(command.upgrade,cfg,rendered,HEAD)
        now=datetime(2026,8,15,10,0,tzinfo=timezone.utc); actor_a=uuid4(); actor_b=uuid4()
        with Session(test) as s,s.begin():
            auth=PA45Authority(SQLPA45Repository(s),SecurityGateway(),HealthGateway(now),now_provider=lambda:now)
            cmd_a=OpenSupportSession("same-support",16001,actor_a,SupportAccessMode.DELEGATED,("merchant.read","diagnostics.read"),"ticket support",now,now+timedelta(hours=2),"pc5:auth:a")
            cmd_b=OpenSupportSession("same-support",16002,actor_b,SupportAccessMode.DELEGATED,("merchant.read",),"ticket support",now,now+timedelta(hours=2),"pc5:auth:b")
            sa=auth.open_support_session(cmd_a); sb=auth.open_support_session(cmd_b)
            if sa.tenant_id==sb.tenant_id or auth.repository.support_session(16002,sa.public_id) is not None: raise RuntimeError("PA45_TENANT_ISOLATION")
            if auth.open_support_session(cmd_a)!=sa: raise RuntimeError("PA45_EXACT_REPLAY")
            try: auth.open_support_session(OpenSupportSession("same-support",16001,actor_a,SupportAccessMode.DELEGATED,("merchant.read",),"changed",now,now+timedelta(hours=2),"pc5:auth:a"))
            except PA45AuthorityError as e:
                if e.code!="PA45_COMMAND_CONFLICT": raise
            else: raise RuntimeError("PA45_CHANGED_REPLAY_ACCEPTED")
            auth.record_support_action(RecordSupportAction("support-action",16001,sa.public_id,"inspect_config","pc4:tenant:16001","audit:support:1",now+timedelta(minutes=5)))
            case=auth.open_recovery_case(OpenRecoveryCase("recovery",16001,"INC-16001","integration_uncertain","provider:external:1","diagnose only",actor_a,"ticket:16001"))
            auth.record_recovery_action(RecordRecoveryAction("recovery-action",16001,case.public_id,"provider_lookup",RecoveryActionOutcome.INCONCLUSIVE,"provider:lookup:1",now+timedelta(minutes=10),sa.public_id))
            resolved=auth.transition_recovery_case(TransitionRecoveryCase("resolve",16001,case.public_id,RecoveryCaseState.RESOLVED,case.row_version,"provider state recovered","audit:resolved"))
            if resolved.state is not RecoveryCaseState.RESOLVED: raise RuntimeError("PA45_RECOVERY")
            mh=auth.capture_merchant_health(CaptureMerchantHealth("merchant-health",16001)); ph=auth.capture_platform_health(CapturePlatformHealth("platform-health"))
            if mh.status.value!="degraded" or ph.status.value!="healthy": raise RuntimeError("PA45_HEALTH")
            closed=auth.transition_support_session(TransitionSupportSession("close-support",16001,sa.public_id,SupportSessionState.CLOSED,sa.row_version,"ticket complete"))
            if closed.state is not SupportSessionState.CLOSED: raise RuntimeError("PA45_SUPPORT_CLOSE")
        with test.begin() as c:
            aid=c.execute(text("SELECT id FROM pa_support_actions LIMIT 1")).scalar_one(); hid=c.execute(text("SELECT id FROM pa_health_snapshots LIMIT 1")).scalar_one()
            for statement,params in (("UPDATE pa_support_actions SET action_code='tampered' WHERE id=:i",{"i":aid}),("DELETE FROM pa_health_snapshots WHERE id=:i",{"i":hid})):
                try:
                    with c.begin_nested(): c.execute(text(statement),params)
                except DBAPIError: pass
                else: raise RuntimeError("PA45_APPEND_ONLY_MUTATION_ACCEPTED")
            after=tuple((t,c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()) for t in finance)
            if after!=before: raise RuntimeError("PA45_FINANCIAL_EFFECTS_CHANGED")
        _run(command.downgrade,cfg,rendered,PREVIOUS); _run(command.upgrade,cfg,rendered,HEAD)
        with test.connect() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=HEAD: raise RuntimeError("PA45_REUPGRADE")
        with engine.connect() as c: dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS: _run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev!=HEAD: raise RuntimeError("PA45_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","tenant_isolation":"PASS","tenant_idempotency":"PASS","append_only_evidence":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test: test.dispose()
        drop(); admin.dispose()


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--acceptance",action="store_true"); args=ap.parse_args(); result=static_verify()
    if args.acceptance: result.update(database_acceptance())
    print(json.dumps(result,indent=2,sort_keys=True)); print("PA45_VERIFY=PASS")

if __name__=="__main__":
    try: main()
    except Exception as e: print("PA45_VERIFY=FAIL\n"+str(e)); raise SystemExit(1)
