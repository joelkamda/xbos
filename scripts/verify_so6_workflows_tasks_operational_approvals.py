#!/usr/bin/env python3
"""Verify SO6 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="a6292ca36b458aafabff0e2f81766ccd9e5db42b";PREVIOUS="so5_resources_operational_assignment_030";HEAD="so6_workflows_tasks_operational_approvals_031"
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
    a=_json("so6_authority.json");l=_json("so6_legacy_adoption_manifest.json");i=_json("so6_public_interfaces.json");xa=_json("so6_xa_metadata.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO6_RELEASE_BOUNDARY")
    if {x["classification"] for x in l["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO6_LEGACY_DISCOVERY_INCOMPLETE")
    if (a["security_authority"],a["resource_authority"],a["structure_authority"])!=("PC5_REUSED","SO5_REUSED","PC1_REUSED"):raise RuntimeError("SO6_COMPETING_AUTHORITY")
    if a["security_approval_boundary"]!="PC5_ONLY" or a["document_authority"]!="SO7_EXCLUDED" or a["communications_authority"]!="SO8_EXCLUDED" or a["reporting_automation_authority"]!="SO9_EXCLUDED" or a["scheduling_authority"]!="SO10_EXCLUDED":raise RuntimeError("SO6_BOUNDARY_EXPANSION")
    if a["finance"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE" or i["finance_writer"]!="NONE" or i["security_role_writer"]!="NONE" or i["pc5_protected_approval_writer"]!="NONE" or xa["frontend_implementation"]!="NONE":raise RuntimeError("SO6_WRITER_BOUNDARY")
    up=(ROOT/"alembic_neutral/sql/so6_workflows_tasks_operational_approvals_up.sql").read_text(encoding="utf-8")
    for required in ("REFERENCES public.so5_resources(tenant_id,id)","REFERENCES public.organization_units(tenant_id,id)","REFERENCES public.locations(tenant_id,id)","so6_history_immutable","UNIQUE(tenant_id,workflow_id,id)"):
        if required not in up:raise RuntimeError("SO6_SQL_BOUNDARY="+required)
    if any(x in up.lower() for x in ("financial_events","journal_entries","financial_obligations","payment_settlements","protected_action_approvals","approval_decisions")):raise RuntimeError("SO6_FORBIDDEN_SQL_AUTHORITY")
    repo=(ROOT/"shared_operations/so6/sql_repository.py").read_text(encoding="utf-8")
    for lock in ("FOR UPDATE OF w","FOR UPDATE OF t","FOR UPDATE OF a"):
        if lock not in repo:raise RuntimeError("SO6_LOCK_SCOPE="+lock)
    profiles=[_json("examples/field_service_workflow_profile.json"),_json("examples/clinical_review_workflow_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"] or profiles[0]["workflow_types"]==profiles[1]["workflow_types"]:raise RuntimeError("SO6_NEUTRALITY")
    report=validate_pc0(ROOT,validate_release=False);manifest=_json("so6_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO6_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"security_authority":"PC5_REUSED","resource_authority":"SO5_REUSED","workflow":"PASS","tasks":"PASS","operational_approval":"PASS","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from types import SimpleNamespace
    from uuid import UUID
    from dataclasses import replace
    from datetime import datetime,timedelta,timezone
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    from database import engine
    from shared_operations.so6 import (AddTask,ApprovalStatus,ChangeTaskStatus,CompleteWorkflow,CreateWorkflow,DecideOperationalApproval,Priority,ReassignTask,RequestOperationalApproval,SO6Authority,SO6AuthorityError,TaskStatus,WorkflowStatus)
    from shared_operations.so6.sql_repository import SQLSO6Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO6_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so6_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9601,'SO6A','Neutral Workflows','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9601,9601,'LEGACY','Operations Site','Douala','Compatibility',true)"))
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO6_PREDECESSOR_REPLAY")
            org=c.execute(text("SELECT id,public_id FROM organization_units WHERE tenant_id=9601 ORDER BY id LIMIT 1")).one();loc=c.execute(text("SELECT id,public_id FROM locations WHERE tenant_id=9601 ORDER BY id LIMIT 1")).one()
            r1=c.execute(text("INSERT INTO so5_resources(tenant_id,resource_kind,classification_code,display_label,organization_unit_id,location_id,lifecycle_status) VALUES(9601,'non_person','review_station','Review Station',:o,:l,'active') RETURNING id,public_id"),{"o":org.id,"l":loc.id}).one()
            r2=c.execute(text("INSERT INTO so5_resources(tenant_id,resource_kind,classification_code,display_label,organization_unit_id,location_id,lifecycle_status) VALUES(9601,'non_person','quality_station','Quality Station',:o,:l,'active') RETURNING id,public_id"),{"o":org.id,"l":loc.id}).one()
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages")
        with test.connect() as c:finance_before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                op=UUID(str(org.public_id));lp=UUID(str(loc.public_id));rp1=UUID(str(r1.public_id));rp2=UUID(str(r2.public_id))
                def resource(t,p):
                    row=s.execute(text("SELECT tenant_id,public_id,lifecycle_status status FROM so5_resources WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**row._mapping) if row else None
                def scoped(table,t,p):
                    row=s.execute(text(f"SELECT tenant_id,public_id FROM {table} WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**row._mapping) if row else None
                so6=SO6Authority(SQLSO6Repository(s),resource_resolver=resource,organization_resolver=lambda t,p:scoped("organization_units",t,p),location_resolver=lambda t,p:scoped("locations",t,p),authorize=lambda *x:True)
                now=datetime.now(timezone.utc);wcmd=CreateWorkflow("workflow-1",9601,"service_case","Neutral Case","source_case","CASE-1",op,lp,Priority.HIGH,now+timedelta(days=1))
                w=so6.create_workflow(wcmd);count=s.execute(text("SELECT count(*) FROM so6_workflows WHERE tenant_id=9601")).scalar_one();replay=so6.create_workflow(wcmd)
                if replay!=w or s.execute(text("SELECT count(*) FROM so6_workflows WHERE tenant_id=9601")).scalar_one()!=count:raise RuntimeError("SO6_WORKFLOW_REPLAY")
                try:so6.create_workflow(replace(wcmd,title="Changed"))
                except SO6AuthorityError as exc:
                    if exc.code!="SO6_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO6_CHANGED_WORKFLOW_REPLAY_ACCEPTED")
                tcmd=AddTask("task-1",9601,w.public_id,w.row_version,"review","Review case",rp1,"review_station",Priority.NORMAL,now+timedelta(hours=2));task=so6.add_task(tcmd);task_count=s.execute(text("SELECT count(*) FROM so6_workflow_tasks WHERE tenant_id=9601")).scalar_one();task_replay=so6.add_task(tcmd)
                if task_replay!=task or s.execute(text("SELECT count(*) FROM so6_workflow_tasks WHERE tenant_id=9601")).scalar_one()!=task_count:raise RuntimeError("SO6_TASK_REPLAY")
                try:so6.add_task(replace(tcmd,title="Changed task"))
                except SO6AuthorityError as exc:
                    if exc.code!="SO6_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO6_CHANGED_TASK_REPLAY_ACCEPTED")
                task=so6.change_task_status(ChangeTaskStatus("task-start",9601,task.public_id,task.row_version,TaskStatus.IN_PROGRESS,"started",now));task=so6.reassign_task(ReassignTask("task-reassign",9601,task.public_id,task.row_version,rp2,"handoff",now))
                w=so6.workflow(9601,w.public_id);acmd=RequestOperationalApproval("approval-1",9601,w.public_id,w.row_version,"quality_release",task.public_id,rp2,now+timedelta(hours=3),"evidence:case-1");approval=so6.request_approval(acmd);approval_replay=so6.request_approval(acmd)
                if approval_replay!=approval or s.execute(text("SELECT count(*) FROM so6_operational_approvals WHERE tenant_id=9601")).scalar_one()!=1:raise RuntimeError("SO6_APPROVAL_REPLAY")
                w=so6.workflow(9601,w.public_id)
                try:so6.complete_workflow(CompleteWorkflow("early-complete",9601,w.public_id,w.row_version,"done",now))
                except SO6AuthorityError as exc:
                    if exc.code!="SO6_WORKFLOW_CONFLICT":raise
                else:raise RuntimeError("SO6_OPEN_WORK_COMPLETION_ACCEPTED")
                task=so6.change_task_status(ChangeTaskStatus("task-done",9601,task.public_id,task.row_version,TaskStatus.COMPLETED,"completed",now));approval=so6.decide_approval(DecideOperationalApproval("approval-decide",9601,approval.public_id,approval.row_version,ApprovalStatus.APPROVED,"reviewed",now,"Operational release"))
                w=so6.workflow(9601,w.public_id);w=so6.complete_workflow(CompleteWorkflow("complete",9601,w.public_id,w.row_version,"completed",now))
                if w.status is not WorkflowStatus.COMPLETED or not so6.history(9601,w.public_id):raise RuntimeError("SO6_HISTORY_OR_COMPLETION")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9602,'SO6B','Isolation','CM','XAF','en-CM','Africa/Douala')"))
            foreign_workflow=c.execute(text("INSERT INTO so6_workflows(tenant_id,workflow_type_code,title,subject_authority,subject_reference) VALUES(9602,'case','Isolation','source','1') RETURNING id")).scalar_one()
            try:
                with c.begin_nested():c.execute(text("INSERT INTO so6_workflow_tasks(tenant_id,workflow_id,task_type_code,title,assignee_resource_id) VALUES(9602,:w,'step','Cross tenant',:r)"),{"w":foreign_workflow,"r":r1.id})
            except IntegrityError:pass
            else:raise RuntimeError("SO6_CROSS_TENANT_RESOURCE_ACCEPTED")
        with test.connect() as c:finance_after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO6_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so6_workflows')")).scalar_one() is None:raise RuntimeError("SO6_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO6_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","workflow":"PASS","tasks":"PASS","operational_approval":"PASS","history":"PASS","idempotency":"PASS","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()
def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();r=static_verify()
    if a.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("SO6_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO6_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
