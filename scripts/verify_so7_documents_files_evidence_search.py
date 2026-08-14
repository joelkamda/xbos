#!/usr/bin/env python3
"""Verify SO7 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="7fb3be466787144f1f0e09e930ef7bb6707418f0";PREVIOUS="so6_workflows_tasks_operational_approvals_031";HEAD="so7_documents_files_evidence_search_032"
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
    a=_json("so7_authority.json");l=_json("so7_legacy_adoption_manifest.json");i=_json("so7_public_interfaces.json");xa=_json("so7_xa_metadata.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO7_RELEASE_BOUNDARY")
    if {x["classification"] for x in l["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO7_LEGACY_DISCOVERY_INCOMPLETE")
    if (a["semantic_authority"],a["security_authority"],a["workflow_authority"])!=("PC3_REUSED","PC5_REUSED","SO6_EXTERNAL"):raise RuntimeError("SO7_COMPETING_AUTHORITY")
    if a["document_authority"]!="SO7_LOGICAL_DOCUMENT" or a["file_version_authority"]!="SO7_STORAGE_NEUTRAL" or a["evidence_link_authority"]!="SO7_REFERENCE_ONLY" or a["search_authority"]!="SO7_DERIVED_PROJECTION":raise RuntimeError("SO7_AUTHORITY_SHAPE")
    if a["storage_provider_authority"]!="ADAPTER_ONLY" or a["content_extraction_authority"]!="EXCLUDED" or a["communications_authority"]!="SO8_EXCLUDED" or a["reporting_automation_authority"]!="SO9_EXCLUDED" or a["scheduling_authority"]!="SO10_EXCLUDED":raise RuntimeError("SO7_BOUNDARY_EXPANSION")
    if a["finance"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE" or i["finance_writer"]!="NONE" or i["security_role_writer"]!="NONE" or i["pc5_audit_writer"]!="NONE" or i["workflow_writer"]!="NONE" or xa["frontend_implementation"]!="NONE":raise RuntimeError("SO7_WRITER_BOUNDARY")
    up=(ROOT/"alembic_neutral/sql/so7_documents_files_evidence_search_up.sql").read_text(encoding="utf-8")
    for required in ("UNIQUE(tenant_id,document_id,version_number)","REFERENCES public.so7_document_versions(tenant_id,document_id,id)","so7_version_immutable","CREATE VIEW public.so7_document_search_projection","content_sha256 char(64)"):
        if required not in up:raise RuntimeError("SO7_SQL_BOUNDARY="+required)
    if any(x in up.lower() for x in ("financial_events","journal_entries","financial_obligations","payment_settlements","audit_evidence","protected_action_approvals")):raise RuntimeError("SO7_FORBIDDEN_SQL_AUTHORITY")
    repo=(ROOT/"shared_operations/so7/sql_repository.py").read_text(encoding="utf-8")
    for marker in ("FOR UPDATE OF d","FOR UPDATE OF e","so7_document_search_projection"):
        if marker not in repo:raise RuntimeError("SO7_REPOSITORY_BOUNDARY="+marker)
    profiles=[_json("examples/field_service_evidence_profile.json"),_json("examples/clinical_document_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"] or profiles[0]["classifications"]==profiles[1]["classifications"]:raise RuntimeError("SO7_NEUTRALITY")
    report=validate_pc0(ROOT,validate_release=False);manifest=_json("so7_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO7_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"semantic_authority":"PC3_REUSED","security_authority":"PC5_REUSED","document_authority":"PASS","version_history":"PASS","content_integrity":"PASS","evidence_linkage":"PASS","search":"PASS","search_derived":"PASS","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from types import SimpleNamespace
    from dataclasses import replace
    from datetime import datetime,timezone
    from uuid import UUID
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import DBAPIError,IntegrityError
    from database import engine
    from shared_operations.so7 import (ChangeDocumentStatus,CreateDocument,DocumentStatus,EndEvidenceLink,EvidenceStatus,LinkEvidence,RegisterFileVersion,SO7Authority,SO7AuthorityError)
    from shared_operations.so7.sql_repository import SQLSO7Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO7_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so7_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9701,'SO7A','Neutral Evidence','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9701,9701,'LEGACY','Evidence Site','Douala','Compatibility',true)"))
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO7_PREDECESSOR_REPLAY")
            ns=c.execute(text("INSERT INTO semantic_namespaces(namespace_code,scope,owner_code,tenant_id,lifecycle) VALUES('so7_document_types_9701','tenant','SO7',9701,'active') RETURNING id")).scalar_one()
            c.execute(text("INSERT INTO semantic_concepts(namespace_id,code,lifecycle) VALUES(:n,'inspection_report','active')"),{"n":ns})
            workflow=c.execute(text("INSERT INTO so6_workflows(tenant_id,workflow_type_code,title,subject_authority,subject_reference) VALUES(9701,'inspection_case','Inspection','source_case','CASE-9701') RETURNING public_id")).scalar_one()
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages")
        with test.connect() as c:finance_before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                def classification(t,code):
                    return bool(s.execute(text("""SELECT 1 FROM semantic_concepts c JOIN semantic_namespaces n ON n.id=c.namespace_id WHERE c.code=:code AND c.lifecycle='active' AND n.lifecycle='active' AND (n.tenant_id IS NULL OR n.tenant_id=:t)"""),{"code":code,"t":t}).scalar())
                def subject(t,authority,reference):
                    if authority!="workflow":return False
                    try:p=UUID(reference)
                    except ValueError:return False
                    return bool(s.execute(text("SELECT 1 FROM so6_workflows WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).scalar())
                so7=SO7Authority(SQLSO7Repository(s),classification_resolver=classification,subject_resolver=subject,authorize=lambda *x:True)
                now=datetime.now(timezone.utc);dcmd=CreateDocument("document-1",9701,"Inspection Evidence","inspection_report",{"source":"acceptance"})
                d=so7.create_document(dcmd);count=s.execute(text("SELECT count(*) FROM so7_documents WHERE tenant_id=9701")).scalar_one();replay=so7.create_document(dcmd)
                if replay!=d or s.execute(text("SELECT count(*) FROM so7_documents WHERE tenant_id=9701")).scalar_one()!=count:raise RuntimeError("SO7_DOCUMENT_REPLAY")
                try:so7.create_document(replace(dcmd,title="Changed"))
                except SO7AuthorityError as exc:
                    if exc.code!="SO7_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO7_CHANGED_DOCUMENT_REPLAY_ACCEPTED")
                vcmd=RegisterFileVersion("version-1",9701,d.public_id,d.row_version,"inspection.pdf","application/pdf",256,"a"*64,"local","so7/inspection.pdf","identity:9701")
                v1=so7.register_version(vcmd);vcount=s.execute(text("SELECT count(*) FROM so7_document_versions WHERE tenant_id=9701")).scalar_one();vreplay=so7.register_version(vcmd)
                if vreplay!=v1 or s.execute(text("SELECT count(*) FROM so7_document_versions WHERE tenant_id=9701")).scalar_one()!=vcount:raise RuntimeError("SO7_VERSION_REPLAY")
                try:so7.register_version(replace(vcmd,content_sha256="b"*64))
                except SO7AuthorityError as exc:
                    if exc.code!="SO7_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO7_CHANGED_VERSION_REPLAY_ACCEPTED")
                d=so7.document(9701,d.public_id);v2cmd=RegisterFileVersion("version-2",9701,d.public_id,d.row_version,"inspection-v2.pdf","application/pdf",300,"b"*64,"local","so7/inspection-v2.pdf","identity:9701");v2=so7.register_version(v2cmd)
                if [x.version_number for x in so7.versions(9701,d.public_id)]!=[1,2] or so7.current_version(9701,d.public_id)!=v2:raise RuntimeError("SO7_VERSION_HISTORY")
                try:
                    with s.begin_nested():s.execute(text("UPDATE so7_document_versions SET file_name='rewritten.pdf' WHERE tenant_id=9701 AND public_id=:p"),{"p":str(v1.public_id)})
                except DBAPIError as exc:
                    if "append-only" not in str(exc).lower():raise
                else:raise RuntimeError("SO7_VERSION_MUTATION_ACCEPTED")
                d=so7.document(9701,d.public_id);ecmd=LinkEvidence("evidence-1",9701,d.public_id,d.row_version,"workflow",str(workflow),"supporting_evidence")
                e=so7.link_evidence(ecmd);ecount=s.execute(text("SELECT count(*) FROM so7_evidence_links WHERE tenant_id=9701")).scalar_one();ereplay=so7.link_evidence(ecmd)
                if ereplay!=e or s.execute(text("SELECT count(*) FROM so7_evidence_links WHERE tenant_id=9701")).scalar_one()!=ecount or e.version_public_id!=v2.public_id:raise RuntimeError("SO7_EVIDENCE_REPLAY_OR_VERSION")
                try:so7.link_evidence(replace(ecmd,relation_code="alternate"))
                except SO7AuthorityError as exc:
                    if exc.code!="SO7_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO7_CHANGED_EVIDENCE_REPLAY_ACCEPTED")
                hits=so7.search(9701,"inspection")
                if len(hits)!=1 or hits[0].document_public_id!=d.public_id:raise RuntimeError("SO7_SEARCH")
                e=so7.end_evidence(EndEvidenceLink("evidence-end",9701,e.public_id,e.row_version,"superseded",now))
                if e.status is not EvidenceStatus.ENDED or so7.evidence_for_subject(9701,"workflow",str(workflow)) or len(so7.evidence_for_subject(9701,"workflow",str(workflow),True))!=1:raise RuntimeError("SO7_EVIDENCE_HISTORY")
                d=so7.document(9701,d.public_id);d=so7.change_status(ChangeDocumentStatus("archive",9701,d.public_id,d.row_version,DocumentStatus.ARCHIVED,"inactive",now))
                if d.status is not DocumentStatus.ARCHIVED:raise RuntimeError("SO7_LIFECYCLE")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9702,'SO7B','Isolation','CM','XAF','en-CM','Africa/Douala')"))
            foreign_doc=c.execute(text("INSERT INTO so7_documents(tenant_id,title,classification_code) VALUES(9702,'Foreign','inspection_report') RETURNING id")).scalar_one()
            version_id=c.execute(text("SELECT id FROM so7_document_versions WHERE tenant_id=9701 ORDER BY version_number LIMIT 1")).scalar_one()
            try:
                with c.begin_nested():c.execute(text("INSERT INTO so7_evidence_links(tenant_id,document_id,version_id,subject_authority,subject_reference,relation_code) VALUES(9702,:d,:v,'workflow','foreign','supporting')"),{"d":foreign_doc,"v":version_id})
            except IntegrityError:pass
            else:raise RuntimeError("SO7_CROSS_TENANT_VERSION_LINK_ACCEPTED")
            leaked=c.execute(text("SELECT count(*) FROM so7_document_search_projection WHERE tenant_id=9702 AND title ILIKE '%Inspection Evidence%'" )).scalar_one()
            if leaked:raise RuntimeError("SO7_SEARCH_TENANT_LEAK")
        with test.connect() as c:finance_after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO7_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so7_documents')")).scalar_one() is None:raise RuntimeError("SO7_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO7_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","document_authority":"PASS","version_history":"PASS","content_integrity":"PASS","evidence_linkage":"PASS","search":"PASS","search_derived":"PASS","idempotency":"PASS","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()
def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();r=static_verify()
    if a.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("SO7_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO7_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
