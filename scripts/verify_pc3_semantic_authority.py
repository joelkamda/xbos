"""PC3 static validation and controlled local PostgreSQL acceptance."""
from __future__ import annotations
import argparse,hashlib,json,os,sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.platform.architecture_contract import validate_pc0

SOURCE="0163039";PREVIOUS="pc2_party_authority_022";HEAD="pc3_semantic_authority_023"
DEV="xbos_track_b_dev";TEST="xbos_platform_core_pc3_test";LOCAL={"localhost","127.0.0.1","::1"}
FINANCIAL=("financial_events","journal_entries","journal_lines","financial_obligations","value_sources","payment_allocations","canonical_payment_intents","payment_settlements","outbox_messages","reconciliation_controls","financial_counterparties")

def static_verify():
    contract=json.loads((ROOT/"contracts/platform/v1/pc3_semantic_authority.json").read_text())
    adoption=json.loads((ROOT/"contracts/platform/v1/pc3_taxonomy_adoption_manifest.json").read_text())
    release=json.loads((ROOT/"contracts/platform/v1/pc3_release_manifest.json").read_text())
    if contract["scope"]!=[f"PC3.{n}" for n in range(1,12)]:raise RuntimeError("PC3 scope incomplete")
    if (contract["source_checkpoint"],contract["previous_head"],contract["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("PC3 checkpoint/lineage mismatch")
    found={item["authority"]:item["classification"] for item in adoption["entries"]}
    required={"taxonomy_nodes":"ADOPT/EVOLVE","atomic_unit_taxonomy":"PRESERVE/BRIDGE","atomic_units":"PRESERVE","semantic_level":"BRIDGE","taxonomy_type":"BRIDGE","Finance semantic catalogs":"PRESERVE"}
    if not all(found.get(k)==v for k,v in required.items()):raise RuntimeError("PC3 taxonomy adoption classification mismatch")
    version=(ROOT/"alembic_neutral/versions/pc3_semantic_authority_023_namespaces_taxonomy_mapping_classification.py").read_text()
    if f'revision = "{HEAD}"' not in version or f'down_revision = "{PREVIOUS}"' not in version:raise RuntimeError("PC3 migration is not canonical child")
    up=(ROOT/"alembic_neutral/sql/pc3_semantic_authority_up.sql").read_text()
    forbidden=("INSERT INTO public.taxonomy_nodes","UPDATE public.taxonomy_nodes","DELETE FROM public.taxonomy_nodes","ALTER TABLE public.atomic_units","UPDATE public.financial_","DELETE FROM public.financial_")
    if any(value in up for value in forbidden):raise RuntimeError("PC3 migration contains forbidden legacy/Finance mutation")
    for item in release["artifacts"]:
        path=ROOT/item["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:raise RuntimeError(f"PC3 release manifest mismatch={item['path']}")
    pc0=validate_pc0(ROOT)
    return {"status":"PASS","pc0":pc0["status"],"previous_head":PREVIOUS,"accepted_head":HEAD,"adoption_entries":len(adoption["entries"]),"release_artifacts":len(release["artifacts"])}

def database_acceptance():
    from alembic import command as alembic_command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from database import engine as application_engine
    from core.platform.semantics import AssignClassification,CreateConcept,CreateMapping,CreateNamespace,CreateSemanticVersion,MappingType,MoveTaxonomyNode,NamespaceScope,SQLSemanticRepository,SemanticAuthority,SemanticAuthorityError
    from core.platform.structure import SQLStructuralRepository,StructuralAuthority
    from core.platform.structure.contracts import ProvisionTenant
    url=make_url(application_engine.url)
    if url.host not in LOCAL:raise RuntimeError("refusing non-local PostgreSQL target")
    if url.database!=DEV:raise RuntimeError("configured development database mismatch")
    def selected(name,auto=False):return create_engine(url.set(database=name),pool_pre_ping=True,**({"isolation_level":"AUTOCOMMIT"} if auto else {}))
    admin=selected("postgres",True)
    with admin.connect() as c:
        if c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"),{"n":TEST}).scalar_one_or_none():c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":TEST});c.exec_driver_sql(f'DROP DATABASE "{TEST}"')
        c.exec_driver_sql(f'CREATE DATABASE "{TEST}" TEMPLATE template0')
    admin.dispose()
    @contextmanager
    def target(name=TEST):
        prior=os.environ.get("DATABASE_URL");os.environ["DATABASE_URL"]=url.set(database=name).render_as_string(hide_password=False)
        try:yield
        finally:
            if prior is None:os.environ.pop("DATABASE_URL",None)
            else:os.environ["DATABASE_URL"]=prior
    config=Config(str(ROOT/"alembic.ini"));db=None
    try:
        with target():alembic_command.upgrade(config,PREVIOUS)
        db=selected(TEST)
        with Session(db,expire_on_commit=False) as session,session.begin():
            context=StructuralAuthority(SQLStructuralRepository(session)).provision(ProvisionTenant("pc3-tenant","PC3","PC3 Tenant","CM","XAF","fr-CM","Africa/Douala","LE","PC3 Legal","ROOT","Root","HQ","HQ"))
            tenant=context.tenant.id
            session.execute(text("INSERT INTO taxonomy_nodes(tenant_id,parent_id,name,semantic_level,taxonomy_type,sort_order,is_active) VALUES(:t,NULL,'Legacy Root','domain','COMMERCE',0,true)"),{"t":tenant})
            session.execute(text("INSERT INTO atomic_units(tenant_id,name,sku,is_active) VALUES(:t,'Legacy Unit','PC3-UNIT',true)"),{"t":tenant})
        with target():alembic_command.upgrade(config,HEAD)
        with Session(db,expire_on_commit=False) as session,session.begin():
            authority=SemanticAuthority(SQLSemanticRepository(session))
            namespace=authority.create_namespace(CreateNamespace("pc3-ns","kernel",NamespaceScope.KERNEL,"pc3"))
            concept=authority.create_concept(CreateConcept("pc3-concept","kernel","pc3","business_object"))
            version=authority.create_version(CreateSemanticVersion("pc3-version","kernel","pc3","business_object",1,date(2026,1,1),None,"Business Object","Neutral business object"))
            tenant_namespace=authority.create_namespace(CreateNamespace("pc3-tenant-ns",f"tenant.{tenant}",NamespaceScope.TENANT,f"tenant:{tenant}",tenant))
            custom=authority.create_concept(CreateConcept("pc3-custom",tenant_namespace.namespace_code,tenant_namespace.owner_code,"custom"))
            authority.create_version(CreateSemanticVersion("pc3-custom-v",tenant_namespace.namespace_code,tenant_namespace.owner_code,"custom",1,date(2026,1,1),None,"Custom","Tenant custom meaning"))
            mapping=authority.create_mapping(CreateMapping("pc3-map","pc3-map","pc3",custom.qualified_code,concept.qualified_code,MappingType.RELATED,date(2026,1,1)))
            node=session.execute(text("SELECT id FROM taxonomy_nodes WHERE tenant_id=:t AND name='Legacy Root'"),{"t":tenant}).scalar_one()
            unit=session.execute(text("SELECT id FROM atomic_units WHERE tenant_id=:t AND sku='PC3-UNIT'"),{"t":tenant}).scalar_one()
            snapshot=authority.assign(AssignClassification("pc3-assignment",tenant,"atomic_unit",str(unit),concept.qualified_code,date(2026,6,1),node))
            session.execute(text("UPDATE taxonomy_nodes SET semantic_concept_id=:c WHERE tenant_id=:t AND id=:n"),{"c":concept.id,"t":tenant,"n":node})
            resolved=authority.resolve(qualified_code=concept.qualified_code,effective_on=date(2026,6,1),tenant_id=tenant)
            if resolved!=(concept,version) or snapshot.concept_qualified_code!=concept.qualified_code:raise RuntimeError("deterministic semantic resolution/snapshot failed")
            impact=authority.impact(concept.qualified_code)
            if impact["safe_to_retire"] or impact["counts"]["assignments"]!=1:raise RuntimeError("semantic impact analysis failed")
            export=authority.export(tenant)
            if export!=authority.export(tenant):raise RuntimeError("semantic export nondeterministic")
        with Session(db) as session,session.begin():
            authority=SemanticAuthority(SQLSemanticRepository(session))
            try:authority.create_concept(CreateConcept("pc3-unauthorized","kernel","tenant:attacker","override"))
            except SemanticAuthorityError as exc:
                if exc.code!="unauthorized_namespace_mutation":raise
            else:raise RuntimeError("namespace ownership violation passed")
            try:authority.resolve(qualified_code=tenant_namespace.namespace_code+":custom",effective_on=date(2026,6,1),tenant_id=tenant+1)
            except SemanticAuthorityError as exc:
                if exc.code!="semantic_reference_not_found_or_not_effective":raise
            else:raise RuntimeError("cross-tenant semantic lookup passed")
        def replay(kind):
            with Session(db,expire_on_commit=False) as session,session.begin():
                authority=SemanticAuthority(SQLSemanticRepository(session))
                if kind=="mapping":return authority.create_mapping(CreateMapping("pc3-concurrent-map","pc3-map","pc3",custom.qualified_code,concept.qualified_code,MappingType.EXACT,date(2026,2,1))).id
                return authority.assign(AssignClassification("pc3-concurrent-assignment",tenant,"atomic_unit",str(unit),custom.qualified_code,date(2026,6,1),node)).assignment_id
        for kind in ("mapping","assignment"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                if len(set(pool.map(lambda _:replay(kind),range(2))))!=1:raise RuntimeError(f"concurrent {kind} replay diverged")
        with db.begin() as c:
            child=c.execute(text("INSERT INTO taxonomy_nodes(tenant_id,parent_id,name,semantic_level,taxonomy_type,sort_order,is_active) VALUES(:t,:p,'Child','domain','COMMERCE',1,true) RETURNING id"),{"t":tenant,"p":node}).scalar_one()
        def concurrent_move(_):
            with Session(db,expire_on_commit=False) as session,session.begin():
                return SemanticAuthority(SQLSemanticRepository(session)).move_taxonomy_node(MoveTaxonomyNode(tenant,child,None,1)).semantic_row_version
        move_results=[];move_failures=[]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(concurrent_move,index) for index in range(2)]
            for future in futures:
                try:move_results.append(future.result())
                except SemanticAuthorityError as exc:move_failures.append(exc.code)
        if move_results!=[2] or move_failures!=["taxonomy_not_found_cross_tenant_or_concurrent_change"]:raise RuntimeError(f"taxonomy parent concurrency guard failed={move_results},{move_failures}")
        with db.begin() as c:c.execute(text("UPDATE taxonomy_nodes SET parent_id=:p WHERE tenant_id=:t AND id=:child"),{"p":node,"t":tenant,"child":child})
        try:
            with db.begin() as c:c.execute(text("UPDATE taxonomy_nodes SET parent_id=:child WHERE tenant_id=:t AND id=:root"),{"child":child,"t":tenant,"root":node})
        except Exception as exc:
            if "taxonomy_cycle" not in str(exc):raise RuntimeError("taxonomy cycle guard returned unexpected error") from exc
        else:raise RuntimeError("taxonomy cycle passed")
        with target():alembic_command.downgrade(config,PREVIOUS);alembic_command.upgrade(config,HEAD)
        with application_engine.connect() as c:
            current=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one();tables=set(c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars());before={t:c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in FINANCIAL if t in tables}
        if current not in {PREVIOUS,HEAD}:raise RuntimeError(f"development lineage mismatch={current}")
        if current==PREVIOUS:
            with target(DEV):alembic_command.upgrade(config,HEAD)
        with application_engine.connect() as c:after_head=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one();after={t:c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in before}
        if after_head!=HEAD or after!=before:raise RuntimeError("development upgrade changed financial effects")
    except Exception:raise
    else:
        if db:db.dispose()
        admin=selected("postgres",True)
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":TEST});c.exec_driver_sql(f'DROP DATABASE "{TEST}"')
        admin.dispose()
    return {"disposable":"PASS","downgrade_reupgrade":"PASS","development_head":HEAD,"financial_effects":"UNCHANGED","cleanup":"PASS"}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance:result["database"]=database_acceptance()
    except Exception as exc:print(f"PC3_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("PC3_VERIFY=PASS");return 0
if __name__=="__main__":raise SystemExit(main())
