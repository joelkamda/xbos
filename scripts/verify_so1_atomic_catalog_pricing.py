#!/usr/bin/env python3
"""Verify and optionally accept SO1 Atomic Unit, catalog, offer and pricing authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from core.platform.architecture_contract import validate_pc0
from core.platform.neutral_proof.dependency_authority import verify_dependency_authority
from core.platform.release_integrity import verify_historical_release,verify_latest_release
from scripts.verify_so0_shared_operations import verify_so0
from scripts.verify_xa_frontend_experience_architecture import verify_xa
from shared_operations.so1 import SO1Authority,SO1AuthorityError
from shared_operations.so1.contracts import ComponentRule,CreateAtomicUnit,CreateCatalog,CreateOffer,DefinePrice,OfferComponent,PublishCatalogEntry,ResolvePrice,ScopeType,TargetType

SOURCE="f72f4b5d8ad8e576212347615458fcd801e9f7bd";PREVIOUS="pc5_identity_policy_audit_025";HEAD="so1_atomic_catalog_offer_pricing_026"
CONTRACTS=ROOT/"contracts/shared_operations/v1";TEST_DB="xbos_shared_operations_so1_test";LOCAL={"localhost","127.0.0.1","::1"}
FINANCE=("financial_events","journal_entries","journal_lines","financial_obligations","payment_settlements","outbox_messages","reconciliation_controls")
PREDECESSOR_TABLES={"tenants","atomic_units","taxonomy_nodes","atomic_unit_taxonomy"}
SO1_TABLES={"so1_catalogs","so1_offers","so1_offer_components","so1_catalog_entries","so1_prices"}
SO1_CONSTRAINTS={
    "ck_so1_atomic_units_sku","ck_so1_atomic_units_version","uq_so1_atomic_units_public_id","uq_so1_atomic_units_tenant_id_id",
    "ck_so1_catalog_entries_target","ck_so1_catalog_entries_version","ck_so1_catalog_entries_window","fk_so1_catalog_entries_catalog","fk_so1_catalog_entries_offer","fk_so1_catalog_entries_unit","uq_so1_catalog_entries_public_id",
    "ck_so1_catalogs_code","ck_so1_catalogs_name","ck_so1_catalogs_scope","ck_so1_catalogs_version","ck_so1_catalogs_window","fk_so1_catalogs_tenant","uq_so1_catalogs_public_id","uq_so1_catalogs_tenant_code","uq_so1_catalogs_tenant_id_id",
    "ck_so1_offer_components_quantity","ck_so1_offer_components_rule","fk_so1_offer_components_offer","fk_so1_offer_components_unit","uq_so1_offer_components",
    "ck_so1_offers_code","ck_so1_offers_metadata","ck_so1_offers_name","ck_so1_offers_version","fk_so1_offers_tenant","uq_so1_offers_public_id","uq_so1_offers_tenant_code","uq_so1_offers_tenant_id_id",
    "ck_so1_prices_amount","ck_so1_prices_code","ck_so1_prices_currency","ck_so1_prices_scope","ck_so1_prices_target","ck_so1_prices_version","ck_so1_prices_window","fk_so1_prices_offer","fk_so1_prices_tenant","fk_so1_prices_unit","uq_so1_prices_public_id",
}
SO1_INDEXES={"ix_so1_catalogs_tenant_active","ix_so1_entries_catalog_active","ix_so1_offers_tenant_active","ix_so1_prices_resolution"}

def _json(name):return json.loads((CONTRACTS/name).read_text(encoding="utf-8"))
def _canonical(path):return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def _set_alembic_url(config, rendered_url: str) -> None:
    """Inject a rendered SQLAlchemy URL without ConfigParser consuming percent escapes."""
    config.set_main_option("sqlalchemy.url", rendered_url.replace("%", "%%"))

def _run_alembic(operation, config, rendered_url: str, target: str) -> None:
    """Run Alembic against one explicit URL even when the operator environment is set."""
    previous={name:os.environ.get(name) for name in ("DATABASE_URL","MIGRATION_DATABASE_URL")}
    _set_alembic_url(config,rendered_url)
    os.environ["DATABASE_URL"]=rendered_url
    os.environ["MIGRATION_DATABASE_URL"]=rendered_url
    try:operation(config,target)
    finally:
        for name,value in previous.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value

def _verify_predecessor_schema(connection) -> None:
    """Fail closed unless canonical replay produced the exact SO1 predecessor schema."""
    if connection.exec_driver_sql("SELECT to_regclass('public.alembic_version')").scalar_one_or_none() is None:
        raise RuntimeError("SO1_PREDECESSOR_REPLAY_ALEMBIC_VERSION_MISSING")
    actual_head=connection.exec_driver_sql("SELECT version_num FROM public.alembic_version").scalar_one_or_none()
    if actual_head!=PREVIOUS:
        raise RuntimeError(f"SO1_PREDECESSOR_REPLAY_HEAD_MISMATCH={actual_head}")
    existing=set(connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    missing=sorted(PREDECESSOR_TABLES-existing)
    if missing:raise RuntimeError(f"SO1_PREDECESSOR_REPLAY_TABLES_MISSING={missing}")

def _development_action(actual_head: str) -> str:
    if actual_head==PREVIOUS:return "UPGRADE"
    if actual_head==HEAD:return "VERIFY_IN_PLACE"
    raise RuntimeError(f"SO1_DEVELOPMENT_HEAD_UNSAFE={actual_head}")

def _verify_so1_schema(connection) -> None:
    actual_head=connection.exec_driver_sql("SELECT version_num FROM public.alembic_version").scalar_one_or_none()
    if actual_head!=HEAD:raise RuntimeError(f"SO1_DEVELOPMENT_ADOPTION_FAILED={actual_head}")
    tables=set(connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    missing_tables=sorted(SO1_TABLES-tables)
    if missing_tables:raise RuntimeError(f"SO1_DEVELOPMENT_TABLES_MISSING={missing_tables}")
    constraints=set(connection.exec_driver_sql("SELECT conname FROM pg_constraint").scalars())
    missing_constraints=sorted(SO1_CONSTRAINTS-constraints)
    if missing_constraints:raise RuntimeError(f"SO1_DEVELOPMENT_CONSTRAINTS_MISSING={missing_constraints}")
    indexes=set(connection.exec_driver_sql("SELECT indexname FROM pg_indexes WHERE schemaname='public'").scalars())
    missing_indexes=sorted(SO1_INDEXES-indexes)
    if missing_indexes:raise RuntimeError(f"SO1_DEVELOPMENT_INDEXES_MISSING={missing_indexes}")
    invalid_units=connection.exec_driver_sql("SELECT count(*) FROM public.atomic_units WHERE public_id IS NULL OR row_version<1").scalar_one()
    if invalid_units:raise RuntimeError(f"SO1_DEVELOPMENT_ATOMIC_UNIT_ADOPTION_INVALID={invalid_units}")
    invalid_bridge=connection.exec_driver_sql("""SELECT count(*) FROM public.atomic_unit_taxonomy m
        LEFT JOIN public.atomic_units u ON u.id=m.atomic_unit_id
        LEFT JOIN public.taxonomy_nodes n ON n.id=m.taxonomy_node_id
        WHERE u.id IS NULL OR n.id IS NULL OR u.tenant_id IS DISTINCT FROM n.tenant_id""").scalar_one()
    if invalid_bridge:raise RuntimeError(f"SO1_DEVELOPMENT_TAXONOMY_BRIDGE_INVALID={invalid_bridge}")

def _development_snapshot(connection) -> dict[str, dict[str, int]]:
    existing=set(connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())
    def counts(names):return {name:connection.exec_driver_sql(f'SELECT count(*) FROM public."{name}"').scalar_one() for name in sorted(set(names)&existing)}
    return {"finance":counts(FINANCE),"legacy":counts(PREDECESSOR_TABLES),"so1":counts(SO1_TABLES)}

def _verify_development_snapshot(action: str, before: dict, after: dict) -> None:
    if before["finance"]!=after["finance"]:raise RuntimeError("SO1_DEVELOPMENT_FINANCE_CHANGED")
    if before["legacy"]!=after["legacy"]:raise RuntimeError("SO1_DEVELOPMENT_LEGACY_IDENTITY_CHANGED")
    if action=="VERIFY_IN_PLACE" and before["so1"]!=after["so1"]:raise RuntimeError("SO1_DEVELOPMENT_REPEAT_MUTATED_DATA")
    if action=="UPGRADE" and any(after["so1"].values()):raise RuntimeError("SO1_DEVELOPMENT_UPGRADE_SEEDED_DATA")

def static_verify():
    authority=_json("so1_authority.json");adoption=_json("so1_legacy_adoption_manifest.json");interfaces=_json("so1_public_interfaces.json");xa=_json("so1_xa_metadata.json")
    if (authority["source_checkpoint"],authority["previous_head"],authority["accepted_head"],authority["migration"])!=(SOURCE,PREVIOUS,HEAD,"ADDITIVE_ADOPTION"):raise RuntimeError("SO1_RELEASE_BOUNDARY")
    decisions={x["artifact"]:x for x in adoption["decisions"]}
    if decisions["atomic_units.id"]["classification"]!="ADOPT" or decisions["atomic_unit_taxonomy"]["classification"]!="BRIDGE":raise RuntimeError("SO1_LEGACY_ADOPTION")
    if set(authority["required_authorities"])!={"PC1","PC2","PC3","PC4","PC5"}:raise RuntimeError("SO1_PLATFORM_AUTHORITY_COVERAGE")
    if len(interfaces["required_permissions"])!=11 or interfaces["private_package"]!="shared_operations.so1.sql_repository":raise RuntimeError("SO1_PUBLIC_PRIVATE_CONTRACT")
    if xa["xa_contract"]!="xa.frontend-experience.v1" or xa["price_display"]["frontend_calculation"]!="FORBIDDEN":raise RuntimeError("SO1_XA_CONTRACT")
    up=(ROOT/"alembic_neutral/sql/so1_atomic_catalog_offer_pricing_up.sql").read_text(encoding="utf-8")
    down=(ROOT/"alembic_neutral/sql/so1_atomic_catalog_offer_pricing_down.sql").read_text(encoding="utf-8")
    required=("ALTER TABLE public.atomic_units ADD COLUMN public_id","CREATE TABLE public.so1_catalogs","CREATE TABLE public.so1_offers","CREATE TABLE public.so1_offer_components","CREATE TABLE public.so1_catalog_entries","CREATE TABLE public.so1_prices","operational commercial prices; never revenue")
    if not all(x in up for x in required):raise RuntimeError("SO1_MIGRATION_COVERAGE")
    if any(x in up for x in ("DROP TABLE public.atomic_units","TRUNCATE","UPDATE public.taxonomy_nodes","INSERT INTO public.financial_","UPDATE public.financial_")):raise RuntimeError("SO1_DESTRUCTIVE_OR_FINANCIAL_SQL")
    if "DROP COLUMN IF EXISTS public_id" not in down or "DROP TABLE IF EXISTS public.so1_prices" not in down:raise RuntimeError("SO1_DOWNGRADE_COVERAGE")
    profiles=[_json("examples/retail_service_profile.json"),_json("examples/professional_service_profile.json")]
    if profiles[0]["currency"]==profiles[1]["currency"] or profiles[0]["atomic_units"]==profiles[1]["atomic_units"]:raise RuntimeError("SO1_NEUTRALITY_PROFILES")
    forbidden=(bytes((87,78,68)),b"Wine & Dine",b"Logpom",b"meal",b"menu item")
    for base in (ROOT/"shared_operations/so1",CONTRACTS):
        for path in base.rglob("*"):
            if path.is_file() and path.name!="so1_release_manifest.json" and any(x.lower() in path.read_bytes().lower() for x in forbidden):raise RuntimeError(f"SO1_ACTIVE_INDUSTRY_LEAKAGE={path.relative_to(ROOT)}")
    dependency=verify_dependency_authority(ROOT,json.loads((ROOT/"contracts/platform/v1/pc6_dependency_authority.json").read_text()))
    if dependency["pin_count"]!=14 or dependency["python"]!="3.13.3":raise RuntimeError("SO1_DEPENDENCY_AUTHORITY")
    pc0=validate_pc0(ROOT)
    for number in range(1,6):verify_historical_release(ROOT,number)
    if verify_latest_release(ROOT)["latest"]!=6:raise RuntimeError("SO1_PLATFORM_RELEASE_CHAIN")
    if verify_xa()["status"]!="PASS" or verify_so0()["status"]!="PASS":raise RuntimeError("SO1_FROZEN_PREDECESSOR")
    manifest=_json("so1_release_manifest.json")
    install_lines=(ROOT/"SO1_INSTALL_MANIFEST.txt").read_text(encoding="utf-8").splitlines()
    inventory_start=install_lines.index("SO1_INSTALL_MANIFEST.txt")
    package_inventory=[line for line in install_lines[inventory_start:] if line]
    expected_inventory=[item["path"] for item in manifest["artifacts"]]+["contracts/shared_operations/v1/so1_release_manifest.json"]
    if len(package_inventory)!=len(set(package_inventory)) or set(package_inventory)!=set(expected_inventory):
        raise RuntimeError("SO1_PACKAGE_INVENTORY_MISMATCH")
    for item in manifest["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or _canonical(path)!=item["sha256"]:raise RuntimeError(f"SO1_RELEASE_MISMATCH={item['path']}")
    return {"status":"PASS","source_checkpoint":SOURCE[:7],"previous_head":PREVIOUS,"accepted_head":HEAD,"legacy_atomic_unit_identity":"ADOPT_PRESERVE","taxonomy_bridge":"PRESERVE","neutral_profiles":2,"pc0":pc0["status"],"xa":"PASS","so0":"PASS","finance":"UNCHANGED","dependency_changes":"NONE","release_artifacts":len(manifest["artifacts"])}

@contextmanager
def _session(engine):
    from sqlalchemy.orm import Session
    with Session(engine,expire_on_commit=False) as session:
        with session.begin():yield session

def database_acceptance():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from database import engine as application_engine
    from shared_operations.so1.sql_repository import SQLSO1Repository
    url=make_url(application_engine.url)
    if url.host not in LOCAL or url.database!="xbos_track_b_dev":raise RuntimeError("SO1_REFUSE_NONLOCAL_OR_WRONG_DEV_DB")
    with application_engine.connect() as c:
        development_action=_development_action(c.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
    def selected(name,auto=False):return create_engine(url.set(database=name),pool_pre_ping=True,**({"isolation_level":"AUTOCOMMIT"} if auto else {}))
    admin=selected("postgres",True);test=None;success=False
    def drop():
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":TEST_DB});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    try:
        drop()
        with admin.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{TEST_DB}" TEMPLATE template0')
        test=selected(TEST_DB);cfg=Config(str(ROOT/"alembic_neutral.ini"));test_url=url.set(database=TEST_DB).render_as_string(hide_password=False)
        _run_alembic(command.upgrade,cfg,test_url,PREVIOUS)
        with test.connect() as c:_verify_predecessor_schema(c)
        with test.begin() as c:
            tenant_a=c.execute(text("INSERT INTO tenants(code,name,country_code,currency,locale,timezone) VALUES('CEDAR','Cedar Services','CA','CAD','en-CA','America/Toronto') RETURNING id")).scalar_one()
            tenant_b=c.execute(text("INSERT INTO tenants(code,name,country_code,currency,locale,timezone) VALUES('ORBIT','Orbit Advisory','GB','GBP','en-GB','Europe/London') RETURNING id")).scalar_one()
            legacy=c.execute(text("INSERT INTO atomic_units(tenant_id,name,sku,unit_type,is_active,meta) VALUES(:t,'Legacy Equipment','LEGACY-EQUIP','asset',true,'{}') RETURNING id"),{"t":tenant_a}).scalar_one()
            node=c.execute(text("INSERT INTO taxonomy_nodes(tenant_id,name,semantic_level,sort_order,is_active,taxonomy_type,meta) VALUES(:t,'Equipment','category',0,true,'OPERATIONS','{}') RETURNING id"),{"t":tenant_a}).scalar_one()
            c.execute(text("INSERT INTO atomic_unit_taxonomy(atomic_unit_id,taxonomy_node_id) VALUES(:u,:n)"),{"u":legacy,"n":node})
            finance_before={table:c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCE}
        _run_alembic(command.upgrade,cfg,test_url,HEAD)
        now=datetime(2026,8,13,12,tzinfo=timezone.utc)
        with _session(test) as s:
            preserved=s.execute(text("SELECT id,sku,public_id,row_version FROM atomic_units WHERE tenant_id=:t AND id=:id"),{"t":tenant_a,"id":legacy}).one()
            if preserved.id!=legacy or preserved.sku!="LEGACY-EQUIP" or preserved.public_id is None:raise RuntimeError("SO1_LEGACY_IDENTITY_NOT_PRESERVED")
            if s.execute(text("SELECT count(*) FROM atomic_unit_taxonomy WHERE atomic_unit_id=:id"),{"id":legacy}).scalar_one()!=1:raise RuntimeError("SO1_TAXONOMY_BRIDGE_NOT_PRESERVED")
            repo=SQLSO1Repository(s);authority=SO1Authority(repo,authorize=lambda *args:True,validate_scope=lambda tenant,scope,scope_id:tenant in {tenant_a,tenant_b},public_id_factory=lambda:UUID(int=s.execute(text("SELECT nextval('billable_units_id_seq')")).scalar_one()+1000))
            unit=authority.create_atomic_unit(CreateAtomicUnit("so1:u",tenant_a,"INSTALL","Installation","service_capability"))
            second=authority.create_atomic_unit(CreateAtomicUnit("so1:v",tenant_b,"CONSULT","Consultation","labor_service_capability"))
            try:authority.atomic_unit(tenant_a,second.public_id)
            except SO1AuthorityError:pass
            else:raise RuntimeError("SO1_CROSS_TENANT_UNIT_RESOLVED")
            offer=authority.create_offer(CreateOffer("so1:o",tenant_a,"INSTALL-OFFER","Installation Offer",(OfferComponent(unit.public_id,Decimal("1"),ComponentRule.REQUIRED,1),)))
            catalog=authority.create_catalog(CreateCatalog("so1:c",tenant_a,"SERVICES","Services",ScopeType.TENANT,None,now))
            authority.publish_catalog_entry(PublishCatalogEntry("so1:e",tenant_a,catalog.public_id,TargetType.OFFER,offer.public_id))
            authority.define_price(DefinePrice("so1:p",tenant_a,TargetType.OFFER,offer.public_id,"STANDARD",Decimal("89.00"),"CAD",ScopeType.TENANT,None,10,now-timedelta(days=1)))
            resolved=authority.resolve_price(ResolvePrice(tenant_a,TargetType.OFFER,offer.public_id,"STANDARD","CAD",now,ScopeType.TENANT,None))
            if resolved.amount!=Decimal("89.000000"):raise RuntimeError("SO1_PRICE_RESOLUTION")
            finance_after={table:s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCE}
            if finance_after!=finance_before:raise RuntimeError("SO1_FINANCIAL_EFFECTS_CHANGED")
        _run_alembic(command.downgrade,cfg,test_url,PREVIOUS)
        with test.connect() as c:
            if c.execute(text("SELECT id FROM atomic_units WHERE tenant_id=:t AND sku='LEGACY-EQUIP'"),{"t":tenant_a}).scalar_one()!=legacy:raise RuntimeError("SO1_DOWNGRADE_LOST_LEGACY_IDENTITY")
        _run_alembic(command.upgrade,cfg,test_url,HEAD)
        with application_engine.connect() as c:development_before=_development_snapshot(c)
        if development_action=="UPGRADE":
            dev_cfg=Config(str(ROOT/"alembic_neutral.ini"));_run_alembic(command.upgrade,dev_cfg,url.render_as_string(hide_password=False),HEAD)
        with application_engine.connect() as c:
            _verify_so1_schema(c);development_after=_development_snapshot(c)
        _verify_development_snapshot(development_action,development_before,development_after)
        success=True
        return {"clean_replay":"PASS","upgrade":"PASS","downgrade_reupgrade":"PASS","legacy_identity":"PRESERVED","taxonomy_bridge":"PASS","tenant_isolation":"PASS","pricing_resolution":"PASS","development_adoption":development_action,"financial_effects":"UNCHANGED","cleanup":"PASS"}
    finally:
        if test:test.dispose()
        if success:drop()
        admin.dispose()

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance:result["database"]=database_acceptance()
    except Exception as exc:print(f"SO1_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("SO1_VERIFY=PASS");return 0

if __name__=="__main__":raise SystemExit(main())
