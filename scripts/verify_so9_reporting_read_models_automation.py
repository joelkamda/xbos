#!/usr/bin/env python3
"""Verify SO9 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="bdca5e66f8b62bb0bcbd45e7700dd3e7ca9e44af";PREVIOUS="so8_communications_delivery_offline_033";HEAD="so9_reporting_read_models_automation_034"
CONTRACTS=ROOT/"contracts/shared_operations/v1"
def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))
def _canonical(path):return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def _set_url(config,url):config.set_main_option("sqlalchemy.url",url.replace("%","%%"))
def _run(operation,config,url,target):
    old={k:os.environ.get(k) for k in ("DATABASE_URL","MIGRATION_DATABASE_URL")};_set_url(config,url);os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
    try:operation(config,target)
    finally:
        for k,v in old.items():os.environ.pop(k,None) if v is None else os.environ.__setitem__(k,v)
def static_verify():
    from core.platform.architecture_contract import validate_pc0
    a=_json("so9_authority.json");l=_json("so9_legacy_adoption_manifest.json");i=_json("so9_public_interfaces.json");xa=_json("so9_xa_metadata.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO9_RELEASE_BOUNDARY")
    if {x["classification"] for x in l["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO9_LEGACY_DISCOVERY_INCOMPLETE")
    if a["security_authority"]!="PC5_REUSED" or a["delivery_authority"]!="SO8_REUSED":raise RuntimeError("SO9_COMPETING_AUTHORITY")
    if a["read_model_authority"]!="SO9_DERIVED_REBUILDABLE" or a["source_domain_authority"]!="EXTERNAL_PUBLIC_READ_CONTRACTS":raise RuntimeError("SO9_READ_MODEL_AUTHORITY")
    if a["financial_reporting_authority"]!="NEUTRAL_FINANCE_PRESERVED" or a["scheduling_authority"]!="SO10_EXCLUDED" or a["source_writer_authority"]!="NONE":raise RuntimeError("SO9_BOUNDARY_EXPANSION")
    if a["finance"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE" or i["finance_writer"]!="NONE" or i["source_domain_writer"]!="NONE" or i["workflow_writer"]!="NONE" or i["scheduling_writer"]!="NONE" or xa["frontend_implementation"]!="NONE":raise RuntimeError("SO9_WRITER_BOUNDARY")
    if not xa["read_model_is_derived"] or not xa["report_is_derived"] or not xa["dashboard_never_grants_authorization"]:raise RuntimeError("SO9_XA_DERIVED_BOUNDARY")
    up=(ROOT/"alembic_neutral/sql/so9_reporting_read_models_automation_up.sql").read_text(encoding="utf-8")
    for required in ("UNIQUE(tenant_id,command_key)","UNIQUE(tenant_id,read_model_id,revision_number)","UNIQUE(tenant_id,automation_id,execution_key)","so9_derived_history_immutable","result_sha256 char(64)"):
        if required not in up:raise RuntimeError("SO9_SQL_BOUNDARY="+required)
    if any(x in up.lower() for x in ("insert into public.financial_events","update public.financial_events","insert into public.journal_entries","insert into public.financial_obligations","insert into public.payment_settlements","insert into public.so8_delivery_jobs","update public.so6_workflows")):raise RuntimeError("SO9_FORBIDDEN_SQL_AUTHORITY")
    repo=(ROOT/"shared_operations/so9/sql_repository.py").read_text(encoding="utf-8")
    for marker in ("FOR UPDATE OF r","FOR UPDATE OF a","SO9_COMMAND_CONFLICT","so9_projection_snapshots"):
        if marker not in repo:raise RuntimeError("SO9_REPOSITORY_BOUNDARY="+marker)
    service=(ROOT/"shared_operations/so9/service.py").read_text(encoding="utf-8")
    if 'return "so9.auto."+hashlib.sha256(raw).hexdigest()' not in service:raise RuntimeError("SO9_DELIVERY_IDEMPOTENCY_KEY")
    profiles=[_json("examples/field_service_reporting_profile.json"),_json("examples/clinical_reporting_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"] or profiles[0]["metrics"]==profiles[1]["metrics"]:raise RuntimeError("SO9_NEUTRALITY")
    module=json.loads((ROOT/"contracts/platform/v1/pc0_module_map.json").read_text());reports=next(x for x in module["modules"] if x["code"]=="reports")
    if (reports.get("owner"),reports.get("kind"))!=("SO9","shared_operations_authority") or "shared_operations/so9" not in reports.get("source_roots",[]):raise RuntimeError("SO9_PC0_MODULE_NOT_PROMOTED")
    pc0=json.loads((ROOT/"contracts/platform/v1/pc0_data_authority_register.json").read_text());authority=next(x for x in pc0["authorities"] if x.get("module")=="reports")
    refs=json.loads((ROOT/"contracts/platform/v1/pc0_reference_authority_migration_register.json").read_text())["entries"];migration=next(x for x in refs if x.get("module_code")=="reports")
    if authority["code"]!="operational_reporting_read_models" or migration["target_data_authority"]!=authority["code"]:raise RuntimeError("SO9_REFERENCE_MIGRATION")
    report=validate_pc0(ROOT,validate_release=False);manifest=_json("so9_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO9_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"read_model_authority":"PASS","reporting":"PASS","metrics":"PASS","automation":"PASS","delivery_authority":"SO8_REUSED","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from dataclasses import replace
    from datetime import datetime,timedelta,timezone
    from uuid import UUID
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import DBAPIError
    from database import engine
    from shared_operations.so8 import CreateDeliveryJob,SO8Authority
    from shared_operations.so8.sql_repository import SQLSO8Repository
    from shared_operations.so9 import (AutomationStatus,ConfigureAutomation,DefineMetric,DefineReadModel,DefineReport,ExecuteAutomation,MetricAggregation,RefreshReadModel,RunReport,SO9Authority,SO9AuthorityError)
    from shared_operations.so9.sql_repository import SQLSO9Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO9_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so9_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9901,'SO9A','Neutral Reporting','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9901,9901,'LEGACY','Reporting Site','Douala','Compatibility',true)"))
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.connect() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO9_PREDECESSOR_REPLAY")
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages","idempotency_records")
        with test.connect() as c:finance_before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                so8=SO8Authority(SQLSO8Repository(s),authorize=lambda *x:True)
                def handoff(t,key,kind,channel,dest,payload,at):
                    return so8.create_delivery(CreateDeliveryJob(key,t,kind,channel,dest,payload,at,3)).public_id
                so9=SO9Authority(SQLSO9Repository(s),authorize=lambda *x:True,source_resolver=lambda t,a:t==9901 and a in {"so6.workflow","finance.reconciliation"},delivery_handoff=handoff)
                now=datetime.now(timezone.utc)
                rmcmd=DefineReadModel("rm-1",9901,"ops.performance","Operations Performance","so6.workflow","workflow.performance",{})
                rm=so9.define_read_model(rmcmd)
                scmd=RefreshReadModel("refresh-1",9901,rm.public_id,"a"*64,{"rows":[{"duration":10},{"duration":20},{"duration":30}]},now,"wf:9901")
                snap=so9.refresh_read_model(scmd);count=s.execute(text("SELECT count(*) FROM so9_projection_snapshots WHERE tenant_id=9901")).scalar_one();replay=so9.refresh_read_model(scmd)
                if replay!=snap or s.execute(text("SELECT count(*) FROM so9_projection_snapshots WHERE tenant_id=9901")).scalar_one()!=count:raise RuntimeError("SO9_REFRESH_REPLAY")
                try:so9.refresh_read_model(replace(scmd,payload={"rows":[{"duration":99}]}))
                except SO9AuthorityError as exc:
                    if exc.code!="SO9_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO9_CHANGED_REFRESH_REPLAY_ACCEPTED")
                so9.define_metric(DefineMetric("metric-count",9901,rm.public_id,"job_count","Job Count",MetricAggregation.COUNT))
                so9.define_metric(DefineMetric("metric-sum",9901,rm.public_id,"duration_sum","Duration Sum",MetricAggregation.SUM,"duration"))
                report=so9.define_report(DefineReport("report-1",9901,rm.public_id,"ops.summary","Operations Summary",{},("job_count","duration_sum")))
                rcmd=RunReport("run-1",9901,report.public_id,now,{"period":"day"},snap.public_id);rr=so9.run_report(rcmd)
                if rr.result_payload["metrics"]!={"job_count":3,"duration_sum":"60"}:raise RuntimeError("SO9_METRIC_REPORT")
                if so9.run_report(rcmd)!=rr or len(so9.report_runs(9901,report.public_id))!=1:raise RuntimeError("SO9_REPORT_REPLAY")
                auto=so9.configure_automation(ConfigureAutomation("auto-1",9901,report.public_id,"daily.ops","daily_window_resolved",{"timezone":"Africa/Douala"},True,"report","email","ops@example.invalid"))
                acmd=ExecuteAutomation("auto-run-1",9901,auto.public_id,"2026-08-14",now+timedelta(minutes=1),{"period":"day"},snap.public_id);ar=so9.execute_automation(acmd)
                if not ar.delivery_job_public_id or so9.execute_automation(acmd)!=ar:raise RuntimeError("SO9_AUTOMATION_REPLAY")
                if s.execute(text("SELECT count(*) FROM so8_delivery_jobs WHERE tenant_id=9901")).scalar_one()!=1:raise RuntimeError("SO9_SO8_DELIVERY_DEDUPE")
                try:so9.execute_automation(replace(acmd,command_key="auto-run-2"))
                except SO9AuthorityError as exc:
                    if exc.code!="SO9_AUTOMATION_EXECUTION_CONFLICT":raise
                else:raise RuntimeError("SO9_DUPLICATE_EXECUTION_ACCEPTED")
                if s.execute(text("SELECT count(*) FROM so8_delivery_jobs WHERE tenant_id=9901")).scalar_one()!=1:raise RuntimeError("SO9_SO8_EXECUTION_IDENTITY_DEDUPE")
                try:
                    with s.begin_nested():s.execute(text("UPDATE so9_projection_snapshots SET source_watermark='rewrite' WHERE tenant_id=9901"))
                except DBAPIError as exc:
                    if "append-only" not in str(exc).lower():raise
                else:raise RuntimeError("SO9_SNAPSHOT_MUTATION_ACCEPTED")
                try:
                    with s.begin_nested():s.execute(text("DELETE FROM so9_report_runs WHERE tenant_id=9901"))
                except DBAPIError as exc:
                    if "append-only" not in str(exc).lower():raise
                else:raise RuntimeError("SO9_REPORT_RUN_MUTATION_ACCEPTED")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9902,'SO9B','Isolation','CM','XAF','en-CM','Africa/Douala')"))
            if c.execute(text("SELECT count(*) FROM so9_read_models WHERE tenant_id=9902")).scalar_one()!=0:raise RuntimeError("SO9_READ_MODEL_TENANT_LEAK")
            if c.execute(text("SELECT count(*) FROM so9_report_runs WHERE tenant_id=9902")).scalar_one()!=0:raise RuntimeError("SO9_REPORT_TENANT_LEAK")
        with test.connect() as c:finance_after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO9_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:devhead=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if devhead==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif devhead==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so9_read_models')")).scalar_one() is None:raise RuntimeError("SO9_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO9_DEVELOPMENT_HEAD_UNSAFE="+devhead)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","read_model_authority":"PASS","reporting":"PASS","metrics":"PASS","automation":"PASS","delivery_authority":"SO8_REUSED","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()
def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();r=static_verify()
    if a.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("SO9_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO9_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
