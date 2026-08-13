"""PC1 static validation and controlled local PostgreSQL acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from core.platform.architecture_contract import validate_pc0

EXPECTED_PREVIOUS_HEAD = "m64_reconciliation_controls_020"
EXPECTED_HEAD = "pc1_structural_context_021"
DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_platform_core_pc1_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
FINANCIAL_TABLES = (
    "financial_events","journal_entries","journal_lines","financial_obligations","value_sources",
    "payment_allocations","allocation_reversals","canonical_payment_intents","canonical_payment_attempts",
    "payment_settlements","outbox_messages","reconciliation_windows","reconciliation_controls",
)


def validate_structural_distinction(context: object) -> None:
    """Prove semantic authority distinctions without comparing table-local IDs."""

    from core.platform.structure.contracts import LegalEntity, Location, OrganizationUnit, Tenant

    tenant = context.tenant
    organization = context.organization_unit
    legal_entity = context.legal_entity
    location = context.location
    if not isinstance(tenant, Tenant):
        raise RuntimeError("structural context has invalid tenant authority type")
    if not isinstance(organization, OrganizationUnit):
        raise RuntimeError("structural context has invalid organization-unit authority type")
    if not isinstance(legal_entity, LegalEntity):
        raise RuntimeError("structural context has invalid legal-entity authority type")
    if not isinstance(location, Location):
        raise RuntimeError("structural context has invalid location authority type")
    if {organization.tenant_id, legal_entity.tenant_id, location.tenant_id} != {tenant.id}:
        raise RuntimeError("structural context crosses tenant authority")
    if organization.legal_entity_id != legal_entity.id:
        raise RuntimeError("organization-unit legal-entity relationship is inconsistent")
    if location.legal_entity_id != legal_entity.id:
        raise RuntimeError("location legal-entity relationship is inconsistent")


def static_verify() -> dict[str, object]:
    contract = json.loads((ROOT / "contracts/platform/v1/pc1_structural_authority.json").read_text(encoding="utf-8"))
    compatibility = json.loads((ROOT / "contracts/platform/v1/pc1_compatibility_migration_manifest.json").read_text(encoding="utf-8"))
    release = json.loads((ROOT / "contracts/platform/v1/pc1_release_manifest.json").read_text(encoding="utf-8"))
    if contract["scope"] != [f"PC1.{number}" for number in range(1, 11)]: raise RuntimeError("PC1 scope incomplete")
    if contract["previous_head"] != EXPECTED_PREVIOUS_HEAD or contract["accepted_head"] != EXPECTED_HEAD: raise RuntimeError("PC1 lineage contract mismatch")
    classifications = {item["authority"]: item["classification"] for item in compatibility["entries"]}
    required = {"tenants":"ADOPT/EVOLVE","organization_units":"ADOPT/PROMOTE","branches":"MAP/BRIDGE","finance_organization_references":"PRESERVE"}
    if not all(classifications.get(key) == value for key,value in required.items()): raise RuntimeError("compatibility classification mismatch")
    version = (ROOT / "alembic_neutral/versions/pc1_structural_context_021_tenant_organization_legal_location.py").read_text(encoding="utf-8")
    if f'revision = "{EXPECTED_HEAD}"' not in version or f'down_revision = "{EXPECTED_PREVIOUS_HEAD}"' not in version: raise RuntimeError("PC1 migration is not canonical child")
    up = (ROOT / "alembic_neutral/sql/pc1_structural_context_up.sql").read_text(encoding="utf-8")
    forbidden = ("INSERT INTO public.financial_events","UPDATE public.journal_entries","DELETE FROM public.financial_")
    if any(marker in up for marker in forbidden): raise RuntimeError("PC1 migration contains financial economic mutation")
    replacements = {}
    for manifest_name in ("pc3_release_manifest.json", "pc2_release_manifest.json"):
        descendant_manifest = ROOT / "contracts/platform/v1" / manifest_name
        if descendant_manifest.is_file():
            descendant = json.loads(descendant_manifest.read_text(encoding="utf-8"))
            replacements = {item["path"]: item for item in descendant.get("historical_pc1_replacements", [])}
            if replacements:
                break
    for artifact in release.get("artifacts", []):
        path = ROOT / artifact["path"]
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        replacement = replacements.get(artifact["path"])
        accepted = actual == artifact["sha256"] or (
            replacement is not None
            and replacement.get("historical_sha256") == artifact["sha256"]
            and replacement.get("descendant_sha256") == actual
        )
        if not accepted:
            raise RuntimeError(f"PC1 release manifest mismatch={artifact['path']}")
    pc0 = validate_pc0(ROOT)
    return {"status":"PASS","pc0":pc0["status"],"previous_head":EXPECTED_PREVIOUS_HEAD,"accepted_head":EXPECTED_HEAD,"compatibility_entries":len(compatibility["entries"]),"release_artifacts":len(release["artifacts"])}


def database_acceptance() -> dict[str, object]:
    from alembic import command as alembic_command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from database import engine as application_engine
    from core.platform.structure.contracts import ProvisionTenant, TenantLifecycle
    from core.platform.structure.service import StructuralAuthority, StructuralAuthorityError
    from core.platform.structure.sql_repository import SQLStructuralRepository

    url = make_url(application_engine.url)
    if url.host not in LOCAL_HOSTS: raise RuntimeError("refusing non-local PostgreSQL target")
    if url.database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError("configured development database mismatch")
    def selected(name: str, autocommit: bool = False):
        options = {"pool_pre_ping": True}
        if autocommit: options["isolation_level"] = "AUTOCOMMIT"
        return create_engine(url.set(database=name), **options)
    admin = selected("postgres", True)
    with admin.connect() as connection:
        exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": TEST_DATABASE_NAME}).scalar_one_or_none()
        if exists:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": TEST_DATABASE_NAME})
            connection.exec_driver_sql(f'DROP DATABASE "{TEST_DATABASE_NAME}"')
        connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0')
    admin.dispose()
    @contextmanager
    def target_database():
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url.set(database=TEST_DATABASE_NAME).render_as_string(hide_password=False)
        try: yield
        finally:
            if previous is None: os.environ.pop("DATABASE_URL", None)
            else: os.environ["DATABASE_URL"] = previous
    config = Config(str(ROOT / "alembic.ini"))
    try:
        with target_database(): alembic_command.upgrade(config, EXPECTED_PREVIOUS_HEAD)
        disposable = selected(TEST_DATABASE_NAME)
        with disposable.begin() as connection:
            connection.execute(text("""INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone)
                VALUES(9101,'PC1-LEGACY','PC1 Legacy','CM','XAF','fr-CM','Africa/Douala')"""))
            connection.execute(text("""INSERT INTO branches(id,tenant_id,branch_code,name,city,address,is_active)
                VALUES(9101,9101,'LEGACY','Legacy Branch','Douala','Compatibility',true)"""))
            connection.execute(text("""INSERT INTO organization_units(id,tenant_id,unit_type,code,name,active)
                VALUES(9101,9101,'department','EXISTING','Existing Organization',true)"""))
        with target_database(): alembic_command.upgrade(config, EXPECTED_HEAD)
        with disposable.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            mapping = connection.execute(text("SELECT organization_unit_id,location_id FROM legacy_branch_structural_mappings WHERE tenant_id=9101 AND branch_id=9101")).first()
            if revision != EXPECTED_HEAD: raise RuntimeError(f"disposable head mismatch={revision}")
            if mapping is None: raise RuntimeError("legacy branch fixture was not mapped after PC1 migration")
            if not all(mapping): raise RuntimeError("legacy branch mapping contains an empty structural reference")
            mapped_organization_id, mapped_location_id = mapping
            fixture_counts = {
                "tenant": connection.execute(text("SELECT count(*) FROM tenants WHERE id=9101")).scalar_one(),
                "organization": connection.execute(text("SELECT count(*) FROM organization_units WHERE tenant_id=9101 AND id IN (9101,:mapped)"), {"mapped": mapped_organization_id}).scalar_one(),
                "location": connection.execute(text("SELECT count(*) FROM locations WHERE tenant_id=9101 AND id=:id"), {"id": mapped_location_id}).scalar_one(),
                "branch_mapping": connection.execute(text("SELECT count(*) FROM legacy_branch_structural_mappings WHERE tenant_id=9101 AND branch_id=9101")).scalar_one(),
            }
            if fixture_counts != {"tenant":1,"organization":2,"location":1,"branch_mapping":1}:
                raise RuntimeError(f"incomplete clean-replay fixture={fixture_counts}")
        command = ProvisionTenant("pc1-acceptance","PC1-NEW","PC1 New","CM","XAF","fr-CM","Africa/Douala","LE","PC1 Legal","ROOT","Root","HQ","Headquarters")
        with Session(disposable, expire_on_commit=False) as session, session.begin():
            authority = StructuralAuthority(SQLStructuralRepository(session))
            first = authority.provision(command)
            context = authority.resolve(
                tenant_id=first.tenant.id,
                organization_unit_id=first.organization_unit.id,
                legal_entity_id=first.legal_entity.id,
                location_id=first.location.id,
            )
            validate_structural_distinction(context)
            first_export = authority.export(first.tenant.id)
            if first_export != authority.export(first.tenant.id): raise RuntimeError("tenant structural export is nondeterministic")
            if any(marker in first_export.lower() for marker in (b"journal",b"payment",b"outbox")):
                raise RuntimeError("structural export contains financial effects")
        with Session(disposable, expire_on_commit=False) as session, session.begin():
            authority = StructuralAuthority(SQLStructuralRepository(session))
            replay = authority.provision(command)
            if first.tenant.id != replay.tenant.id: raise RuntimeError("provisioning replay changed tenant identity")
            suspended = authority.transition_tenant(first.tenant.id, first.tenant.row_version, TenantLifecycle.SUSPENDED)
            if suspended.lifecycle is not TenantLifecycle.SUSPENDED: raise RuntimeError("tenant suspension failed")
        with Session(disposable, expire_on_commit=False) as session, session.begin():
            authority = StructuralAuthority(SQLStructuralRepository(session))
            try: authority.resolve(tenant_id=first.tenant.id)
            except StructuralAuthorityError as exc:
                if exc.code != "tenant_unavailable": raise
            else: raise RuntimeError("suspended tenant remained available")
            authority.transition_tenant(first.tenant.id, 2, TenantLifecycle.ACTIVE)
        with Session(disposable) as session, session.begin():
            try: StructuralAuthority(SQLStructuralRepository(session)).provision(ProvisionTenant(**{**command.__dict__,"tenant_name":"Conflict"}))
            except StructuralAuthorityError as exc:
                if exc.code != "conflicting_provisioning_replay": raise
            else: raise RuntimeError("conflicting provisioning replay passed")

        second_command = ProvisionTenant("pc1-second","PC1-SECOND","PC1 Second","CM","XAF","fr-CM","Africa/Douala","LE","Second Legal","ROOT","Second Root","HQ","Second HQ")
        with Session(disposable, expire_on_commit=False) as session, session.begin():
            second = StructuralAuthority(SQLStructuralRepository(session)).provision(second_command)
        with Session(disposable) as session, session.begin():
            authority = StructuralAuthority(SQLStructuralRepository(session))
            try: authority.resolve(tenant_id=first.tenant.id, organization_unit_id=second.organization_unit.id)
            except StructuralAuthorityError as exc:
                if exc.code != "organization_not_found_or_cross_tenant": raise
            else: raise RuntimeError("cross-tenant structural resolution passed")

        with disposable.begin() as connection:
            connection.execute(text("UPDATE organization_units SET parent_id=9101 WHERE tenant_id=9101 AND id=:mapped"), {"mapped": mapped_organization_id})
        with Session(disposable) as session, session.begin():
            legacy = StructuralAuthority(SQLStructuralRepository(session)).resolve(tenant_id=9101, legacy_branch_id=9101)
            if legacy.ancestry != (9101, mapped_organization_id) or legacy.location.id != mapped_location_id:
                raise RuntimeError("legacy branch context or ancestry is nondeterministic")
        try:
            with disposable.begin() as connection:
                connection.execute(text("UPDATE organization_units SET parent_id=:mapped WHERE tenant_id=9101 AND id=9101"), {"mapped": mapped_organization_id})
        except Exception as exc:
            if "organization_cycle" not in str(exc): raise RuntimeError("cycle guard failed with unexpected error") from exc
        else: raise RuntimeError("organization cycle was accepted")

        concurrent_command = ProvisionTenant("pc1-concurrent","PC1-CONCURRENT","PC1 Concurrent","CM","XAF","fr-CM","Africa/Douala","LE","Concurrent Legal","ROOT","Concurrent Root")
        def concurrent_provision() -> int:
            with Session(disposable, expire_on_commit=False) as session, session.begin():
                return StructuralAuthority(SQLStructuralRepository(session)).provision(concurrent_command).tenant.id
        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_ids = tuple(executor.map(lambda _index: concurrent_provision(), range(2)))
        if len(set(concurrent_ids)) != 1: raise RuntimeError(f"concurrent provisioning created competing tenants={concurrent_ids}")

        with target_database(): alembic_command.downgrade(config, EXPECTED_PREVIOUS_HEAD); alembic_command.upgrade(config, EXPECTED_HEAD)
        with disposable.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != EXPECTED_HEAD: raise RuntimeError("downgrade/re-upgrade failed")

        with application_engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if current not in {EXPECTED_PREVIOUS_HEAD, EXPECTED_HEAD}: raise RuntimeError(f"development lineage mismatch={current}")
            existing = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
            before = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCIAL_TABLES if table in existing}
        if current == EXPECTED_PREVIOUS_HEAD:
            with target_database():
                os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
                alembic_command.upgrade(config, EXPECTED_HEAD)
        with application_engine.connect() as connection:
            after_head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            after = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in before}
        if after_head != EXPECTED_HEAD or after != before: raise RuntimeError("development upgrade changed financial effects")
        disposable.dispose()
    except Exception:
        raise
    else:
        admin = selected("postgres", True)
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": TEST_DATABASE_NAME})
            connection.exec_driver_sql(f'DROP DATABASE "{TEST_DATABASE_NAME}"')
        admin.dispose()
    return {"disposable":"PASS","downgrade_reupgrade":"PASS","development_head":EXPECTED_HEAD,"financial_effects":"UNCHANGED","cleanup":"PASS"}


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance: result["database"] = database_acceptance()
    except Exception as exc:
        print(f"PC1_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("PC1_VERIFY=PASS");return 0


if __name__ == "__main__": raise SystemExit(main())
