"""PC2 static validation and controlled local PostgreSQL acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from core.platform.architecture_contract import validate_pc0

EXPECTED_SOURCE="3190a07"
EXPECTED_PREVIOUS_HEAD="pc1_structural_context_021"
EXPECTED_HEAD="pc2_party_authority_022"
DEVELOPMENT_DATABASE_NAME="xbos_track_b_dev"
TEST_DATABASE_NAME="xbos_platform_core_pc2_test"
LOCAL_HOSTS={"localhost","127.0.0.1","::1"}
FINANCIAL_TABLES=("financial_events","journal_entries","journal_lines","financial_obligations","value_sources","payment_allocations","canonical_payment_intents","payment_settlements","outbox_messages","reconciliation_controls","financial_counterparties")


def static_verify() -> dict[str,object]:
    party=json.loads((ROOT/"contracts/platform/v1/pc2_party_authority.json").read_text(encoding="utf-8"))
    compatibility=json.loads((ROOT/"contracts/platform/v1/pc2_compatibility_migration_manifest.json").read_text(encoding="utf-8"))
    interfaces=json.loads((ROOT/"contracts/platform/v1/pc2_public_interfaces.json").read_text(encoding="utf-8"))
    release=json.loads((ROOT/"contracts/platform/v1/pc2_release_manifest.json").read_text(encoding="utf-8"))
    if party["scope"] != [f"PC2.{n}" for n in range(1,12)]:raise RuntimeError("PC2 scope incomplete")
    if party["source_checkpoint"]!=EXPECTED_SOURCE or party["previous_head"]!=EXPECTED_PREVIOUS_HEAD or party["accepted_head"]!=EXPECTED_HEAD:raise RuntimeError("PC2 checkpoint or lineage contract mismatch")
    required={"users":"MAP/BRIDGE","financial_counterparties":"PRESERVE/BRIDGE","legal_entities":"PRESERVE/LINK","organization_units":"PRESERVE/REFERENCE","locations":"PRESERVE/REFERENCE"}
    found={item["authority"]:item["classification"] for item in compatibility["entries"]}
    if not all(found.get(key)==value for key,value in required.items()):raise RuntimeError("PC2 compatibility classification mismatch")
    if any(item.get("automatic_conversion") is not False for item in compatibility["entries"]):raise RuntimeError("PC2 automatic compatibility conversion forbidden")
    if interfaces["module"]!="party" or "authentication writer" in " ".join(interfaces["public"]).lower():raise RuntimeError("PC2 public interface boundary mismatch")
    version=(ROOT/"alembic_neutral/versions/pc2_party_authority_022_party_person_organization_roles_relationships.py").read_text(encoding="utf-8")
    if f'revision = "{EXPECTED_HEAD}"' not in version or f'down_revision = "{EXPECTED_PREVIOUS_HEAD}"' not in version:raise RuntimeError("PC2 migration is not canonical child")
    up=(ROOT/"alembic_neutral/sql/pc2_party_authority_up.sql").read_text(encoding="utf-8")
    forbidden=("UPDATE public.financial_","DELETE FROM public.financial_","INSERT INTO public.users","INSERT INTO public.parties")
    if any(marker in up for marker in forbidden):raise RuntimeError("PC2 migration contains forbidden data mutation or seed")
    replacements = {}
    for manifest_name in ("pc4_release_manifest.json","pc3_release_manifest.json"):
        descendant_manifest=ROOT/"contracts/platform/v1"/manifest_name
        if descendant_manifest.is_file():
            descendant=json.loads(descendant_manifest.read_text(encoding="utf-8"));replacements={item["path"]:item for item in descendant.get("historical_pc2_replacements",[])}
            if replacements:break
    for item in release["artifacts"]:
        path=ROOT/item["path"]
        actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        replacement=replacements.get(item["path"])
        accepted=actual==item["sha256"] or (replacement is not None and replacement.get("historical_sha256")==item["sha256"] and replacement.get("descendant_sha256")==actual)
        if not accepted:raise RuntimeError(f"PC2 release manifest mismatch={item['path']}")
    pc0=validate_pc0(ROOT)
    return {"status":"PASS","pc0":pc0["status"],"previous_head":EXPECTED_PREVIOUS_HEAD,"accepted_head":EXPECTED_HEAD,"compatibility_entries":len(compatibility["entries"]),"release_artifacts":len(release["artifacts"])}


def database_acceptance() -> dict[str,object]:
    from alembic import command as alembic_command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from database import engine as application_engine
    from core.platform.party import AddPartyContact,AddPartyIdentifier,AssignPartyRole,CreateOrganizationParty,CreatePartyRelationship,CreatePerson,LinkLegalEntityParty,PartyAuthority,PartyAuthorityError,SQLPartyRepository
    from core.platform.structure import SQLStructuralRepository,StructuralAuthority
    from core.platform.structure.contracts import ProvisionTenant

    url=make_url(application_engine.url)
    if url.host not in LOCAL_HOSTS:raise RuntimeError("refusing non-local PostgreSQL target")
    if url.database!=DEVELOPMENT_DATABASE_NAME:raise RuntimeError("configured development database mismatch")
    def selected(name,autocommit=False):return create_engine(url.set(database=name),pool_pre_ping=True,**({"isolation_level":"AUTOCOMMIT"} if autocommit else {}))
    admin=selected("postgres",True)
    with admin.connect() as connection:
        if connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"),{"name":TEST_DATABASE_NAME}).scalar_one_or_none():
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),{"name":TEST_DATABASE_NAME});connection.exec_driver_sql(f'DROP DATABASE "{TEST_DATABASE_NAME}"')
        connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0')
    admin.dispose()
    @contextmanager
    def target_database(name=TEST_DATABASE_NAME):
        previous=os.environ.get("DATABASE_URL");os.environ["DATABASE_URL"]=url.set(database=name).render_as_string(hide_password=False)
        try:yield
        finally:
            if previous is None:os.environ.pop("DATABASE_URL",None)
            else:os.environ["DATABASE_URL"]=previous
    config=Config(str(ROOT/"alembic.ini"));disposable=None
    try:
        with target_database():alembic_command.upgrade(config,EXPECTED_PREVIOUS_HEAD)
        disposable=selected(TEST_DATABASE_NAME)
        tenant_commands=(
            ProvisionTenant("pc2-tenant-1","PC2-T1","PC2 Tenant 1","CM","XAF","fr-CM","Africa/Douala","LE","PC2 Legal 1","ROOT","Root 1","HQ","HQ 1"),
            ProvisionTenant("pc2-tenant-2","PC2-T2","PC2 Tenant 2","CM","XAF","fr-CM","Africa/Douala","LE","PC2 Legal 2","ROOT","Root 2","HQ","HQ 2"),
        )
        contexts=[]
        for command in tenant_commands:
            with Session(disposable,expire_on_commit=False) as session,session.begin():contexts.append(StructuralAuthority(SQLStructuralRepository(session)).provision(command))
        with target_database():alembic_command.upgrade(config,EXPECTED_HEAD)
        with Session(disposable,expire_on_commit=False) as session,session.begin():
            authority=PartyAuthority(SQLPartyRepository(session));tenant=contexts[0].tenant.id
            person=authority.create_person(CreatePerson("pc2-person",tenant,"employee-001","Ada","Lovelace"))
            organization=authority.create_organization(CreateOrganizationParty("pc2-org",tenant,"org-001","Analytical Engines Ltd","REG-001"))
            if person.party.kind.value==organization.party.kind.value:raise RuntimeError("Party subtypes collapsed")
            role1=authority.assign_role(AssignPartyRole("pc2-customer",tenant,person.party.id,"customer",date(2026,1,1),legal_entity_id=contexts[0].legal_entity.id))
            role2=authority.assign_role(AssignPartyRole("pc2-supplier",tenant,person.party.id,"supplier",date(2026,1,1)))
            if role1.role_code==role2.role_code:raise RuntimeError("multiple Party business roles collapsed")
            relationship=authority.create_relationship(CreatePartyRelationship("pc2-employed",tenant,person.party.id,organization.party.id,"employee_of",True,date(2026,1,1)))
            if not relationship.directed:raise RuntimeError("relationship direction lost")
            authority.add_identifier(AddPartyIdentifier("pc2-tax-id",tenant,organization.party.id,"tax_reference","CM-PC2-001",date(2026,1,1),is_primary=True))
            authority.add_contact(AddPartyContact("pc2-contact",tenant,organization.party.id,"email","pc2@example.test",date(2026,1,1),is_primary=True))
            authority.link_legal_entity(LinkLegalEntityParty("pc2-legal-link",tenant,contexts[0].legal_entity.id,organization.party.id))
            session.execute(text("INSERT INTO party_compatibility_mappings(tenant_id,source_authority,source_record_id,party_id,mapping_basis) VALUES(:t,'users','operator-fixture',:p,'operator_approved')"),{"t":tenant,"p":person.party.id})
            if authority.resolve_reference(tenant_id=tenant,scheme="external_key",value="EMPLOYEE-001")!=person.party:raise RuntimeError("deterministic Party reference failed")
            export=authority.export(tenant)
            if export!=authority.export(tenant) or b'"schema":"xbos.pc2.party-export.v1"' not in export:raise RuntimeError("Party export is nondeterministic")
            first_person,first_organization=person,organization
        with Session(disposable,expire_on_commit=False) as session,session.begin():
            second_person=PartyAuthority(SQLPartyRepository(session)).create_person(
                CreatePerson("pc2-second-person",contexts[1].tenant.id,"second-person","Grace","Hopper")
            )
        with Session(disposable) as session,session.begin():
            authority=PartyAuthority(SQLPartyRepository(session))
            try:authority.create_relationship(CreatePartyRelationship("pc2-cross",contexts[0].tenant.id,first_person.party.id,second_person.party.id,"employee_of",True,date(2026,1,1)))
            except PartyAuthorityError as exc:
                if exc.code!="party_not_found_or_cross_tenant":raise
            else:raise RuntimeError("cross-tenant relationship passed")
        try:
            with Session(disposable) as session,session.begin():
                PartyAuthority(SQLPartyRepository(session)).create_relationship(
                    CreatePartyRelationship("pc2-conflicting-dates",contexts[0].tenant.id,first_person.party.id,first_organization.party.id,"employee_of",True,date(2026,1,1),date(2026,12,31))
                )
        except PartyAuthorityError as exc:
            if exc.code!="conflicting_relationship_validity":raise
        else:raise RuntimeError("conflicting relationship effective dates passed")
        role_command=AssignPartyRole("pc2-concurrent-role",contexts[0].tenant.id,first_person.party.id,"contractor",date(2026,2,1))
        relationship_command=CreatePartyRelationship("pc2-concurrent-rel",contexts[0].tenant.id,first_person.party.id,first_organization.party.id,"representative_of",True,date(2026,2,1))
        def concurrent(kind):
            with Session(disposable,expire_on_commit=False) as session,session.begin():
                authority=PartyAuthority(SQLPartyRepository(session));result=authority.assign_role(role_command) if kind=="role" else authority.create_relationship(relationship_command);return result.id
        with ThreadPoolExecutor(max_workers=2) as executor:
            if len(set(executor.map(lambda _:concurrent("role"),range(2))))!=1:raise RuntimeError("concurrent role replay diverged")
        with ThreadPoolExecutor(max_workers=2) as executor:
            if len(set(executor.map(lambda _:concurrent("relationship"),range(2))))!=1:raise RuntimeError("concurrent relationship replay diverged")
        with target_database():alembic_command.downgrade(config,EXPECTED_PREVIOUS_HEAD);alembic_command.upgrade(config,EXPECTED_HEAD)
        with disposable.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()!=EXPECTED_HEAD:raise RuntimeError("PC2 downgrade/re-upgrade failed")
        with application_engine.connect() as connection:
            current=connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if current not in {EXPECTED_PREVIOUS_HEAD,EXPECTED_HEAD}:raise RuntimeError(f"development lineage mismatch={current}")
            existing=set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
            before={table:connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCIAL_TABLES if table in existing}
        if current==EXPECTED_PREVIOUS_HEAD:
            with target_database(DEVELOPMENT_DATABASE_NAME):alembic_command.upgrade(config,EXPECTED_HEAD)
        with application_engine.connect() as connection:
            after_head=connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one();after={table:connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in before}
        if after_head!=EXPECTED_HEAD or after!=before:raise RuntimeError("development upgrade changed financial effects")
    except Exception:raise
    else:
        if disposable:disposable.dispose()
        admin=selected("postgres",True)
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"),{"name":TEST_DATABASE_NAME});connection.exec_driver_sql(f'DROP DATABASE "{TEST_DATABASE_NAME}"')
        admin.dispose()
    return {"disposable":"PASS","downgrade_reupgrade":"PASS","development_head":EXPECTED_HEAD,"financial_effects":"UNCHANGED","cleanup":"PASS"}


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance:result["database"]=database_acceptance()
    except Exception as exc:print(f"PC2_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("PC2_VERIFY=PASS");return 0


if __name__=="__main__":raise SystemExit(main())
