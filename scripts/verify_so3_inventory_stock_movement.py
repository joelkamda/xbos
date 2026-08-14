#!/usr/bin/env python3
"""Verify and optionally accept SO3 inventory authority."""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
SOURCE="fdb2cc853705b6a6905048741bb78b3bdc81428c"
PREVIOUS="so2_operational_party_relationships_027"
HEAD="so3_inventory_stock_movement_028"
CONTRACTS=ROOT/"contracts/shared_operations/v1"

def _json(name): return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))
def _canonical(path): return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
def _set_url(config,url): config.set_main_option("sqlalchemy.url",url.replace("%","%%"))
def _run(operation,config,url,target):
    old={k:os.environ.get(k) for k in ("DATABASE_URL","MIGRATION_DATABASE_URL")}; _set_url(config,url)
    os.environ.update(DATABASE_URL=url,MIGRATION_DATABASE_URL=url)
    try: operation(config,target)
    finally:
        for k,v in old.items(): os.environ.pop(k,None) if v is None else os.environ.__setitem__(k,v)

def _verify_fk_candidate_keys(up):
    import re
    predecessor=(ROOT/"alembic_neutral/sql/pc1_structural_context_up.sql").read_text(encoding="utf-8")+(ROOT/"alembic_neutral/sql/so1_atomic_catalog_offer_pricing_up.sql").read_text(encoding="utf-8")
    candidates={
        "so3_stock_locations":"CONSTRAINT uq_so3_stock_locations_tenant_id UNIQUE(tenant_id,id)",
        "inventory_items":"CONSTRAINT uq_so3_inventory_item_tenant_id UNIQUE(tenant_id,id)",
        "inventory_movements":"CONSTRAINT uq_so3_movement_tenant_id UNIQUE(tenant_id,id)",
    }
    if not all(marker in up for marker in candidates.values()): raise RuntimeError("SO3_FK_CANDIDATE_KEY_MISSING")
    if not all(marker in predecessor for marker in ("uq_locations_tenant_id_id UNIQUE (tenant_id,id)","uq_branches_tenant_id_id UNIQUE (tenant_id,id)","uq_so1_atomic_units_tenant_id_id UNIQUE(tenant_id,id)")): raise RuntimeError("SO3_PREDECESSOR_CANDIDATE_KEY_MISSING")
    references=re.findall(r"FOREIGN KEY\(([^)]+)\) REFERENCES public\.([a-z0-9_]+)\(([^)]+)\)",up)
    tenant_targets={"so3_stock_locations","inventory_items","inventory_movements","locations","branches","atomic_units"}
    relevant=[(source.replace(" ",""),target,columns.replace(" ","")) for source,target,columns in references if target in tenant_targets]
    if not relevant or any(not source.startswith("tenant_id,") or columns!="tenant_id,id" for source,target,columns in relevant): raise RuntimeError("SO3_CROSS_TENANT_FK_WEAKENED")
    if sum(target=="so3_stock_locations" for _,target,_ in relevant)!=6: raise RuntimeError("SO3_STOCK_LOCATION_FK_COVERAGE")

def static_verify():
    from core.platform.architecture_contract import validate_pc0
    authority=_json("so3_authority.json"); adoption=_json("so3_legacy_adoption_manifest.json"); interfaces=_json("so3_public_interfaces.json"); xa=_json("so3_xa_metadata.json")
    if (authority["source_checkpoint"],authority["previous_head"],authority["accepted_head"])!=(SOURCE,PREVIOUS,HEAD): raise RuntimeError("SO3_RELEASE_BOUNDARY")
    decisions={x["artifact"]:x for x in adoption["decisions"]}
    if decisions["inventory_items"]["classification"]!="ADOPT" or decisions["inventory_movements"]["classification"]!="ADOPT": raise RuntimeError("SO3_LEGACY_ADOPTION")
    if authority["financial_valuation"]!="EXCLUDED" or authority["production_dependency_changes"]!="NONE": raise RuntimeError("SO3_FINANCE_OR_DEPENDENCY")
    if interfaces["public_module"]!="shared_operations.so3" or xa["frontend_implementation"]!="NONE": raise RuntimeError("SO3_INTERFACE_BOUNDARY")
    up=(ROOT/"alembic_neutral/sql/so3_inventory_stock_movement_up.sql").read_text(encoding="utf-8")
    _verify_fk_candidate_keys(up)
    required=("ALTER TABLE public.inventory_items","ALTER TABLE public.inventory_movements","CREATE TABLE public.so3_stock_locations","legacy_branch_structural_mappings","so3_inventory_movement_immutable")
    if not all(x in up for x in required): raise RuntimeError("SO3_MIGRATION_COVERAGE")
    if any(x in up for x in ("CREATE TABLE public.inventory_ledger","INSERT INTO public.financial_","UPDATE public.financial_","DROP TABLE public.inventory_items","CREATE TABLE public.atomic_units","CREATE TABLE public.locations")): raise RuntimeError("SO3_COMPETING_OR_FINANCE_SQL")
    profiles=[_json("examples/retail_inventory_profile.json"),_json("examples/clinical_supplies_profile.json")]
    if profiles[0]["terminology"]==profiles[1]["terminology"]: raise RuntimeError("SO3_NEUTRALITY")
    if validate_pc0(ROOT,validate_release=False)["status"]!="PASS": raise RuntimeError("SO3_PC0")
    manifest=_json("so3_release_manifest.json")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]: raise RuntimeError("SO3_RELEASE_MISMATCH="+item["path"])
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"legacy_inventory":"ADOPT_PRESERVE","atomic_unit":"SO1_REUSED","location":"PC1_REUSED","finance":"UNCHANGED","dependency_changes":"NONE","neutral_profiles":2,"release_artifacts":len(manifest["artifacts"])}

def database_acceptance():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from database import engine
    url=make_url(engine.url)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database!="xbos_track_b_dev": raise RuntimeError("SO3_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    test_name="xbos_shared_operations_so3_test"; admin=create_engine(url.set(database="postgres"),isolation_level="AUTOCOMMIT"); test=None
    def drop():
        with admin.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":test_name}); c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{test_name}"')
    try:
        drop()
        with admin.connect() as c: c.exec_driver_sql(f'CREATE DATABASE "{test_name}" TEMPLATE template0')
        test=create_engine(url.set(database=test_name)); cfg=Config(str(ROOT/"alembic_neutral.ini")); rendered=url.set(database=test_name).render_as_string(hide_password=False)
        _run(command.upgrade,cfg,rendered,"m64_reconciliation_controls_020")
        with test.begin() as c:
            c.execute(text("INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) VALUES(9301,'SO3A','Neutral Inventory','CM','XAF','en-CM','Africa/Douala')"))
            c.execute(text("INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active) VALUES(9301,9301,'LEGACY','Legacy Stock Site','Douala','Compatibility',true)"))
            c.execute(text("INSERT INTO atomic_units(id,tenant_id,name,sku,unit_type,is_active,is_sellable) VALUES(9301,9301,'Neutral Unit','SO3-U','each',true,true)"))
            item=c.execute(text("INSERT INTO inventory_items(id,tenant_id,branch_id,atomic_unit_id,quantity_on_hand,reorder_level) VALUES(9301,9301,9301,9301,7,2) RETURNING id")).scalar_one()
            c.execute(text("INSERT INTO inventory_movements(id,tenant_id,branch_id,inventory_item_id,atomic_unit_id,quantity_delta,movement_type,source,reference_type,reference_id) VALUES(9301,9301,9301,:item,9301,7,'receipt','legacy','fixture',9301)"),{"item":item})
        _run(command.upgrade,cfg,rendered,PREVIOUS)
        with test.connect() as c:
            if c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=PREVIOUS: raise RuntimeError("SO3_PREDECESSOR_REPLAY")
        _run(command.upgrade,cfg,rendered,HEAD)
        with test.connect() as c:
            head=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one(); tables=set(c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
            required={"inventory_items","inventory_movements","so3_stock_locations","so3_inventory_commands","so3_stock_reservations","so3_stock_counts","so3_stock_transfers"}
            legacy=c.execute(text("SELECT i.id,i.quantity_on_hand,s.legacy_branch_id FROM inventory_items i JOIN so3_stock_locations s ON s.id=i.stock_location_id WHERE i.id=9301")).one_or_none()
            movement=c.execute(text("SELECT id,quantity_delta FROM inventory_movements WHERE id=9301")).one_or_none()
            if head!=HEAD or not required.issubset(tables) or legacy!=(9301,7,9301) or movement!=(9301,7): raise RuntimeError("SO3_SCHEMA_OR_LEGACY_ADOPTION_PROOF")
        _run(command.downgrade,cfg,rendered,PREVIOUS); _run(command.upgrade,cfg,rendered,HEAD)
        with engine.connect() as c: actual=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if actual==PREVIOUS: _run(command.upgrade,Config(str(ROOT/"alembic_neutral.ini")),url.render_as_string(hide_password=False),HEAD)
        elif actual!=HEAD: raise RuntimeError("SO3_DEVELOPMENT_HEAD_UNSAFE="+actual)
        return {"disposable_rehearsal":"PASS","development_adoption":"PASS","financial_effects":"UNCHANGED"}
    finally:
        if test: test.dispose()
        drop(); admin.dispose()

def main():
    p=argparse.ArgumentParser(); p.add_argument("--acceptance",action="store_true"); a=p.parse_args(); report=static_verify()
    if a.acceptance: report.update(database_acceptance())
    print(json.dumps(report,indent=2,sort_keys=True)); print("SO3_VERIFY=PASS")
if __name__=="__main__":
    try: main()
    except Exception as e: print("SO3_VERIFY=FAIL\n"+str(e)); raise SystemExit(1)
