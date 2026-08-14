#!/usr/bin/env python3
"""Verify SO5 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="087a6d9c5f8c555788cbbd2718b24c5dea73074a";PREVIOUS="so4_procurement_supplier_operations_029";HEAD="so5_resources_operational_assignment_030"
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
    a=_json("so5_authority.json");l=_json("so5_legacy_adoption_manifest.json");i=_json("so5_public_interfaces.json");xa=_json("so5_xa_metadata.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO5_RELEASE_BOUNDARY")
    if {x["classification"] for x in l["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO5_LEGACY_DISCOVERY_INCOMPLETE")
    if (a["party_authority"],a["identity_authority"],a["structure_authority"])!=("PC2_REUSED","PC5_SEPARATE","PC1_REUSED"):raise RuntimeError("SO5_COMPETING_AUTHORITY")
    if a["workflow_authority"]!="SO6_EXCLUDED" or a["scheduling_authority"]!="SO10_EXCLUDED" or a["finance"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE":raise RuntimeError("SO5_BOUNDARY_EXPANSION")
    if i["finance_writer"]!="NONE" or i["security_role_writer"]!="NONE" or xa["frontend_implementation"]!="NONE":raise RuntimeError("SO5_WRITER_BOUNDARY")
    up=(ROOT/"alembic_neutral/sql/so5_resources_operational_assignment_up.sql").read_text(encoding="utf-8")
    for required in ("REFERENCES public.parties(tenant_id,id)","REFERENCES public.organization_units(tenant_id,id)","REFERENCES public.locations(tenant_id,id)","identity_memberships","so5_history_immutable"):
        if required not in up:raise RuntimeError("SO5_SQL_BOUNDARY="+required)
    if any(x in up.lower() for x in ("financial_events","journal_entries","financial_obligations","payment_settlements","payroll","commission")):raise RuntimeError("SO5_FINANCE_SQL_FORBIDDEN")
    repo=(ROOT/"shared_operations/so5/sql_repository.py").read_text(encoding="utf-8")
    if "FOR UPDATE OF r" not in repo or "FOR UPDATE OF a" not in repo:raise RuntimeError("SO5_LOCK_SCOPE")
    profiles=[_json("examples/field_service_resources_profile.json"),_json("examples/clinical_resources_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"]:raise RuntimeError("SO5_NEUTRALITY")
    report=validate_pc0(ROOT,validate_release=False);manifest=_json("so5_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO5_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"party_authority":"PC2_REUSED","identity_authority":"PC5_SEPARATE","structure_authority":"PC1_REUSED","resource_authority":"PASS","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

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
    from database import engine
    from shared_operations.so5 import CreateResource,ResourceKind,AssignResource,EndAssignment,SO5Authority,SO5AuthorityError
    from shared_operations.so5.sql_repository import SQLSO5Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO5_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so5_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9501,'SO5A','Neutral Resources','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9501,9501,'LEGACY','Operations Site','Douala','Compatibility',true)"))
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO5_PREDECESSOR_REPLAY")
            party=c.execute(text("INSERT INTO parties(tenant_id,party_kind,display_name) VALUES(9501,'person','Neutral Technician') RETURNING id,public_id")).one()
            c.execute(text("INSERT INTO persons(tenant_id,party_id,given_name,family_name) VALUES(9501,:p,'Neutral','Technician')"),{"p":party.id})
            ident=c.execute(text("INSERT INTO identities(login_name,status,party_id) VALUES('so5-tech@example.invalid','active',:p) RETURNING id,public_id"),{"p":party.id}).one()
            c.execute(text("INSERT INTO identity_memberships(identity_id,tenant_id,party_id,status,invitation_state,valid_from) VALUES(:i,9501,:p,'active','accepted',now())"),{"i":ident.id,"p":party.id})
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages")
        with test.connect() as c:finance_before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                def row(table,t,p):
                    v=s.execute(text(f"SELECT * FROM {table} WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**v._mapping) if v else None
                pp=UUID(str(s.execute(text("SELECT public_id FROM parties WHERE tenant_id=9501")).scalar_one()));ip=UUID(str(s.execute(text("SELECT public_id FROM identities WHERE login_name='so5-tech@example.invalid'")).scalar_one()))
                op=UUID(str(s.execute(text("SELECT public_id FROM organization_units WHERE tenant_id=9501 ORDER BY id LIMIT 1")).scalar_one()));lp=UUID(str(s.execute(text("SELECT public_id FROM locations WHERE tenant_id=9501 ORDER BY id LIMIT 1")).scalar_one()))
                def identity(t,p):
                    v=s.execute(text("SELECT i.public_id,m.tenant_id,q.public_id party_public_id FROM identities i JOIN identity_memberships m ON m.identity_id=i.id JOIN parties q ON (q.tenant_id,q.id)=(m.tenant_id,m.party_id) WHERE m.tenant_id=:t AND i.public_id=:p AND m.status='active'"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**v._mapping) if v else None
                so5=SO5Authority(SQLSO5Repository(s),party_resolver=lambda t,p:row("parties",t,p),identity_resolver=identity,organization_resolver=lambda t,p:row("organization_units",t,p),location_resolver=lambda t,p:row("locations",t,p),authorize=lambda *x:True)
                person_cmd=CreateResource("person-1",9501,ResourceKind.PERSON,"technician","Neutral Technician",pp,ip,op,lp,1,True)
                person=so5.create_resource(person_cmd); effects=s.execute(text("SELECT count(*) FROM so5_resources WHERE tenant_id=9501")).scalar_one();replay=so5.create_resource(person_cmd)
                if replay!=person or s.execute(text("SELECT count(*) FROM so5_resources WHERE tenant_id=9501")).scalar_one()!=effects:raise RuntimeError("SO5_RESOURCE_REPLAY")
                try:so5.create_resource(replace(person_cmd,display_label="Changed"))
                except SO5AuthorityError as exc:
                    if exc.code!="SO5_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO5_CHANGED_REPLAY_ACCEPTED")
                machine=so5.create_resource(CreateResource("machine-1",9501,ResourceKind.NON_PERSON,"diagnostic_equipment","Analyzer",None,None,op,lp,2,False))
                if machine.party_public_id is not None or machine.identity_public_id is not None:raise RuntimeError("SO5_FAKE_PARTY")
                person=so5.resource(9501,person.public_id);now=datetime.now(timezone.utc);cmd=AssignResource("assign-1",9501,person.public_id,person.row_version,"field_service",now,now+timedelta(hours=8),op,lp)
                a=so5.assign(cmd);replay_a=so5.assign(cmd)
                if replay_a!=a or len(so5.assignments(9501,person.public_id))!=1:raise RuntimeError("SO5_ASSIGNMENT_REPLAY")
                person=so5.resource(9501,person.public_id)
                try:so5.assign(AssignResource("overlap",9501,person.public_id,person.row_version,"field_service",now+timedelta(hours=1),now+timedelta(hours=2),op,lp))
                except SO5AuthorityError as exc:
                    if exc.code!="SO5_ASSIGNMENT_CONFLICT":raise
                else:raise RuntimeError("SO5_EXCLUSIVE_OVERLAP_ACCEPTED")
                ended=so5.end_assignment(EndAssignment("end-1",9501,a.public_id,a.row_version,now+timedelta(hours=4),"completed"))
                if ended.status.value!="ended" or not so5.history(9501,person.public_id):raise RuntimeError("SO5_HISTORY")
        with test.begin() as c:
            from sqlalchemy.exc import IntegrityError
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9502,'SO5B','Isolation','CM','XAF','en-CM','Africa/Douala')"))
            try:
                with c.begin_nested():c.execute(text("INSERT INTO so5_resources(tenant_id,resource_kind,classification_code,display_label,party_id,lifecycle_status) VALUES(9502,'person','tech','Cross',:p,'active')"),{"p":party.id})
            except IntegrityError:pass
            else:raise RuntimeError("SO5_CROSS_TENANT_PARTY_ACCEPTED")
            try:
                with c.begin_nested():c.execute(text("INSERT INTO so5_resources(tenant_id,resource_kind,classification_code,display_label,party_id,identity_id,lifecycle_status) VALUES(9502,'person','tech','Cross Identity',NULL,:i,'active')"),{"i":ident.id})
            except Exception:pass
            else:raise RuntimeError("SO5_CROSS_TENANT_IDENTITY_ACCEPTED")
        with test.connect() as c:finance_after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO5_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so5_resources')")).scalar_one() is None:raise RuntimeError("SO5_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO5_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","resource_authority":"PASS","non_person_resource":"PASS","assignment":"PASS","assignment_history":"PASS","idempotency":"PASS","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()
def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();r=static_verify()
    if a.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("SO5_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO5_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
