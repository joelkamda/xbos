#!/usr/bin/env python3
"""Verify SO4 statically and perform controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
SOURCE="903e0e945b3659cffb03b1cdeaded38de2e7ce1d";PREVIOUS="so3_inventory_stock_movement_028";HEAD="so4_procurement_supplier_operations_029"
CONTRACTS=ROOT/"contracts/shared_operations/v1"
def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))
def _canonical(path):return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def _set_url(config,url):config.set_main_option("sqlalchemy.url",url.replace("%","%%"))
def _run(operation,config,url,target):
    old={k:os.environ.get(k) for k in ("DATABASE_URL","MIGRATION_DATABASE_URL")};_set_url(config,url);os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
    try:operation(config,target)
    finally:
        for k,v in old.items():os.environ.pop(k,None) if v is None else os.environ.__setitem__(k,v)

def _verify_fk_law(sql):
    required=("REFERENCES public.parties(tenant_id,id)","REFERENCES public.so2_operational_relationships(tenant_id,id)","REFERENCES public.atomic_units(tenant_id,id)","REFERENCES public.so3_stock_locations(tenant_id,id)","REFERENCES public.inventory_movements(tenant_id,public_id)")
    if not all(x in sql for x in required):raise RuntimeError("SO4_TENANT_QUALIFIED_FK_COVERAGE")
    if any(x in sql for x in ("REFERENCES public.parties(id)","REFERENCES public.atomic_units(id)","REFERENCES public.so3_stock_locations(id)")):raise RuntimeError("SO4_CROSS_TENANT_FK_WEAKENED")

def _verify_lock_law(source):
    joined_locks=[line for line in source.splitlines() if "JOIN" in line and "FOR UPDATE" in line]
    if len(joined_locks)!=1 or "FOR UPDATE OF l" not in joined_locks[0]:raise RuntimeError("SO4_JOINED_LOCK_SCOPE")
    if any(token in joined_locks[0] for token in ("FOR UPDATE OF u","FOR UPDATE OF s","FOR UPDATE OF loc")):raise RuntimeError("SO4_NULLABLE_METADATA_LOCK")
    if source.index("SELECT * FROM so4_purchase_orders WHERE tenant_id=:t AND public_id=:p FOR UPDATE")>source.index("FOR UPDATE OF l"):raise RuntimeError("SO4_RECEIPT_LOCK_ORDER")

def static_verify():
    from core.platform.architecture_contract import validate_pc0
    authority=_json("so4_authority.json");legacy=_json("so4_legacy_adoption_manifest.json");interfaces=_json("so4_public_interfaces.json");xa=_json("so4_xa_metadata.json")
    if (authority["source_checkpoint"],authority["previous_head"],authority["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("SO4_RELEASE_BOUNDARY")
    if {x["classification"] for x in legacy["decisions"]}!={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}:raise RuntimeError("SO4_LEGACY_DISCOVERY_INCOMPLETE")
    if authority["supplier_authority"]!="PC2_PARTY_PLUS_SO2_RELATIONSHIP" or authority["atomic_unit_authority"]!="SO1_REUSED" or authority["inventory_authority"]!="SO3_PUBLIC_CONTRACT_REUSED":raise RuntimeError("SO4_COMPETING_AUTHORITY")
    if interfaces["finance_writer"]!="NONE" or authority["production_dependency_changes"]!="NONE" or xa["frontend_implementation"]!="NONE":raise RuntimeError("SO4_BOUNDARY_EXPANSION")
    up=(ROOT/"alembic_neutral/sql/so4_procurement_supplier_operations_up.sql").read_text(encoding="utf-8");_verify_fk_law(up)
    _verify_lock_law((ROOT/"shared_operations/so4/sql_repository.py").read_text(encoding="utf-8"))
    if any(x in up.lower() for x in ("insert into public.financial_","update public.financial_","journal_entries","financial_obligations","payment_settlements")):raise RuntimeError("SO4_FINANCE_SQL_FORBIDDEN")
    if not all(x in up for x in ("so4_purchase_requests","so4_purchase_orders","so4_operational_receipts","so4_procurement_history_immutable")):raise RuntimeError("SO4_MIGRATION_COVERAGE")
    profiles=[_json("examples/retail_merchandise_procurement_profile.json"),_json("examples/clinical_service_supply_procurement_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"] or profiles[0]["service_procurement"]==profiles[1]["service_procurement"]:raise RuntimeError("SO4_NEUTRALITY")
    report=validate_pc0(ROOT,validate_release=False)
    manifest=_json("so4_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError("SO4_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"supplier_authority":"PC2_SO2_REUSED","atomic_unit_authority":"SO1_REUSED","inventory_authority":"SO3_REUSED","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"xa":"PASS","pc0":report["status"],"release_artifacts":len(manifest["artifacts"])}

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
    from shared_operations.so3 import SO3Authority
    from shared_operations.so3.sql_repository import SQLSO3Repository
    from shared_operations.so4 import CreatePurchaseOrder,LineType,ProcurementLineInput,ProcurementStatus,ReceiptLineInput,ReceivePurchaseOrder,SO4Authority,SO4AuthorityError,TransitionProcurement
    from shared_operations.so4.sql_repository import SQLSO4Repository
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev":raise RuntimeError("SO4_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    name="xbos_shared_operations_so4_test";admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT");test=None
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
        test=create_engine(url.set(database=name));cfg=Config(str(ROOT/"alembic_neutral.ini"));rendered=url.set(database=name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9401,'SO4A','Neutral Procurement','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9401,9401,'LEGACY','Receiving Site','Douala','Compatibility',true)"))
            c.execute(text("INSERT INTO atomic_units(id,tenant_id,name,sku,unit_type,is_active,is_sellable) VALUES(9401,9401,'Neutral Supply','SO4-U','each',true,true)"))
            item=c.execute(text("INSERT INTO inventory_items(id,tenant_id,branch_id,atomic_unit_id,quantity_on_hand,reorder_level) VALUES(9401,9401,9401,9401,7,2) RETURNING id")).scalar_one()
            c.execute(text("INSERT INTO inventory_movements(id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,quantity_delta,movement_type,source,reference_type,reference_id) VALUES(9401,9401,9401,:i,9401,7,'receipt','legacy','fixture',9401)"),{"i":item})
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.begin() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS:raise RuntimeError("SO4_PREDECESSOR_REPLAY")
            party=c.execute(text("INSERT INTO parties(tenant_id,party_kind,display_name) VALUES(9401,'organization','Neutral Supplier') RETURNING id,public_id")).one()
            c.execute(text("INSERT INTO organization_parties(tenant_id,party_id,legal_name) VALUES(9401,:p,'Neutral Supplier')"),{"p":party.id})
            rel=c.execute(text("INSERT INTO so2_operational_relationships(tenant_id,party_id,relationship_type_code,lifecycle_status,effective_from) VALUES(9401,:p,'supplier','active',now()) RETURNING id,public_id"),{"p":party.id}).one()
        _run(command.upgrade,cfg,rendered,HEAD);_run(command.downgrade,cfg,rendered,PREVIOUS);_run(command.upgrade,cfg,rendered,HEAD)
        finance_tables=("financial_events","journal_entries","financial_obligations","payment_settlements","outbox_messages")
        with test.connect() as c:finance_before=tuple((name,c.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()) for name in finance_tables)
        with test.begin() as c:
            from sqlalchemy.exc import IntegrityError
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9402,'SO4B','Isolation Tenant','CM','XAF','en-CM','Africa/Douala')"))
            try:
                with c.begin_nested():c.execute(text("INSERT INTO so4_purchase_orders(tenant_id,order_code,supplier_party_id,supplier_relationship_id,lifecycle_status) VALUES(9402,'CROSS',:p,:r,'draft')"),{"p":party.id,"r":rel.id})
            except IntegrityError:pass
            else:raise RuntimeError("SO4_CROSS_TENANT_FK_ACCEPTED")
        with Session(test,expire_on_commit=False) as s:
            with s.begin():
                def row(table,t,p,extra=""):
                    value=s.execute(text(f"SELECT * {extra} FROM {table} WHERE tenant_id=:t AND public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**value._mapping) if value else None
                party_public=UUID(str(s.execute(text("SELECT public_id FROM parties WHERE tenant_id=9401")).scalar_one()));rel_public=UUID(str(s.execute(text("SELECT public_id FROM so2_operational_relationships WHERE tenant_id=9401")).scalar_one()));unit_public=UUID(str(s.execute(text("SELECT public_id FROM atomic_units WHERE tenant_id=9401 AND id=9401")).scalar_one()));stock_public=UUID(str(s.execute(text("SELECT public_id FROM so3_stock_locations WHERE tenant_id=9401")).scalar_one()))
                def rel_resolver(t,p):
                    x=s.execute(text("SELECT r.*,q.public_id party_public_id,r.lifecycle_status status FROM so2_operational_relationships r JOIN parties q ON q.id=r.party_id WHERE r.tenant_id=:t AND r.public_id=:p"),{"t":t,"p":str(p)}).first();return SimpleNamespace(**x._mapping) if x else None
                atomic=lambda t,p:row("atomic_units",t,p);stock=lambda t,p:row("so3_stock_locations",t,p)
                location=lambda t,p:row("locations",t,p);so3=SO3Authority(SQLSO3Repository(s),atomic_unit_resolver=atomic,location_resolver=location,authorize=lambda *x:True)
                so4=SO4Authority(SQLSO4Repository(s),party_resolver=lambda t,p:row("parties",t,p),relationship_resolver=rel_resolver,atomic_unit_resolver=atomic,stock_location_resolver=stock,inventory_authority=so3,authorize=lambda *x:True,approval_validator=lambda *x:True)
                order=so4.create_order(CreatePurchaseOrder("create",9401,"PO-1",party_public,rel_public,(ProcurementLineInput(1,LineType.STOCK,"Neutral Supply",10,unit_public,stock_public),)))
                for key,status in (("submit",ProcurementStatus.SUBMITTED),("approve",ProcurementStatus.APPROVED),("order",ProcurementStatus.ORDERED)):
                    order=so4.transition_order(TransitionProcurement(key,9401,order.public_id,order.row_version,status,key,datetime.now(timezone.utc),UUID(int=44) if status is ProcurementStatus.APPROVED else None))
                line=order.lines[0]
                receive_1=ReceivePurchaseOrder("receive-1",9401,order.public_id,"GR-1",(ReceiptLineInput(line.public_id,4),),datetime.now(timezone.utc))
                first=so4.receive(receive_1)
                first_effects=(s.execute(text("SELECT count(*) FROM so4_operational_receipts WHERE tenant_id=9401")).scalar_one(),s.execute(text("SELECT count(*) FROM inventory_movements WHERE tenant_id=9401 AND source='so4-procurement'")).scalar_one(),s.execute(text("SELECT quantity_on_hand FROM inventory_items WHERE tenant_id=9401 AND atomic_unit_id=9401")).scalar_one())
                replay=so4.receive(receive_1)
                if first!=replay:raise RuntimeError("SO4_RECEIPT_REPLAY")
                replay_effects=(s.execute(text("SELECT count(*) FROM so4_operational_receipts WHERE tenant_id=9401")).scalar_one(),s.execute(text("SELECT count(*) FROM inventory_movements WHERE tenant_id=9401 AND source='so4-procurement'")).scalar_one(),s.execute(text("SELECT quantity_on_hand FROM inventory_items WHERE tenant_id=9401 AND atomic_unit_id=9401")).scalar_one())
                if replay_effects!=first_effects:raise RuntimeError("SO4_RECEIPT_REPLAY_DUPLICATED_EFFECT")
                try:so4.receive(replace(receive_1,occurred_at=receive_1.occurred_at+timedelta(microseconds=1)))
                except SO4AuthorityError as exc:
                    if exc.code!="SO4_COMMAND_CONFLICT":raise
                else:raise RuntimeError("SO4_CHANGED_COMMAND_REPLAY_ACCEPTED")
                order=so4.order(9401,order.public_id);so4.receive(ReceivePurchaseOrder("receive-2",9401,order.public_id,"GR-2",(ReceiptLineInput(line.public_id,6),),datetime.now(timezone.utc)))
                quantity=s.execute(text("SELECT quantity_on_hand FROM inventory_items WHERE tenant_id=9401 AND atomic_unit_id=9401")).scalar_one();order=so4.order(9401,order.public_id)
                if quantity!=17 or order.status is not ProcurementStatus.RECEIVED or order.lines[0].outstanding_quantity!=0:raise RuntimeError("SO4_RECEIPT_QUANTITY_PROOF")
        with test.connect() as c:finance_after=tuple((name,c.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()) for name in finance_tables)
        if finance_after!=finance_before:raise RuntimeError("SO4_FINANCIAL_EFFECTS_CHANGED")
        with engine.connect() as c:dev=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if dev==PREVIOUS:_run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),url.render_as_string(hide_password=False),HEAD)
        elif dev==HEAD:
            with engine.connect() as c:
                if c.execute(text("SELECT to_regclass('public.so4_purchase_orders')")).scalar_one() is None:raise RuntimeError("SO4_DEVELOPMENT_SCHEMA_MISSING")
        else:raise RuntimeError("SO4_DEVELOPMENT_HEAD_UNSAFE="+dev)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","procurement_lifecycle":"PASS","partial_receipt":"PASS","receipt_idempotency":"PASS","tenant_isolation":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test:test.dispose()
        drop();admin.dispose()

def main():
    p=argparse.ArgumentParser();p.add_argument("--acceptance",action="store_true");a=p.parse_args();report=static_verify()
    if a.acceptance:report.update(database_acceptance())
    print(json.dumps(report,indent=2,sort_keys=True));print("SO4_VERIFY=PASS")
if __name__=="__main__":
    try:main()
    except Exception as e:print("SO4_VERIFY=FAIL\n"+str(e));raise SystemExit(1)
