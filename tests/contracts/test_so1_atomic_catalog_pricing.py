from __future__ import annotations

import copy
import configparser
import json
import os
import re
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from shared_operations.so1 import SO1Authority,SO1AuthorityError
from shared_operations.so1.contracts import AtomicUnit,Catalog,ComponentRule,CreateAtomicUnit,CreateCatalog,CreateOffer,DefinePrice,Offer,OfferComponent,Price,PublishCatalogEntry,ResolvePrice,ScopeType,TargetType,UpdateOffer
from scripts.verify_so1_atomic_catalog_pricing import HEAD,PREDECESSOR_TABLES,PREVIOUS,SO1_CONSTRAINTS,SO1_INDEXES,SO1_TABLES,_development_action,_run_alembic,_set_alembic_url,_verify_development_snapshot,_verify_predecessor_schema,_verify_so1_schema,static_verify

ROOT=Path(__file__).resolve().parents[2];CONTRACTS=ROOT/"contracts/shared_operations/v1"
def load(name):return json.loads((CONTRACTS/name).read_text())

class MemoryRepository:
    def __init__(self):self.units={};self.catalogs={};self.offers={};self.prices={};self.links=[];self.entries=[];self.next=1
    def create_atomic_unit(self,c,p):
        result=AtomicUnit(self.next,p,c.tenant_id,c.code,c.name,c.unit_kind,True,c.metadata or {},1);self.next+=1;self.units[(c.tenant_id,p)]=result;return result
    def atomic_unit(self,t,p):return self.units.get((t,p))
    def update_atomic_unit(self,c):
        item=self.atomic_unit(c.tenant_id,c.public_id)
        if not item or item.row_version!=c.expected_version:return None
        result=AtomicUnit(item.id,item.public_id,item.tenant_id,item.code,c.name or item.name,c.unit_kind or item.unit_kind,item.active,c.metadata if c.metadata is not None else item.metadata,item.row_version+1);self.units[(c.tenant_id,c.public_id)]=result;return result
    def deactivate_atomic_unit(self,t,p,v):
        item=self.atomic_unit(t,p)
        if not item or item.row_version!=v:return None
        result=AtomicUnit(item.id,item.public_id,item.tenant_id,item.code,item.name,item.unit_kind,False,item.metadata,v+1);self.units[(t,p)]=result;return result
    def link_taxonomy(self,t,p,n):
        if self.atomic_unit(t,p) is None:raise ValueError("cross tenant")
        self.links.append((t,p,n))
    def create_catalog(self,c,p):
        result=Catalog(self.next,p,c.tenant_id,c.code,c.name,c.scope_type,c.scope_id,True,c.effective_from,c.effective_to,1);self.next+=1;self.catalogs[(c.tenant_id,p)]=result;return result
    def catalog(self,t,p):return self.catalogs.get((t,p))
    def publish_entry(self,c,p):
        if self.catalog(c.tenant_id,c.catalog_public_id) is None:raise ValueError("cross tenant")
        self.entries.append((c,p));return p
    def create_offer(self,c,p):
        if any(self.atomic_unit(c.tenant_id,x.atomic_unit_public_id) is None for x in c.components):raise ValueError("cross tenant")
        result=Offer(self.next,p,c.tenant_id,c.code,c.name,True,c.components,1);self.next+=1;self.offers[(c.tenant_id,p)]=result;return result
    def offer(self,t,p):return self.offers.get((t,p))
    def update_offer(self,c):
        item=self.offer(c.tenant_id,c.public_id)
        if not item or item.row_version!=c.expected_version:return None
        result=Offer(item.id,item.public_id,item.tenant_id,item.code,c.name,True,c.components,item.row_version+1);self.offers[(c.tenant_id,c.public_id)]=result;return result
    def deactivate_offer(self,t,p,v):
        item=self.offer(t,p)
        if not item or item.row_version!=v:return None
        result=Offer(item.id,item.public_id,item.tenant_id,item.code,item.name,False,item.components,v+1);self.offers[(t,p)]=result;return result
    def define_price(self,c,p):
        if (c.target_type is TargetType.ATOMIC_UNIT and self.atomic_unit(c.tenant_id,c.target_public_id) is None) or (c.target_type is TargetType.OFFER and self.offer(c.tenant_id,c.target_public_id) is None):raise ValueError("cross tenant")
        result=Price(self.next,p,c.tenant_id,c.target_type,c.target_public_id,c.price_code,c.amount,c.currency,c.scope_type,c.scope_id,c.precedence,c.effective_from,c.effective_to,True,1);self.next+=1;self.prices[(c.tenant_id,p)]=result;return result
    def price(self,t,p):return self.prices.get((t,p))
    def deactivate_price(self,t,p,v):
        item=self.price(t,p)
        if not item or item.row_version!=v:return None
        result=Price(item.id,item.public_id,item.tenant_id,item.target_type,item.target_public_id,item.price_code,item.amount,item.currency,item.scope_type,item.scope_id,item.precedence,item.effective_from,item.effective_to,False,v+1);self.prices[(t,p)]=result;return result
    def resolve_price(self,q):
        candidates=[p for (tenant,_),p in self.prices.items() if tenant==q.tenant_id and p.target_type==q.target_type and p.target_public_id==q.target_public_id and p.price_code==q.price_code and p.currency==q.currency and p.active and p.effective_from<=q.at and (p.effective_to is None or p.effective_to>q.at) and (p.scope_type is ScopeType.TENANT or (p.scope_type==q.scope_type and p.scope_id==q.scope_id))]
        candidates.sort(key=lambda p:((p.scope_type==q.scope_type and p.scope_id==q.scope_id),p.precedence,p.effective_from),reverse=True)
        if len(candidates)>1 and ((candidates[0].scope_type==q.scope_type,candidates[0].precedence,candidates[0].effective_from)==(candidates[1].scope_type==q.scope_type,candidates[1].precedence,candidates[1].effective_from)):raise ValueError("SO1_AMBIGUOUS_PRICE")
        return candidates[0] if candidates else None

def authority(repo=None,tenant_ids=(1,2)):
    ids=iter(UUID(int=x) for x in range(1,100));return SO1Authority(repo or MemoryRepository(),authorize=lambda *args:True,validate_scope=lambda tenant,*args:tenant in tenant_ids,public_id_factory=lambda:next(ids))

def test_static_so1_contract_and_lineage_are_complete():
    result=static_verify();assert result["status"]=="PASS" and (result["previous_head"],result["accepted_head"])==(PREVIOUS,HEAD)

def test_alembic_url_injection_preserves_percent_encoded_credentials():
    class ConfigParserBackedAlembicConfig:
        def __init__(self):self.parser=configparser.ConfigParser();self.parser.add_section("alembic")
        def set_main_option(self,name,value):self.parser.set("alembic",name,value)
        def get_main_option(self,name):return self.parser.get("alembic",name)
    config=ConfigParserBackedAlembicConfig()
    encoded="postgresql://operator:example%40credential@localhost:5432/xbos_shared_operations_so1_test"
    _set_alembic_url(config,encoded)
    assert config.get_main_option("sqlalchemy.url")==encoded

def test_every_so1_alembic_url_injection_uses_the_safe_helper():
    source=(ROOT/"scripts/verify_so1_atomic_catalog_pricing.py").read_text(encoding="utf-8")
    assert source.count('_set_alembic_url(')==2
    assert source.count('set_main_option("sqlalchemy.url"')==1
    assert source.count('_run_alembic(command.')==5

def test_alembic_runner_targets_disposable_url_and_restores_operator_environment():
    class ConfigParserBackedAlembicConfig:
        def __init__(self):self.parser=configparser.ConfigParser();self.parser.add_section("alembic")
        def set_main_option(self,name,value):self.parser.set("alembic",name,value)
        def get_main_option(self,name):return self.parser.get("alembic",name)
    original={name:os.environ.get(name) for name in ("DATABASE_URL","MIGRATION_DATABASE_URL")}
    operator_url="postgresql://operator:accepted@localhost:5432/xbos_track_b_dev"
    disposable_url="postgresql://operator:example%40credential@localhost:5432/xbos_shared_operations_so1_test"
    observed=[];config=ConfigParserBackedAlembicConfig()
    os.environ["DATABASE_URL"]=operator_url;os.environ.pop("MIGRATION_DATABASE_URL",None)
    try:
        _run_alembic(lambda cfg,target:observed.append((cfg.get_main_option("sqlalchemy.url"),os.environ["DATABASE_URL"],os.environ["MIGRATION_DATABASE_URL"],target)),config,disposable_url,PREVIOUS)
        assert observed==[(disposable_url,disposable_url,disposable_url,PREVIOUS)]
        assert os.environ["DATABASE_URL"]==operator_url and "MIGRATION_DATABASE_URL" not in os.environ
    finally:
        for name,value in original.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value

def test_predecessor_schema_checkpoint_requires_exact_head_and_required_tables():
    class Result:
        def __init__(self,scalar=None,rows=()):self.scalar,self.rows=scalar,rows
        def scalar_one_or_none(self):return self.scalar
        def scalars(self):return iter(self.rows)
    class Connection:
        def __init__(self,head=PREVIOUS,tables=PREDECESSOR_TABLES):self.head,self.tables=head,tables
        def exec_driver_sql(self,sql):
            if "to_regclass" in sql:return Result("alembic_version")
            if "version_num" in sql:return Result(self.head)
            return Result(rows=self.tables)
    _verify_predecessor_schema(Connection())
    with pytest.raises(RuntimeError,match="SO1_PREDECESSOR_REPLAY_HEAD_MISMATCH"):_verify_predecessor_schema(Connection(head="m64_reconciliation_controls_020"))
    with pytest.raises(RuntimeError,match="SO1_PREDECESSOR_REPLAY_TABLES_MISSING"):_verify_predecessor_schema(Connection(tables=PREDECESSOR_TABLES-{"tenants"}))

def test_clean_replay_checkpoint_precedes_every_so1_fixture_insert():
    source=(ROOT/"scripts/verify_so1_atomic_catalog_pricing.py").read_text(encoding="utf-8")
    replay=source.index("_run_alembic(command.upgrade,cfg,test_url,PREVIOUS)")
    checkpoint=source.index("_verify_predecessor_schema(c)",replay)
    fixture=source.index("INSERT INTO tenants",checkpoint)
    assert replay<checkpoint<fixture

def test_development_adoption_accepts_only_predecessor_or_so1_head():
    assert _development_action(PREVIOUS)=="UPGRADE"
    assert _development_action(HEAD)=="VERIFY_IN_PLACE"
    with pytest.raises(RuntimeError,match="SO1_DEVELOPMENT_HEAD_UNSAFE"):_development_action("parallel_or_future_head")

def test_so1_schema_catalog_expectations_exactly_cover_migration_sql():
    sql=(ROOT/"alembic_neutral/sql/so1_atomic_catalog_offer_pricing_up.sql").read_text(encoding="utf-8")
    assert SO1_TABLES==set(re.findall(r"CREATE TABLE public\.([a-zA-Z0-9_]+)",sql))
    assert SO1_CONSTRAINTS==set(re.findall(r"CONSTRAINT ([a-zA-Z0-9_]+)",sql))
    assert SO1_INDEXES==set(re.findall(r"CREATE INDEX ([a-zA-Z0-9_]+)",sql))

def test_development_schema_verifier_fails_closed_on_missing_structure():
    class Result:
        def __init__(self,scalar=None,rows=()):self.scalar,self.rows=scalar,rows
        def scalar_one_or_none(self):return self.scalar
        def scalar_one(self):return self.scalar
        def scalars(self):return iter(self.rows)
    class Connection:
        def __init__(self,constraints=SO1_CONSTRAINTS):self.constraints=constraints
        def exec_driver_sql(self,sql):
            if "version_num" in sql:return Result(HEAD)
            if "pg_tables" in sql:return Result(rows=SO1_TABLES|PREDECESSOR_TABLES)
            if "pg_constraint" in sql:return Result(rows=self.constraints)
            if "pg_indexes" in sql:return Result(rows=SO1_INDEXES)
            return Result(0)
    _verify_so1_schema(Connection())
    with pytest.raises(RuntimeError,match="SO1_DEVELOPMENT_CONSTRAINTS_MISSING"):_verify_so1_schema(Connection(SO1_CONSTRAINTS-{"ck_so1_prices_amount"}))

def test_repeated_development_acceptance_is_read_only_and_duplicate_free():
    accepted={"finance":{"financial_events":2},"legacy":{"atomic_units":7,"atomic_unit_taxonomy":5},"so1":{"so1_catalogs":3,"so1_offers":4,"so1_prices":6}}
    _verify_development_snapshot("VERIFY_IN_PLACE",copy.deepcopy(accepted),copy.deepcopy(accepted))
    changed=copy.deepcopy(accepted);changed["so1"]["so1_catalogs"]+=1
    with pytest.raises(RuntimeError,match="SO1_DEVELOPMENT_REPEAT_MUTATED_DATA"):_verify_development_snapshot("VERIFY_IN_PLACE",accepted,changed)
    predecessor={"finance":{"financial_events":2},"legacy":{"atomic_units":7},"so1":{}}
    upgraded={"finance":{"financial_events":2},"legacy":{"atomic_units":7},"so1":{name:0 for name in SO1_TABLES}}
    _verify_development_snapshot("UPGRADE",predecessor,upgraded)

def test_existing_atomic_unit_identity_is_adopted_not_recreated():
    decisions={x["artifact"]:x for x in load("so1_legacy_adoption_manifest.json")["decisions"]}
    assert decisions["atomic_units.id"]["classification"]=="ADOPT"
    up=(ROOT/"alembic_neutral/sql/so1_atomic_catalog_offer_pricing_up.sql").read_text()
    assert "ALTER TABLE public.atomic_units ADD COLUMN public_id" in up and "DROP TABLE public.atomic_units" not in up

def test_atomic_unit_semantic_taxonomy_offer_price_inventory_and_finance_are_distinct():
    distinctions=set(load("so1_authority.json")["distinctions"])
    assert {"atomic_unit_not_semantic_identity","atomic_unit_not_taxonomy_placement","atomic_unit_not_offer","atomic_unit_not_price","atomic_unit_not_inventory_balance","atomic_unit_not_financial_account"}<=distinctions

def test_many_to_many_taxonomy_bridge_is_preserved_and_pc3_owned():
    adoption=load("so1_legacy_adoption_manifest.json");entry=next(x for x in adoption["decisions"] if x["artifact"]=="atomic_unit_taxonomy")
    assert entry["classification"]=="BRIDGE" and "PC3" in entry["treatment"]

def test_offer_composition_is_deterministic_and_distinct_from_atomic_units():
    repo=MemoryRepository();service=authority(repo);first=service.create_atomic_unit(CreateAtomicUnit("u1",1,"HOUR","Consulting Hour"));second=service.create_atomic_unit(CreateAtomicUnit("u2",1,"REPORT","Digital Report"))
    offer=service.create_offer(CreateOffer("o",1,"ASSESS","Assessment",(OfferComponent(second.public_id,Decimal("1"),ComponentRule.OPTIONAL,2),OfferComponent(first.public_id,Decimal("2"),ComponentRule.REQUIRED,1))))
    assert offer.public_id not in {first.public_id,second.public_id} and [x.sequence for x in offer.components]==[1,2]

def test_offer_update_preserves_identity_orders_components_and_rejects_stale_version():
    repo=MemoryRepository();service=authority(repo);first=service.create_atomic_unit(CreateAtomicUnit("u1",1,"HOUR","Hour"));second=service.create_atomic_unit(CreateAtomicUnit("u2",1,"REPORT","Report"))
    offer=service.create_offer(CreateOffer("o",1,"PACKAGE","Package",(OfferComponent(first.public_id,Decimal("1"),ComponentRule.REQUIRED,1),)))
    updated=service.update_offer(UpdateOffer("o2",1,offer.public_id,1,"Revised",(OfferComponent(second.public_id,Decimal("1"),ComponentRule.OPTIONAL,2),OfferComponent(first.public_id,Decimal("2"),ComponentRule.REQUIRED,1))))
    assert updated.public_id==offer.public_id and updated.row_version==2 and [x.sequence for x in updated.components]==[1,2]
    with pytest.raises(SO1AuthorityError,match="SO1_STALE_VERSION"):service.update_offer(UpdateOffer("o3",1,offer.public_id,1,"Stale",updated.components))

def test_release_manifest_rejects_an_arbitrary_artifact_mutation():
    manifest=load("so1_release_manifest.json");item=next(x for x in manifest["artifacts"] if x["path"]=="shared_operations/so1/service.py")
    original=(ROOT/item["path"]).read_bytes().replace(b"\r\n",b"\n")
    import hashlib
    assert hashlib.sha256(original).hexdigest()==item["sha256"]
    assert hashlib.sha256(original+b"# unauthorized mutation\n").hexdigest()!=item["sha256"]

def test_catalog_is_not_taxonomy_or_frontend_navigation():
    distinctions=set(load("so1_authority.json")["distinctions"]);assert {"catalog_not_taxonomy","catalog_not_inventory","catalog_not_frontend_navigation"}<=distinctions

def test_effective_price_resolution_uses_scope_precedence_and_time():
    repo=MemoryRepository();service=authority(repo);now=datetime(2026,8,13,12,tzinfo=timezone.utc);unit=service.create_atomic_unit(CreateAtomicUnit("u",1,"LABOR","Labor"))
    service.define_price(DefinePrice("p1",1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD",Decimal("100"),"USD",ScopeType.TENANT,None,10,now-timedelta(days=2)))
    service.define_price(DefinePrice("p2",1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD",Decimal("90"),"USD",ScopeType.LOCATION,7,1,now-timedelta(days=1)))
    result=service.resolve_price(ResolvePrice(1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD","USD",now,ScopeType.LOCATION,7));assert result.amount==Decimal("90")

def test_disabled_and_expired_prices_do_not_resolve():
    repo=MemoryRepository();service=authority(repo);now=datetime(2026,8,13,12,tzinfo=timezone.utc);unit=service.create_atomic_unit(CreateAtomicUnit("u",1,"DIGITAL","Digital"));price=service.define_price(DefinePrice("p",1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD",Decimal("10"),"USD",ScopeType.TENANT,None,1,now-timedelta(days=2),now-timedelta(days=1)))
    with pytest.raises(SO1AuthorityError,match="SO1_PRICE_UNAVAILABLE"):service.resolve_price(ResolvePrice(1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD","USD",now,ScopeType.TENANT,None))
    assert service.deactivate_price(1,price.public_id,1).active is False

def test_ambiguous_equal_rank_price_fails():
    repo=MemoryRepository();service=authority(repo);now=datetime(2026,8,13,12,tzinfo=timezone.utc);unit=service.create_atomic_unit(CreateAtomicUnit("u",1,"FEE","Fee"))
    command=DefinePrice("p",1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD",Decimal("10"),"USD",ScopeType.TENANT,None,1,now)
    service.define_price(command);service.define_price(command)
    with pytest.raises(ValueError,match="SO1_AMBIGUOUS_PRICE"):service.resolve_price(ResolvePrice(1,TargetType.ATOMIC_UNIT,unit.public_id,"STANDARD","USD",now,ScopeType.TENANT,None))

def test_tenant_isolation_and_cross_tenant_references_fail_closed():
    repo=MemoryRepository();service=authority(repo);unit=service.create_atomic_unit(CreateAtomicUnit("u",2,"OTHER","Other"))
    with pytest.raises(SO1AuthorityError,match="SO1_NOT_FOUND"):service.atomic_unit(1,unit.public_id)
    with pytest.raises(ValueError,match="cross tenant"):service.create_offer(CreateOffer("o",1,"BAD","Bad",(OfferComponent(unit.public_id,Decimal("1"),ComponentRule.REQUIRED,1),)))

def test_permission_is_server_side_and_global_identity_does_not_grant_access():
    ids=iter([UUID(int=1)]);service=SO1Authority(MemoryRepository(),authorize=lambda *args:False,validate_scope=lambda *args:True,public_id_factory=lambda:next(ids))
    with pytest.raises(SO1AuthorityError,match="SO1_PERMISSION_DENIED"):service.create_atomic_unit(CreateAtomicUnit("u",1,"X","X"))

def test_two_materially_different_neutral_profiles_use_same_contract():
    a=load("examples/retail_service_profile.json");b=load("examples/professional_service_profile.json")
    assert a["currency"]!=b["currency"] and a["atomic_units"]!=b["atomic_units"] and a["offer"]!=b["offer"]
    assert a["source_changes"]==b["source_changes"]=="NONE"

def test_no_industry_specific_active_defaults():
    forbidden=(bytes((87,78,68)),b"Wine & Dine",b"Logpom",b"meal",b"menu item")
    for base in (ROOT/"shared_operations/so1",CONTRACTS):
        for path in base.rglob("*"):
            if path.is_file() and path.name!="so1_release_manifest.json":assert not any(x.lower() in path.read_bytes().lower() for x in forbidden)

def test_so0_public_private_law_and_xa_hooks_are_present():
    interface=load("so1_public_interfaces.json");xa=load("so1_xa_metadata.json")
    assert interface["cross_module_private_access"]=="FORBIDDEN" and interface["private_package"].endswith("sql_repository")
    assert xa["price_display"]["frontend_calculation"]=="FORBIDDEN" and not xa["navigation"][0]["visibility_is_authorization"]

def test_price_mutation_has_no_finance_contract_or_automatic_effect():
    authority_contract=load("so1_authority.json");interface=load("so1_public_interfaces.json")
    assert authority_contract["financial_side_effects"]=="NONE" and interface["finance_integration_points"]==[]

def test_migration_is_additive_single_head_and_preserves_dependencies():
    wrapper=(ROOT/"alembic_neutral/versions/so1_atomic_catalog_offer_pricing_026.py").read_text()
    assert f'revision = "{HEAD}"' in wrapper and f'down_revision = "{PREVIOUS}"' in wrapper
    assert load("so1_authority.json")["production_dependency_changes"]=="NONE"
