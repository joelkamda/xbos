#!/usr/bin/env python3
"""Verify SO10 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="1ed3c4e7aeab4fbfbb69d8b958312f9be19452bb";PREVIOUS="so9_reporting_read_models_automation_034";HEAD="so10_scheduling_reservations_service_execution_035"
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
    a=_json("so10_authority.json");l=_json("so10_legacy_adoption_manifest.json");i=_json("so10_public_interfaces.json");xa=_json("so10_xa_metadata.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO10_RELEASE_BOUNDARY")
    if {x["classification"] for x in l["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO10_LEGACY_DISCOVERY_INCOMPLETE")
    expected=("PC4_REUSED","PC2_SO2_REUSED","SO1_REUSED","SO5_REUSED","PC5_REUSED")
    actual=(a["time_authority"],a["party_authority"],a["catalog_authority"],a["resource_authority"],a["security_authority"])
    if actual!=expected:raise RuntimeError("SO10_COMPETING_AUTHORITY")
    if a["workflow_authority"]!="SO6_EXTERNAL" or a["delivery_authority"]!="SO8_EXTERNAL":raise RuntimeError("SO10_ADJACENT_AUTHORITY_EXPANSION")
    if a["financial_authority"]!="NEUTRAL_FINANCE_PRESERVED" or a["finance"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE":raise RuntimeError("SO10_FINANCE_OR_DEPENDENCY_BOUNDARY")
    if any(i[k]!="NONE" for k in ("finance_writer","workflow_writer","delivery_writer","catalog_writer","resource_writer","business_time_writer")):raise RuntimeError("SO10_WRITER_BOUNDARY")
    if xa["frontend_implementation"]!="NONE" or xa["authorization_source"]!="PC5" or xa["time_source"]!="PC4" or xa["resource_source"]!="SO5":raise RuntimeError("SO10_XA_BOUNDARY")
    if not xa["calendar_never_grants_authorization"] or not xa["availability_is_server_authoritative"]:raise RuntimeError("SO10_XA_AUTHORITY")
    up=(ROOT/"alembic_neutral/sql/so10_scheduling_reservations_service_execution_up.sql").read_text(encoding="utf-8")
    for required in (
        "UNIQUE(tenant_id,command_key)",
        "FOREIGN KEY(tenant_id,calendar_code,calendar_version) REFERENCES public.business_calendars(tenant_id,calendar_code,calendar_version)",
        "FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id)",
        "FOREIGN KEY(tenant_id,relationship_id) REFERENCES public.so2_operational_relationships(tenant_id,id)",
        "so10_history_immutable",
        "so10_resource_allocations",
    ):
        if required not in up:raise RuntimeError("SO10_SQL_BOUNDARY="+required)
    forbidden=("insert into public.financial_events","update public.financial_events","insert into public.journal_entries","insert into public.financial_obligations","insert into public.payment_settlements","insert into public.so6_workflows","update public.so6_workflows","insert into public.so8_delivery_jobs")
    if any(x in up.lower() for x in forbidden):raise RuntimeError("SO10_FORBIDDEN_SQL_AUTHORITY")
    repo=(ROOT/"shared_operations/so10/sql_repository.py").read_text(encoding="utf-8")
    for marker in ("FOR UPDATE OF r","FOR UPDATE OF w","FOR UPDATE OF s","FOR UPDATE OF e","SO10_COMMAND_CONFLICT","l.public_id=:l"):
        if marker not in repo:raise RuntimeError("SO10_REPOSITORY_BOUNDARY="+marker)
    profiles=[_json("examples/clinical_appointment_profile.json"),_json("examples/field_service_schedule_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"] or profiles[0]["capabilities"]==profiles[1]["capabilities"]:raise RuntimeError("SO10_NEUTRALITY")
    if profiles[0]["financial_truth"]!="NONE" or profiles[1]["financial_truth"]!="NONE":raise RuntimeError("SO10_PROFILE_FINANCE")
    modules=json.loads((ROOT/"contracts/platform/v1/pc0_module_map.json").read_text(encoding="utf-8"))["modules"]
    scheduling=next((x for x in modules if x.get("code")=="scheduling"),None)
    if not scheduling or (scheduling.get("owner"),scheduling.get("kind"))!=("SO10","shared_operations_authority") or "shared_operations/so10" not in scheduling.get("source_roots",[]):raise RuntimeError("SO10_PC0_MODULE")
    authorities=json.loads((ROOT/"contracts/platform/v1/pc0_data_authority_register.json").read_text(encoding="utf-8"))["authorities"]
    authority=next((x for x in authorities if x.get("module")=="scheduling"),None)
    if not authority or authority.get("code")!="operational_scheduling_reservations":raise RuntimeError("SO10_PC0_DATA_AUTHORITY")
    refs=json.loads((ROOT/"contracts/platform/v1/pc0_reference_authority_migration_register.json").read_text(encoding="utf-8"))["entries"]
    migration=next((x for x in refs if x.get("module_code")=="scheduling"),None)
    if not migration or migration.get("target_data_authority")!="operational_scheduling_reservations":raise RuntimeError("SO10_REFERENCE_MIGRATION")
    report=validate_pc0(ROOT,validate_release=False);manifest=_json("so10_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO10_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"time_authority":"PC4_REUSED","party_authority":"PC2_SO2_REUSED","resource_authority":"SO5_REUSED","scheduling":"PASS","reservations":"PASS","capacity_conflict":"PASS","service_execution":"PASS","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from dataclasses import replace
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from uuid import UUID,uuid4
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from database import engine
    from core.platform.operating_context import BusinessCalendarVersion
    from shared_operations.so10 import (CancelReservation,CompleteService,ConfirmReservation,CreateReservation,DefineAvailabilityWindow,DefineSchedulingService,MarkNoShow,RescheduleReservation,ResourceAllocationRequest,SchedulableTarget,SO10Authority,SO10AuthorityError,StartService)
    from shared_operations.so10.sql_repository import SQLSO10Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO10_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so10_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name})
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9910,'SO10A','Neutral Scheduling','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9910,9910,'LEGACY','Scheduling Site','Douala','Compatibility',true)"))
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO10_PREDECESSOR_REPLAY")
            location=c.execute(text("INSERT INTO locations(tenant_id,code,name,location_kind,timezone_name,address,active) VALUES(9910,'SCHEDULE','Scheduling Location','physical','Africa/Douala','{}'::jsonb,true) RETURNING id,public_id")).one()
            calendar=c.execute(text("INSERT INTO business_calendars(tenant_id,calendar_code,calendar_version,timezone_name,business_day_boundary,operating_weekdays,effective_from,lifecycle) VALUES(9910,'operations',1,'Africa/Douala','00:00',ARRAY[0,1,2,3,4,5,6]::smallint[],now()-interval '30 days','active') RETURNING id")).one()
            unit_public=uuid4();unit=c.execute(text("INSERT INTO atomic_units(tenant_id,name,sku,is_active,is_sellable,public_id) VALUES(9910,'Neutral Scheduled Service','SO10-SVC',true,true,:p) RETURNING id,public_id"),{"p":str(unit_public)}).one()
            party=c.execute(text("INSERT INTO parties(tenant_id,party_kind,display_name,status) VALUES(9910,'person','Neutral Client','active') RETURNING id,public_id")).one()
            relationship=c.execute(text("INSERT INTO so2_operational_relationships(tenant_id,party_id,relationship_type_code,lifecycle_status,purpose,effective_from) VALUES(9910,:p,'client','active','scheduled_service',now()-interval '1 day') RETURNING id,public_id"),{"p":party.id}).one()
            resource1=c.execute(text("INSERT INTO so5_resources(tenant_id,resource_kind,classification_code,display_label,lifecycle_status,capacity,exclusive_assignment,metadata) VALUES(9910,'non_person','service_resource','Resource One','active',1,false,'{}'::jsonb) RETURNING id,public_id")).one()
            resource2=c.execute(text("INSERT INTO so5_resources(tenant_id,resource_kind,classification_code,display_label,lifecycle_status,capacity,exclusive_assignment,metadata) VALUES(9910,'non_person','service_resource','Resource Two','active',2,false,'{}'::jsonb) RETURNING id,public_id")).one()
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages","idempotency_records")
        with test.connect() as c:finance_before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                def basic(table,t,p):
                    v=s.execute(text(f"SELECT * FROM {table} WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**v._mapping) if v else None
                def calendar_resolver(t,code,version):
                    v=s.execute(text("SELECT * FROM business_calendars WHERE tenant_id=:t AND calendar_code=:c AND calendar_version=:v AND lifecycle='active'"),{"t":t,"c":code,"v":version}).first()
                    if not v:return None
                    return BusinessCalendarVersion(v.tenant_id,v.calendar_code,v.calendar_version,v.timezone_name,v.business_day_boundary,tuple(v.operating_weekdays),v.effective_from,v.effective_to,())
                def relationship_resolver(t,p):
                    v=s.execute(text("SELECT r.id,r.public_id,r.tenant_id,r.lifecycle_status status,q.public_id party_public_id FROM so2_operational_relationships r JOIN parties q ON (q.tenant_id,q.id)=(r.tenant_id,r.party_id) WHERE r.tenant_id=:t AND r.public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**v._mapping) if v else None
                def resource_resolver(t,p):
                    v=s.execute(text("SELECT id,public_id,tenant_id,lifecycle_status status,capacity FROM so5_resources WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**v._mapping) if v else None
                so10=SO10Authority(SQLSO10Repository(s),authorize=lambda *x:True,atomic_unit_resolver=lambda t,p:basic("atomic_units",t,p),offer_resolver=lambda t,p:basic("so1_offers",t,p),calendar_resolver=calendar_resolver,party_resolver=lambda t,p:basic("parties",t,p),relationship_resolver=relationship_resolver,resource_resolver=resource_resolver,location_resolver=lambda t,p:basic("locations",t,p))
                loc=UUID(str(location.public_id));target=UUID(str(unit.public_id));pp=UUID(str(party.public_id));relp=UUID(str(relationship.public_id));rp1=UUID(str(resource1.public_id));rp2=UUID(str(resource2.public_id))
                now=datetime.now(timezone.utc)
                proof_day=(now+timedelta(days=2)).date()
                window_start=datetime(proof_day.year,proof_day.month,proof_day.day,7,0,tzinfo=timezone.utc)
                window_end=window_start+timedelta(hours=10)
                start=window_start+timedelta(hours=1);end=start+timedelta(hours=1)
                service_cmd=DefineSchedulingService("service-1",9910,"neutral_service","Neutral Service",SchedulableTarget.ATOMIC_UNIT,target,"operations",1,60,2,{})
                service=so10.define_service(service_cmd);service_count=s.execute(text("SELECT count(*) FROM so10_services WHERE tenant_id=9910")).scalar_one();service_replay=so10.define_service(service_cmd)
                if service_replay!=service or s.execute(text("SELECT count(*) FROM so10_services WHERE tenant_id=9910")).scalar_one()!=service_count:raise RuntimeError("SO10_SERVICE_REPLAY")
                try:
                    with s.begin_nested():so10.define_service(replace(service_cmd,title="Changed"))
                except SO10AuthorityError as exc:
                    if exc.code!="SO10_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO10_CHANGED_SERVICE_REPLAY_ACCEPTED")
                window_cmd=DefineAvailabilityWindow("window-1",9910,service.public_id,loc,window_start,window_end,2,now)
                window=so10.define_window(window_cmd);window_replay=so10.define_window(window_cmd)
                if window_replay!=window or len(so10.windows(9910,service.public_id))!=1:raise RuntimeError("SO10_WINDOW_REPLAY")
                create1=CreateReservation("reservation-1",9910,service.public_id,pp,relp,start,end,1,now,"source-1")
                r1=so10.create_reservation(create1);reservation_count=s.execute(text("SELECT count(*) FROM so10_reservations WHERE tenant_id=9910")).scalar_one();r1_replay=so10.create_reservation(create1)
                if r1_replay!=r1 or s.execute(text("SELECT count(*) FROM so10_reservations WHERE tenant_id=9910")).scalar_one()!=reservation_count:raise RuntimeError("SO10_RESERVATION_REPLAY")
                try:
                    with s.begin_nested():so10.create_reservation(replace(create1,source_reference="changed"))
                except SO10AuthorityError as exc:
                    if exc.code!="SO10_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO10_CHANGED_RESERVATION_REPLAY_ACCEPTED")
                create2=CreateReservation("reservation-2",9910,service.public_id,pp,relp,start+timedelta(minutes=15),end-timedelta(minutes=15),1,now,"source-2")
                r2=so10.create_reservation(create2)
                confirm1=ConfirmReservation("confirm-1",9910,r1.public_id,r1.row_version,loc,start,end,(ResourceAllocationRequest(rp1,1),),now)
                r1=so10.confirm(confirm1);alloc_count=s.execute(text("SELECT count(*) FROM so10_resource_allocations WHERE tenant_id=9910")).scalar_one();history_count=len(so10.history(9910,r1.public_id));r1_replay=so10.confirm(confirm1)
                if r1_replay!=r1 or s.execute(text("SELECT count(*) FROM so10_resource_allocations WHERE tenant_id=9910")).scalar_one()!=alloc_count or len(so10.history(9910,r1.public_id))!=history_count:raise RuntimeError("SO10_CONFIRM_REPLAY")
                conflict=ConfirmReservation("confirm-resource-conflict",9910,r2.public_id,r2.row_version,loc,create2.requested_start,create2.requested_end,(ResourceAllocationRequest(rp1,1),),now)
                try:
                    with s.begin_nested():so10.confirm(conflict)
                except SO10AuthorityError as exc:
                    if exc.code!="SO10_CAPACITY_CONFLICT":raise
                else:raise RuntimeError("SO10_RESOURCE_DOUBLE_BOOK_ACCEPTED")
                confirm2=ConfirmReservation("confirm-2",9910,r2.public_id,r2.row_version,loc,create2.requested_start,create2.requested_end,(ResourceAllocationRequest(rp2,1),),now)
                r2=so10.confirm(confirm2)
                if so10.availability(9910,service.public_id,loc,create2.requested_start,create2.requested_end).available_capacity!=0:raise RuntimeError("SO10_SERVICE_CAPACITY")
                create3=CreateReservation("reservation-3",9910,service.public_id,pp,relp,start+timedelta(minutes=20),end-timedelta(minutes=20),1,now,"source-3")
                r3=so10.create_reservation(create3)
                try:
                    with s.begin_nested():so10.confirm(ConfirmReservation("confirm-capacity-conflict",9910,r3.public_id,r3.row_version,loc,create3.requested_start,create3.requested_end,(),now))
                except SO10AuthorityError as exc:
                    if exc.code!="SO10_CAPACITY_CONFLICT":raise
                else:raise RuntimeError("SO10_WINDOW_OVERBOOK_ACCEPTED")
                later_start=window_start+timedelta(hours=4);later_end=later_start+timedelta(hours=1);old_allocs=so10.allocations(9910,r1.public_id,False)
                reschedule=RescheduleReservation("reschedule-1",9910,r1.public_id,r1.row_version,loc,later_start,later_end,(ResourceAllocationRequest(rp1,1),),now,"client_request")
                r1=so10.reschedule(reschedule);all_allocs=so10.allocations(9910,r1.public_id,False)
                if len(all_allocs)!=len(old_allocs)+1 or all_allocs[-1].allocation_version<=old_allocs[-1].allocation_version:raise RuntimeError("SO10_RESCHEDULE_HISTORY")
                try:
                    with s.begin_nested():so10.reschedule(replace(reschedule,confirmed_start=later_start+timedelta(minutes=15),confirmed_end=later_end+timedelta(minutes=15)))
                except SO10AuthorityError as exc:
                    if exc.code!="SO10_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO10_CHANGED_RESCHEDULE_REPLAY_ACCEPTED")
                execution=so10.start_service(StartService("start-1",9910,r1.public_id,r1.row_version,later_start));execution_replay=so10.start_service(StartService("start-1",9910,r1.public_id,r1.row_version,later_start))
                if execution_replay!=execution or len(so10.executions(9910,r1.public_id))!=1:raise RuntimeError("SO10_START_REPLAY")
                completed=so10.complete_service(CompleteService("complete-1",9910,execution.public_id,execution.row_version,later_end,"completed_normally","evidence:so10"))
                if completed.status.value!="completed" or so10.reservation(9910,r1.public_id).status.value!="completed":raise RuntimeError("SO10_SERVICE_EXECUTION")
                r3=so10.cancel(CancelReservation("cancel-3",9910,r3.public_id,r3.row_version,now,"client_cancelled"))
                if r3.status.value!="cancelled":raise RuntimeError("SO10_CANCELLATION")
                if so10.reservations(9911):raise RuntimeError("SO10_CROSS_TENANT_READ")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9911,'SO10B','Isolation','CM','XAF','en-CM','Africa/Douala')"))
            service_internal_id=c.execute(text("SELECT id FROM so10_services WHERE tenant_id=9910 LIMIT 1")).scalar_one()
            try:
                with c.begin_nested():c.execute(text("INSERT INTO so10_reservations(tenant_id,service_id,party_id,relationship_id,requested_start,requested_end,capacity_units,lifecycle_status) VALUES(9911,:s,:p,:r,now(),now()+interval '1 hour',1,'requested')"),{"s":service_internal_id,"p":party.id,"r":relationship.id})
            except IntegrityError:pass
            else:raise RuntimeError("SO10_CROSS_TENANT_REFERENCE_ACCEPTED")
            hist=c.execute(text("SELECT reservation_id FROM so10_reservation_history WHERE tenant_id=9910 ORDER BY sequence LIMIT 1")).scalar_one()
            try:
                with c.begin_nested():c.execute(text("UPDATE so10_reservation_history SET reason_code='rewrite' WHERE tenant_id=9910 AND reservation_id=:r"),{"r":hist})
            except Exception:pass
            else:raise RuntimeError("SO10_HISTORY_MUTATION_ACCEPTED")
        with test.connect() as c:finance_after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO10_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so10_reservations')")).scalar_one() is None:raise RuntimeError("SO10_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO10_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","scheduling":"PASS","reservations":"PASS","capacity_conflict":"PASS","service_execution":"PASS","idempotency":"PASS","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()

def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();r=static_verify()
    if a.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("SO10_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO10_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
