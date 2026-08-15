#!/usr/bin/env python3
"""Verify PK0-PK3 and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="da61371b9378d6406fe5d6fce8611f77d40b72ef";PREVIOUS="so_aggregate_conformance_hardening_036";HEAD="pk0123_pack_manifest_lifecycle_037"
CONTRACTS=ROOT/"contracts/packs/v1"
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
    a=_json("pk0123_authority.json");i=_json("pk0123_public_interfaces.json")
    if (a["source_checkpoint"],a["previous_head"],a["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("PK0123_RELEASE_BOUNDARY")
    if a["scope"]!=["PK0","PK1","PK2","PK3"] or a["constitutional_rule"]!="pack_is_composition_not_authority":raise RuntimeError("PK0123_SCOPE")
    if a["finance"]!="UNCHANGED" or a["shared_operations"]!="UNCHANGED" or a["production_dependency_changes"]!="NONE":raise RuntimeError("PK0123_BOUNDARY")
    if "pack_platform.PackAuthority" not in i["public"]:raise RuntimeError("PK0123_PUBLIC_INTERFACE")
    up=(ROOT/"alembic_neutral/sql/pk0123_pack_manifest_lifecycle_up.sql").read_text(encoding="utf-8").lower()
    for marker in ("uq_pk_pack_commands_scope","pk_pack_version_immutable","pk_pack_installation_history","pk_history_immutable","pk_connector_declarations","public_interface !~*"):
        if marker not in up:raise RuntimeError("PK0123_SQL_BOUNDARY="+marker)
    forbidden=("insert into public.financial_events","update public.financial_events","insert into public.journal_entries","insert into public.payment_settlements","insert into public.permission_definitions","insert into public.semantic_concepts","update public.core_modules")
    if any(x in up for x in forbidden):raise RuntimeError("PK0123_FORBIDDEN_AUTHORITY_WRITE")
    module_map=json.loads((ROOT/"contracts/platform/v1/pc0_module_map.json").read_text(encoding="utf-8"));packs=next((x for x in module_map["modules"] if x.get("code")=="packs"),None)
    if not packs or packs.get("owner")!="PK" or packs.get("kind")!="pack_composition_authority":raise RuntimeError("PK0123_PC0_MODULE")
    auth=json.loads((ROOT/"contracts/platform/v1/pc0_data_authority_register.json").read_text(encoding="utf-8"));pa=next((x for x in auth["authorities"] if x.get("code")=="pack_composition"),None)
    if not pa or pa.get("owner")!="PK":raise RuntimeError("PK0123_PC0_AUTHORITY")
    refs=json.loads((ROOT/"contracts/platform/v1/pc0_reference_authority_migration_register.json").read_text(encoding="utf-8"));
    if not any(x.get("reference")=="pack_lifecycle" for x in refs["entries"]):raise RuntimeError("PK0123_REFERENCE_REGISTER")
    connector=_json("examples/neutral_payment_provider_connector.json")
    if connector["financial_truth"]!="NONE" or connector["settlement_owner"]!="Neutral Finance":raise RuntimeError("PK0123_CONNECTOR_FINANCE_BOUNDARY")
    if set(connector["finality_policy"].values())!={"submitted","pending","failed","ambiguous","provider_final"}:raise RuntimeError("PK0123_CONNECTOR_FINALITY")
    country=_json("examples/neutral_country_pack.json")
    if country["financial_truth"]!="NONE" or country["runtime_dynamic_import"] is not False:raise RuntimeError("PK0123_COUNTRY_NEUTRALITY")
    report=validate_pc0(ROOT,validate_release=False)
    manifest=_json("pk0123_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("PK0123_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"manifest":"PASS","lifecycle":"PASS","public_extensions":"PASS","connector_contract":"PASS","finance":"UNCHANGED","shared_operations":"UNCHANGED","dependencies":"UNCHANGED","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}
def database_acceptance():
    from dataclasses import replace
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session
    from database import engine
    from pack_platform import (ActivatePack,ConnectorDeclaration,ConnectorKind,DisablePack,ExecutionState,ExtensionKind,InstallPack,PackAuthority,PackDependency,PackExtension,PackKind,PackManifest,PackStatus,ProviderIdempotency,RegisterPackVersion,RemovePack,StagePack)
    from pack_platform.sql_repository import SQLPackRepository
    from pack_platform.service import PackAuthorityError
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("PK0123_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_pk0123_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages","idempotency_records")
    try:
        drop();
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("PK0123_PREDECESSOR_REPLAY")
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(12001,'PKA','Pack Tenant A','CM','XAF','en-CM','Africa/Douala'),(12002,'PKB','Pack Tenant B','CM','XAF','en-CM','Africa/Douala')"))
            before=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
        _run(command.upgrade,cfg,rendered,HEAD)
        with Session(test) as s, s.begin():
            repo=SQLPackRepository(s);authority=PackAuthority(repo)
            dep=PackManifest("neutral.foundation","1.0.0","pk",PackKind.CAPABILITY,"1.0.0")
            d=authority.register(RegisterPackVersion("register-foundation",dep));d2=authority.register(RegisterPackVersion("register-foundation",dep))
            if d2!=d:raise RuntimeError("PK0123_REGISTER_REPLAY")
            try:
                with s.begin_nested():authority.register(RegisterPackVersion("register-foundation",replace(dep,owner_code="other")))
            except PackAuthorityError as exc:
                if exc.code!="PK_COMMAND_CONFLICT":raise
            else:raise RuntimeError("PK0123_CHANGED_REPLAY_ACCEPTED")
            payout=ConnectorDeclaration("payout.example",ConnectorKind.PAYMENT_PROVIDER,"example",("payout",),ProviderIdempotency.EXTERNAL_REFERENCE,True,"provider_event_id",{"accepted":ExecutionState.SUBMITTED,"processing":ExecutionState.PENDING,"failed":ExecutionState.FAILED,"timeout":ExecutionState.AMBIGUOUS,"credited":ExecutionState.PROVIDER_FINAL},("provider_beneficiary_token",),("example.credentials",),"lookup_external_reference_then_manual_hold","sanitized_or_encrypted_only")
            app=PackManifest("neutral.payments","1.0.0","pk",PackKind.CAPABILITY,"1.0.0",dependencies=(PackDependency("neutral.foundation","1.0.0"),),connectors=(payout,),extensions=(PackExtension("finance.conformance",ExtensionKind.FINANCE_CONFORMANCE,"Neutral Finance","core.domain.finance.pack_conformance_service",{}),))
            authority.register(RegisterPackVersion("register-payments",app))
            try:
                with s.begin_nested():authority.stage(StagePack("stage-payments-missing-dep",12001,"neutral.payments","1.0.0"))
            except PackAuthorityError as exc:
                if exc.code!="PK_DEPENDENCY_NOT_INSTALLED":raise
            else:raise RuntimeError("PK0123_MISSING_DEPENDENCY_ACCEPTED")
            f=authority.stage(StagePack("stage-foundation",12001,"neutral.foundation","1.0.0"));f=authority.install(InstallPack("install-foundation",12001,"neutral.foundation","1.0.0",f.row_version));f=authority.activate(ActivatePack("activate-foundation",12001,"neutral.foundation","1.0.0",f.row_version))
            p=authority.stage(StagePack("same-command-key",12001,"neutral.payments","1.0.0"));replay=authority.stage(StagePack("same-command-key",12001,"neutral.payments","1.0.0"))
            if replay!=p or len(repo.history(12001,"neutral.payments"))!=1:raise RuntimeError("PK0123_STAGE_REPLAY")
            # same command key in another tenant is valid tenant-scoped idempotency
            f2=authority.stage(StagePack("stage-foundation-b",12002,"neutral.foundation","1.0.0"));f2=authority.install(InstallPack("install-foundation-b",12002,"neutral.foundation","1.0.0",f2.row_version));f2=authority.activate(ActivatePack("activate-foundation-b",12002,"neutral.foundation","1.0.0",f2.row_version))
            p2=authority.stage(StagePack("same-command-key",12002,"neutral.payments","1.0.0"))
            if p2.tenant_id!=12002:raise RuntimeError("PK0123_TENANT_IDEMPOTENCY")
            p=authority.install(InstallPack("install-payments",12001,"neutral.payments","1.0.0",p.row_version));p=authority.activate(ActivatePack("activate-payments",12001,"neutral.payments","1.0.0",p.row_version));p=authority.disable(DisablePack("disable-payments",12001,"neutral.payments",p.row_version,"operator_disable"))
            try:
                with s.begin_nested():authority.remove(RemovePack("remove-payments",12001,"neutral.payments",p.row_version,False,"remove"))
            except PackAuthorityError as exc:
                if exc.code!="PK_RETENTION_REQUIRED":raise
            else:raise RuntimeError("PK0123_RETENTION_BYPASS")
            p=authority.remove(RemovePack("remove-payments-retain",12001,"neutral.payments",p.row_version,True,"remove_retain"))
            if p.status is not PackStatus.REMOVED:raise RuntimeError("PK0123_REMOVE")
            hist=repo.history(12001,"neutral.payments")
            if [x.to_status.value for x in hist] != ["staged","installed","active","disabled","removed"]:raise RuntimeError("PK0123_HISTORY")
        with test.begin() as c:
            hid=c.execute(text("SELECT id FROM pk_pack_installation_history LIMIT 1")).scalar_one()
            try:
                with c.begin_nested():c.execute(text("UPDATE pk_pack_installation_history SET reason='rewrite' WHERE id=:i"),{"i":hid})
            except DBAPIError:pass
            else:raise RuntimeError("PK0123_HISTORY_MUTATION_ACCEPTED")
            after=tuple((n,c.execute(text(f"SELECT count(*) FROM {n}")).scalar_one()) for n in finance_tables)
            if after!=before:raise RuntimeError("PK0123_FINANCIAL_EFFECTS_CHANGED")
        _run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        with test.connect() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=HEAD or c.execute(text("SELECT to_regclass('public.pk_packs')")).scalar_one() is None:raise RuntimeError("PK0123_REUPGRADE")
        with engine.connect() as c:dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        devurl=url.render_as_string(hide_password=False)
        if dev==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),devurl,HEAD)
        elif dev==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.pk_packs')")).scalar_one() is None:raise RuntimeError("PK0123_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("PK0123_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","manifest":"PASS","lifecycle":"PASS","dependency_enforcement":"PASS","tenant_idempotency":"PASS","history_immutability":"PASS","connector_contract":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()
def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");args=p.parse_args();r=static_verify()
    if args.acceptance:r.update(database_acceptance())
    print(json.dumps(r,indent=2,sort_keys=True));print("PK0123_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as exc:print("PK0123_VERIFY=FAIL\n"+str(exc));raise SystemExit(1)
