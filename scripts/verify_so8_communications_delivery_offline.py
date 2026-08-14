#!/usr/bin/env python3
"""Verify SO8 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="418759a50fd2cfae4d9cc084d0fd21cd057162fb";PREVIOUS="so7_documents_files_evidence_search_032";HEAD="so8_communications_delivery_offline_033"
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
    a=_json("so8_authority.json");l=_json("so8_legacy_adoption_manifest.json");i=_json("so8_public_interfaces.json");xa=_json("so8_xa_metadata.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO8_RELEASE_BOUNDARY")
    if {x["classification"] for x in l["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO8_LEGACY_DISCOVERY_INCOMPLETE")
    if (a["security_authority"],a["document_authority"])!=("PC5_REUSED","SO7_REUSED"):raise RuntimeError("SO8_COMPETING_AUTHORITY")
    if a["delivery_authority"]!="SO8_PROVIDER_NEUTRAL" or a["offline_authority"]!="SO8_QUEUE_REPLAY_SERVER_REVALIDATION" or a["provider_authority"]!="ADAPTER_ONLY":raise RuntimeError("SO8_AUTHORITY_SHAPE")
    if a["financial_outbox_authority"]!="NEUTRAL_FINANCE_PRESERVED" or a["reporting_automation_authority"]!="SO9_EXCLUDED" or a["scheduling_authority"]!="SO10_EXCLUDED":raise RuntimeError("SO8_BOUNDARY_EXPANSION")
    if a["finance"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE" or i["finance_writer"]!="NONE" or i["financial_outbox_writer"]!="NONE" or i["workflow_writer"]!="NONE" or i["document_writer"]!="NONE" or xa["frontend_implementation"]!="NONE":raise RuntimeError("SO8_WRITER_BOUNDARY")
    if not xa["offline_server_truth"] or not xa["offline_idempotency_required"] or not xa["offline_conflict_surface"]:raise RuntimeError("SO8_XA_OFFLINE_BOUNDARY")
    up=(ROOT/"alembic_neutral/sql/so8_communications_delivery_offline_up.sql").read_text(encoding="utf-8")
    for required in ("UNIQUE(tenant_id,command_key)","UNIQUE(tenant_id,job_id,attempt_number)","UNIQUE(tenant_id,source_code,external_event_key)","UNIQUE(tenant_id,device_public_id,client_sequence)","so8_append_only_history","lifecycle_status IN('pending','in_progress','retry_wait','delivered','dead_letter','cancelled')"):
        if required not in up:raise RuntimeError("SO8_SQL_BOUNDARY="+required)
    if any(x in up.lower() for x in ("insert into public.outbox_messages","update public.outbox_messages","financial_events","journal_entries","financial_obligations","payment_settlements","protected_action_approvals")):raise RuntimeError("SO8_FORBIDDEN_SQL_AUTHORITY")
    repo=(ROOT/"shared_operations/so8/sql_repository.py").read_text(encoding="utf-8")
    for marker in ("FOR UPDATE OF j","FOR UPDATE OF o","SO8_EXTERNAL_EVENT_CONFLICT","SO8_OFFLINE_SEQUENCE_CONFLICT"):
        if marker not in repo:raise RuntimeError("SO8_REPOSITORY_BOUNDARY="+marker)
    profiles=[_json("examples/field_service_delivery_profile.json"),_json("examples/clinical_communications_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"] or profiles[0]["channels"]==profiles[1]["channels"]:raise RuntimeError("SO8_NEUTRALITY")
    pc0=json.loads((ROOT/"contracts/platform/v1/pc0_data_authority_register.json").read_text())
    delivery=next(x for x in pc0["authorities"] if x["code"]=="generic_delivery_jobs_offline")
    if (delivery.get("owner"),delivery.get("module"))!=("SO8","communications"):raise RuntimeError("SO8_PC0_AUTHORITY_NOT_ADOPTED")
    refs=json.loads((ROOT/"contracts/platform/v1/pc0_reference_authority_migration_register.json").read_text())["entries"]
    if not all("SO8" in next(x for x in refs if x["reference"]==r)["target_authority"] for r in ("generic_idempotency","generic_event_dispatch")):raise RuntimeError("SO8_REFERENCE_MIGRATION")
    report=validate_pc0(ROOT,validate_release=False);manifest=_json("so8_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO8_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"security_authority":"PC5_REUSED","document_authority":"SO7_REUSED","delivery":"PASS","retry":"PASS","webhook":"PASS","offline_replay":"PASS","idempotency":"PASS","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from dataclasses import replace
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from uuid import UUID
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import DBAPIError
    from database import engine
    from shared_operations.so8 import (AttemptOutcome,ClaimDeliveryJob,CreateDeliveryJob,DeliveryStatus,OfflineStatus,QueueOfflineCommand,ReceiveInboundDelivery,RecordDeliveryAttempt,ResolveOfflineCommand,SO8Authority,SO8AuthorityError)
    from shared_operations.so8.sql_repository import SQLSO8Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO8_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so8_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9801,'SO8A','Neutral Delivery','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9801,9801,'LEGACY','Delivery Site','Douala','Compatibility',true)"))
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO8_PREDECESSOR_REPLAY")
            loc=c.execute(text("SELECT id FROM locations WHERE tenant_id=9801 ORDER BY id LIMIT 1")).scalar_one()
            org=c.execute(text("SELECT id FROM organization_units WHERE tenant_id=9801 ORDER BY id LIMIT 1")).scalar_one()
            device=c.execute(text("INSERT INTO device_identities(device_code,tenant_id,location_id,organization_unit_id,status) VALUES('offline-9801',9801,:l,:o,'active') RETURNING public_id"),{"l":loc,"o":org}).scalar_one()
            doc=c.execute(text("INSERT INTO so7_documents(tenant_id,title,classification_code,current_version_number) VALUES(9801,'Dispatch Evidence','delivery_evidence',1) RETURNING id,public_id")).one()
            dv=c.execute(text("INSERT INTO so7_document_versions(tenant_id,document_id,version_number,file_name,content_type,content_length,content_sha256,storage_provider,storage_key) VALUES(9801,:d,1,'dispatch.pdf','application/pdf',10,:sha,'local','so8/dispatch.pdf') RETURNING public_id"),{"d":doc.id,"sha":"a"*64}).scalar_one()
            wf=c.execute(text("INSERT INTO so6_workflows(tenant_id,workflow_type_code,title,subject_authority,subject_reference) VALUES(9801,'delivery_case','Delivery Case','source','CASE-9801') RETURNING public_id")).scalar_one()
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages","idempotency_records")
        with test.connect() as c:finance_before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                def subject(t,a,r):return a=="workflow" and bool(s.execute(text("SELECT 1 FROM so6_workflows WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":r}).scalar())
                def docver(t,p):return bool(s.execute(text("SELECT 1 FROM so7_document_versions WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).scalar())
                def dev(t,p):return bool(s.execute(text("SELECT 1 FROM device_identities WHERE tenant_id=:t AND public_id=:p AND status='active'"),{"t":t,"p":str(p)}).scalar())
                so8=SO8Authority(SQLSO8Repository(s),authorize=lambda *x:True,subject_resolver=subject,document_version_resolver=docver,device_resolver=dev)
                now=datetime.now(timezone.utc);wref=str(wf)
                jcmd=CreateDeliveryJob("delivery-1",9801,"notification","staff_in_app","resource:9801",{"message":"ready"},now,3,"workflow",wref,UUID(str(dv)))
                j=so8.create_delivery(jcmd);count=s.execute(text("SELECT count(*) FROM so8_delivery_jobs WHERE tenant_id=9801")).scalar_one();replay=so8.create_delivery(jcmd)
                if replay!=j or s.execute(text("SELECT count(*) FROM so8_delivery_jobs WHERE tenant_id=9801")).scalar_one()!=count:raise RuntimeError("SO8_DELIVERY_REPLAY")
                try:so8.create_delivery(replace(jcmd,destination_reference="changed"))
                except SO8AuthorityError as exc:
                    if exc.code!="SO8_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO8_CHANGED_DELIVERY_REPLAY_ACCEPTED")
                j=so8.claim_delivery(ClaimDeliveryJob("claim-1",9801,j.public_id,j.row_version,"worker:a",now,now+timedelta(minutes=5)))
                j=so8.record_attempt(RecordDeliveryAttempt("attempt-1",9801,j.public_id,j.row_version,AttemptOutcome.RETRYABLE_FAILURE,"adapter",now+timedelta(seconds=10),error_code="temporary",retry_at=now+timedelta(minutes=10)))
                if j.status is not DeliveryStatus.RETRY_WAIT or j.attempt_count!=1:raise RuntimeError("SO8_RETRY_STATE")
                j=so8.claim_delivery(ClaimDeliveryJob("claim-2",9801,j.public_id,j.row_version,"worker:b",now+timedelta(minutes=10),now+timedelta(minutes=15)))
                j=so8.record_attempt(RecordDeliveryAttempt("attempt-2",9801,j.public_id,j.row_version,AttemptOutcome.DELIVERED,"adapter",now+timedelta(minutes=11),provider_reference="ok"))
                if j.status is not DeliveryStatus.DELIVERED or len(so8.attempts(9801,j.public_id))!=2:raise RuntimeError("SO8_DELIVERY_ATTEMPTS")
                try:
                    with s.begin_nested():s.execute(text("UPDATE so8_delivery_attempts SET provider_reference='rewrite' WHERE tenant_id=9801"))
                except DBAPIError as exc:
                    if "append-only" not in str(exc).lower():raise
                else:raise RuntimeError("SO8_ATTEMPT_MUTATION_ACCEPTED")
                icmd=ReceiveInboundDelivery("in-1",9801,"partner_webhook","evt-1","b"*64,{"state":"ok"},now,"workflow",wref);ib=so8.receive_inbound(icmd)
                if so8.receive_inbound(replace(icmd,command_key="in-2",occurred_at=now+timedelta(seconds=1)))!=ib:raise RuntimeError("SO8_INBOUND_DEDUPE")
                try:so8.receive_inbound(replace(icmd,command_key="in-3",payload_sha256="c"*64,payload={"state":"changed"}))
                except SO8AuthorityError as exc:
                    if exc.code!="SO8_EXTERNAL_EVENT_CONFLICT":raise
                else:raise RuntimeError("SO8_EXTERNAL_EVENT_REUSE_ACCEPTED")
                ocmd=QueueOfflineCommand("off-1",9801,UUID(str(device)),1,"inspection.capture","workflow",wref,{"reading":42},now,1);o=so8.queue_offline(ocmd);oreplay=so8.queue_offline(ocmd)
                if oreplay!=o or len(so8.offline_history(9801,o.public_id))!=1:raise RuntimeError("SO8_OFFLINE_REPLAY")
                try:so8.queue_offline(replace(ocmd,payload={"reading":43}))
                except SO8AuthorityError as exc:
                    if exc.code!="SO8_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO8_CHANGED_OFFLINE_REPLAY_ACCEPTED")
                o=so8.resolve_offline(ResolveOfflineCommand("off-resolve",9801,o.public_id,o.row_version,OfflineStatus.APPLIED,"accepted",now+timedelta(minutes=1),"workflow-result:1"))
                if o.status is not OfflineStatus.APPLIED or len(so8.offline_history(9801,o.public_id))!=2:raise RuntimeError("SO8_OFFLINE_HISTORY")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9802,'SO8B','Isolation','CM','XAF','en-CM','Africa/Douala')"))
            if c.execute(text("SELECT count(*) FROM so8_delivery_jobs WHERE tenant_id=9802")).scalar_one()!=0:raise RuntimeError("SO8_DELIVERY_TENANT_LEAK")
            if c.execute(text("SELECT count(*) FROM so8_inbound_deliveries WHERE tenant_id=9802")).scalar_one()!=0:raise RuntimeError("SO8_INBOUND_TENANT_LEAK")
        with test.connect() as c:finance_after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO8_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:devhead=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if devhead==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif devhead==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so8_delivery_jobs')")).scalar_one() is None:raise RuntimeError("SO8_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO8_DEVELOPMENT_HEAD_UNSAFE="+devhead)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","delivery":"PASS","retry":"PASS","webhook":"PASS","offline_replay":"PASS","idempotency":"PASS","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()
def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();r=static_verify()
    if a.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("SO8_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO8_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
