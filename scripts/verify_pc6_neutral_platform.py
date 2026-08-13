#!/usr/bin/env python3
"""Verify PC6 neutrality, portability, isolation, operability, and freeze evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time as clock
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.platform.architecture_contract import validate_pc0
from core.platform.neutral_proof import deterministic_export, load_profile, restore_export
from core.platform.neutral_proof.dependency_authority import verify_dependency_authority
from core.platform.neutral_proof.leakage import scan_wnd_leakage
from core.platform.release_integrity import verify_historical_release, verify_latest_release
from scripts.bootstrap_pc6_tenant import _facades


SOURCE = "17c1d9c"
HEAD = PREVIOUS = "pc5_identity_policy_audit_025"
DEV = "xbos_track_b_dev"
TEST = "xbos_platform_core_pc6_test"
RESTORE = "xbos_platform_core_pc6_restore_test"
BACKUP_RESTORE = "xbos_platform_core_pc6_backup_restore_test"
LOCAL = {"localhost", "127.0.0.1", "::1"}
FINANCIAL = ("financial_events", "journal_entries", "journal_lines", "financial_obligations", "value_sources", "payment_allocations", "canonical_payment_intents", "payment_settlements", "outbox_messages", "reconciliation_controls", "reconciliation_calendar_policies")
PROFILE = ROOT / "profiles/platform_core/pc6_second_tenant.json"
CONTRACTS = ROOT / "contracts/platform/v1"


def _json(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _source_snapshot() -> str:
    digest = hashlib.sha256()
    roots = [ROOT / "core/platform", CONTRACTS, ROOT / "profiles/platform_core", ROOT / "requirements-prod.txt"]
    files = []
    for item in roots:
        files.extend(path for path in item.rglob("*") if path.is_file()) if item.is_dir() else files.append(item)
    for path in sorted(files):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(path.relative_to(ROOT).as_posix().encode());digest.update(b"\0");digest.update(path.read_bytes().replace(b"\r\n", b"\n"));digest.update(b"\0")
    return digest.hexdigest()


def _secret_default_scan() -> dict[str, object]:
    settings_path = ROOT / "settings.py"
    tree = ast.parse(settings_path.read_text(encoding="utf-8"), filename="settings.py")
    sensitive = {"JWT_SECRET", "DATABASE_URL", "GATEWAY_API_KEY"}
    declarations = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    declarations[child.target.id] = child.value
    missing = sorted(sensitive - declarations.keys())
    defaulted = sorted(name for name in sensitive if declarations.get(name) is not None)
    if missing or defaulted:
        raise RuntimeError(f"required secret or credential settings changed missing={missing}, defaulted={defaulted}")
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and line.split("=", 1)[1]:
            raise RuntimeError(".env.example contains credential or configuration material")
    scanned = [settings_path, ROOT / ".env.example", PROFILE]
    if any(b"-----BEGIN PRIVATE KEY-----" in path.read_bytes() for path in scanned):
        raise RuntimeError("embedded private key material detected")
    return {"status": "PASS", "required_without_defaults": sorted(sensitive), "files_scanned": len(scanned)}


def _canonical_startup_console_scan() -> dict[str, object]:
    startup_path = ROOT / "startup.py"
    tree = ast.parse(startup_path.read_text(encoding="utf-8"), filename="startup.py")
    selected = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"validate_permissions", "create_app"}}
    if set(selected) != {"validate_permissions", "create_app"}:
        raise RuntimeError("canonical startup functions missing")
    for name, function in selected.items():
        if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" for node in ast.walk(function)):
            raise RuntimeError(f"canonical startup console output forbidden={name}")
        non_ascii = sorted({node.value for node in ast.walk(function) if isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.isascii()})
        if non_ascii:
            raise RuntimeError(f"canonical startup encoding-sensitive literal={name}:{non_ascii}")
    top_level_prints=[]
    candidates=[ROOT/name for name in ("main.py","startup.py","database.py","settings.py")]
    candidates.extend((ROOT/"core").rglob("*.py"))
    for path in candidates:
        module=ast.parse(path.read_text(encoding="utf-8-sig"),filename=path.relative_to(ROOT).as_posix())
        for node in module.body:
            if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=="print":
                top_level_prints.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    if top_level_prints:
        raise RuntimeError(f"import-time console output forbidden={top_level_prints}")
    return {"status":"PASS","encoding":"strict-ascii-compatible","top_level_prints":0}


def static_verify():
    contract = _json("pc6_neutral_platform_proof.json")
    dependency = verify_dependency_authority(ROOT, _json("pc6_dependency_authority.json"))
    leakage = scan_wnd_leakage(ROOT, _json("pc6_wnd_leakage_policy.json"))
    secrets = _secret_default_scan()
    console = _canonical_startup_console_scan()
    profile = load_profile(PROFILE)
    if contract["scope"] != [f"PC6.{number}" for number in range(1, 13)]:
        raise RuntimeError("PC6 scope incomplete")
    if (contract["source_checkpoint"], contract["previous_head"], contract["accepted_head"], contract["migration"]) != (SOURCE, PREVIOUS, HEAD, "NONE"):
        raise RuntimeError("PC6 checkpoint, lineage, or no-migration boundary changed")
    if list((ROOT / "alembic_neutral/versions").glob("pc6_*.py")):
        raise RuntimeError("ceremonial PC6 migration forbidden")
    startup_source = (ROOT / "startup.py").read_text(encoding="utf-8")
    factory_source = startup_source[startup_source.index("def create_app"):]
    if "init_database()" in factory_source or "seed_rbac()" in factory_source:
        raise RuntimeError("canonical application factory performs implicit schema or legacy-RBAC writes")
    inventory = _json("pc6_public_contract_inventory.json")
    if {item["authority"] for item in inventory["interfaces"]} != {"PC1", "PC2", "PC3", "PC4", "PC5"}:
        raise RuntimeError("PC6 public-contract inventory incomplete")
    if "sql_repository" in json.dumps(inventory):
        raise RuntimeError("PC6 public-contract proof exposes private repository")
    for number in range(1, 6):
        verify_historical_release(ROOT, number)
    latest = verify_latest_release(ROOT)
    if latest["latest"] != 6:
        raise RuntimeError("PC6 is not latest cumulative Platform Core descendant")
    pc0 = validate_pc0(ROOT)
    baseline = _json("pc0_frozen_finance_baseline.json")
    if baseline["canonical_head"] != "m64_reconciliation_controls_020" or baseline["lineage"][-1] != baseline["canonical_head"]:
        raise RuntimeError("frozen Finance lineage changed")
    return {
        "status": "PASS", "source_checkpoint": SOURCE, "previous_head": PREVIOUS, "accepted_head": HEAD,
        "migration": "NONE", "wbs_obligations": 12, "pc0": pc0["status"], "dependency_authority": dependency,
        "wnd_leakage": leakage["status"], "secret_defaults": secrets["status"], "startup_console_encoding": console["status"], "entrypoint_import_side_effects": "NONE", "profile_id": profile.profile_id, "profile_sha256": profile.sha256,
        "release_artifacts": latest["artifact_count"], "finance": "UNCHANGED",
    }


@contextmanager
def _database_session(engine):
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        with session.begin():
            yield session


def database_acceptance():
    from alembic import command as alembic_command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from database import engine as application_engine
    from core.platform.neutral_proof import bootstrap_profile
    from core.platform.operating_context import BusinessTimeResolver
    from core.platform.party import AddPartyContact, CreatePartyRelationship, PartyAuthorityError
    from core.platform.security_authority import ActorType, AuditEnvelope, AuditQuery, AuthorizationRequest, Decision, RoleAssignment, ScopeType, SecurityAuthorityError, StructuralScope
    from core.platform.semantics import AssignClassification
    from core.platform.semantics import SemanticAuthorityError
    from core.platform.structure import ProvisionTenant, StructuralAuthorityError

    url = make_url(application_engine.url)
    if url.host not in LOCAL or url.database != DEV:
        raise RuntimeError("refusing non-local PostgreSQL or configured development database mismatch")
    with application_engine.connect() as connection:
        if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
            raise RuntimeError("accepted PC5 development head mismatch")
    def selected(name, auto=False):
        return create_engine(url.set(database=name), pool_pre_ping=True, **({"isolation_level":"AUTOCOMMIT"} if auto else {}))
    admin = selected("postgres", True)
    names = (TEST, RESTORE, BACKUP_RESTORE)
    def drop(name):
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name":name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    def create(name):
        drop(name)
        with admin.connect() as connection: connection.exec_driver_sql(f'CREATE DATABASE "{name}" TEMPLATE template0')
    @contextmanager
    def target(name):
        prior = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = url.set(database=name).render_as_string(hide_password=False)
        try: yield
        finally:
            if prior is None: os.environ.pop("DATABASE_URL", None)
            else: os.environ["DATABASE_URL"] = prior
    config = Config(str(ROOT / "alembic.ini"))
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (HEAD,):
        raise RuntimeError("canonical Alembic lineage does not have exactly one PC5 head")
    profile = load_profile(PROFILE); source_before = _source_snapshot()
    engines = []; success = False; started = clock.perf_counter(); backup_path = None; timings = {}
    try:
        for name in (TEST, RESTORE):
            create(name)
            with target(name): alembic_command.upgrade(config, HEAD)
        test_engine = selected(TEST); restore_engine = selected(RESTORE); engines.extend((test_engine, restore_engine))
        for engine in (test_engine, restore_engine):
            with engine.connect() as connection:
                if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
                    raise RuntimeError("fresh canonical replay head mismatch")
        with test_engine.connect() as connection:
            entrypoint_tables_before = tuple(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars())
            entrypoint_roles_before = connection.execute(text("SELECT count(*) FROM roles")).scalar_one()
        entrypoint_env = os.environ.copy(); entrypoint_env.update(DATABASE_URL=url.set(database=TEST).render_as_string(hide_password=False), JWT_SECRET="pc6-disposable-entrypoint-proof", GATEWAY_API_KEY="pc6-disposable-reference")
        entrypoint = subprocess.run(
            [sys.executable, "-c", "import io,sys; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='ascii',errors='strict',write_through=True); from main import app; assert app.title == 'XBOS Kernel'; print('PC6_CANONICAL_ENTRYPOINT=PASS')"],
            cwd=ROOT, env=entrypoint_env, check=False, capture_output=True, text=True,
        )
        if entrypoint.returncode:
            raise RuntimeError(
                "canonical main:app import failed against fresh replay "
                f"returncode={entrypoint.returncode}\nSTDOUT:\n{entrypoint.stdout}\nSTDERR:\n{entrypoint.stderr}"
            )
        if "PC6_CANONICAL_ENTRYPOINT=PASS" not in entrypoint.stdout:
            raise RuntimeError(f"canonical entrypoint proof marker absent\nSTDOUT:\n{entrypoint.stdout}\nSTDERR:\n{entrypoint.stderr}")
        with test_engine.connect() as connection:
            entrypoint_tables_after = tuple(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars())
            entrypoint_roles_after = connection.execute(text("SELECT count(*) FROM roles")).scalar_one()
        if entrypoint_tables_after != entrypoint_tables_before or entrypoint_roles_after != entrypoint_roles_before:
            raise RuntimeError("canonical entrypoint import performed unauthorized schema or legacy-RBAC writes")
        with test_engine.connect() as connection:
            tables=set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
            finance_before={table:connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in FINANCIAL if table in tables}
        with _database_session(test_engine) as session:
            authorities = _facades(session); operation_started = clock.perf_counter(); result = bootstrap_profile(profile, authorities)
            timings["bootstrap"] = clock.perf_counter() - operation_started
            replay = bootstrap_profile(profile, authorities)
            if (replay["tenant_id"], replay["identity_id"], replay["profile_sha256"]) != (result["tenant_id"], result["identity_id"], result["profile_sha256"]):
                raise RuntimeError("second-tenant bootstrap replay was not idempotent")
            control = authorities["structure"].provision(ProvisionTenant("pc6:control", "CONTROL", "Control Tenant", "DE", "EUR", "de-DE", "Europe/Berlin", "CONTROL-LE", "Control Legal", "CONTROL-ROOT", "Control Root", "CONTROL-HQ", "Control HQ"))
            now = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
            security = authorities["security"]
            session_context = security.create_session(command_key="pc6:northstar-session", identity_id=result["identity_id"], tenant_id=result["tenant_id"], actor_type=ActorType.HUMAN, assurance_level=2, authenticated_at=now-timedelta(minutes=1), expires_at=now+timedelta(hours=1))
            request = AuthorizationRequest(session_context.public_id, profile.payload["security"]["permission_code"], result["tenant_id"], StructuralScope(ScopeType.ORGANIZATION_UNIT, result["organization_unit_id"]), "platform_context", "northstar", now)
            operation_started = clock.perf_counter()
            if security.authorize(request).decision is not Decision.ALLOW: raise RuntimeError("public authorization proof failed")
            timings["authorization"] = clock.perf_counter() - operation_started
            forged = AuthorizationRequest(session_context.public_id, request.permission_code, control.tenant.id, StructuralScope(ScopeType.TENANT, control.tenant.id), "platform_context", "control", now, approval_id=__import__("uuid").UUID("60000000-0000-0000-0000-000000000099"))
            if security.authorize(forged).decision is not Decision.DENY: raise RuntimeError("cross-tenant role or approval leakage")
            global_operator = security.create_session(command_key="pc6:ungranted-platform-session", identity_id=result["identity_id"], tenant_id=None, actor_type=ActorType.HUMAN, assurance_level=4, authenticated_at=now-timedelta(minutes=1), expires_at=now+timedelta(hours=1))
            if security.authorize(AuthorizationRequest(global_operator.public_id, request.permission_code, result["tenant_id"], request.target_scope, "platform_context", "northstar", now)).decision is not Decision.DENY:
                raise RuntimeError("ungranted platform operator acquired tenant administrator authority")
            structural = authorities["structure"].resolve(tenant_id=result["tenant_id"], organization_unit_id=result["organization_unit_id"], legal_entity_id=result["legal_entity_id"], location_id=result["location_id"])
            if structural.organization_unit.tenant_id != structural.legal_entity.tenant_id or structural.location.legal_entity_id != structural.legal_entity.id:
                raise RuntimeError("distinct structural authorities lost tenant or legal relationship")
            administrator_party = authorities["party"].resolve_reference(tenant_id=result["tenant_id"], scheme="external_key", value=profile.payload["parties"]["administrator_external_key"])
            organization_party = authorities["party"].resolve_reference(tenant_id=result["tenant_id"], scheme="external_key", value=profile.payload["parties"]["legal_organization_external_key"])
            failures = (
                (authorities["structure"].resolve, {"tenant_id":control.tenant.id,"organization_unit_id":result["organization_unit_id"]}),
                (authorities["structure"].resolve, {"tenant_id":control.tenant.id,"legal_entity_id":result["legal_entity_id"]}),
                (authorities["structure"].resolve, {"tenant_id":control.tenant.id,"location_id":result["location_id"]}),
                (authorities["party"].resolve_reference, {"tenant_id":control.tenant.id,"scheme":"external_key","value":profile.payload["parties"]["administrator_external_key"]}),
                (authorities["semantics"].resolve, {"qualified_code":f'{profile.payload["semantics"]["namespace_code"]}:{profile.payload["semantics"]["concept_code"]}',"effective_on":now.date(),"tenant_id":control.tenant.id}),
            )
            for resolver, arguments in failures:
                try: resolver(**arguments)
                except (StructuralAuthorityError, PartyAuthorityError, SemanticAuthorityError): pass
                else: raise RuntimeError("cross-tenant public authority lookup passed")
            try: authorities["party"].add_contact(AddPartyContact("pc6:cross-contact", control.tenant.id, administrator_party.id, "email", "invalid@cross.invalid", now.date()))
            except PartyAuthorityError: pass
            else: raise RuntimeError("cross-tenant Party contact passed")
            try: authorities["party"].create_relationship(CreatePartyRelationship("pc6:cross-relationship", control.tenant.id, organization_party.id, administrator_party.id, "forged", True, now.date()))
            except PartyAuthorityError: pass
            else: raise RuntimeError("cross-tenant Party relationship passed")
            try: authorities["semantics"].assign(AssignClassification("pc6:cross-classification", control.tenant.id, "tenant", "control", f'{profile.payload["semantics"]["namespace_code"]}:{profile.payload["semantics"]["concept_code"]}', now.date()))
            except SemanticAuthorityError: pass
            else: raise RuntimeError("cross-tenant semantic classification passed")
            try: security.assign_role(command_key="pc6:forged-role", assignment=RoleAssignment(result["identity_id"], control.tenant.id, profile.payload["security"]["role_code"], StructuralScope(ScopeType.TENANT, result["tenant_id"]), now))
            except SecurityAuthorityError: pass
            else: raise RuntimeError("forged cross-tenant role scope passed")
            other_value = authorities["operating_context"].resolve(tenant_id=control.tenant.id, key="ui.language", as_of=now)
            if other_value is not None: raise RuntimeError("cross-tenant configuration leaked")
            control_export = json.dumps(authorities["operating_context"].export(control.tenant.id), sort_keys=True)
            if profile.payload["calendar"]["code"] in control_export or profile.payload["calendar"]["shifts"][0]["code"] in control_export:
                raise RuntimeError("cross-tenant calendar or shift leaked")
            resolved = authorities["operating_context"].resolve(tenant_id=result["tenant_id"], key="ui.language", as_of=now)
            if resolved.value != "en-ca": raise RuntimeError("typed configuration proof failed")
            business_time = BusinessTimeResolver.resolve(result["calendar"], now)
            if business_time.calendar_code != "northstar-operations": raise RuntimeError("business-time proof failed")
            evidence = AuditEnvelope(__import__("uuid").UUID("60000000-0000-0000-0000-000000000001"), result["tenant_id"], result["identity_id"], ActorType.HUMAN, "pc6.neutral.proof", "tenant_profile", profile.profile_id, "allowed", now, "pc6", "pc6-neutral-proof", session_context.public_id, scope=StructuralScope(ScopeType.ORGANIZATION_UNIT, result["organization_unit_id"]), metadata={"profile_sha256":profile.sha256})
            security.append_audit(evidence)
            if len(security.query_audit(AuditQuery(session_context.public_id, result["tenant_id"], now, now+timedelta(hours=1), scope=StructuralScope(ScopeType.ORGANIZATION_UNIT, result["organization_unit_id"])))) != 1: raise RuntimeError("authorized audit query failed")
            state = {
                "structure": json.loads(authorities["structure"].export(result["tenant_id"])),
                "party": json.loads(authorities["party"].export(result["tenant_id"])),
                "semantics": json.loads(authorities["semantics"].export(result["tenant_id"])),
                "operating_context": authorities["operating_context"].export(result["tenant_id"]),
                "identity": security.export_identity(result["identity_id"]),
            }
            operation_started = clock.perf_counter(); exported = deterministic_export(profile, state); timings["export"] = clock.perf_counter() - operation_started
            if exported != deterministic_export(profile, state): raise RuntimeError("portable export nondeterministic")
            try: security.query_audit(AuditQuery(session_context.public_id, control.tenant.id, now, now+timedelta(hours=1), scope=StructuralScope(ScopeType.TENANT, control.tenant.id)))
            except Exception: pass
            else: raise RuntimeError("cross-tenant audit query passed")
            security.revoke_membership(identity_id=result["identity_id"], tenant_id=result["tenant_id"], revoked_at=now)
            if security.authorize(request).decision is not Decision.DENY: raise RuntimeError("stale membership retained authority")
        with test_engine.connect() as connection:
            finance_after={table:connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in finance_before}
        if finance_after != finance_before: raise RuntimeError("PC6 proof changed frozen Finance effects")
        with _database_session(restore_engine) as session:
            restored_authorities = _facades(session); operation_started = clock.perf_counter()
            restored = restore_export(exported, profile, lambda selected_profile: bootstrap_profile(selected_profile, restored_authorities))
            timings["portable_restore"] = clock.perf_counter() - operation_started
            if restored["tenant_code"] != "NORTHSTAR": raise RuntimeError("portable restore changed tenant identity")
            restored_context = restored_authorities["structure"].resolve(tenant_id=restored["tenant_id"], organization_unit_id=restored["organization_unit_id"], legal_entity_id=restored["legal_entity_id"], location_id=restored["location_id"])
            if restored_context.tenant.code != "NORTHSTAR" or restored_authorities["party"].resolve_reference(tenant_id=restored["tenant_id"], scheme="external_key", value=profile.payload["parties"]["administrator_external_key"]) is None:
                raise RuntimeError("portable restore lost structure or Party reference")
            restored_authorities["semantics"].resolve(qualified_code=f'{profile.payload["semantics"]["namespace_code"]}:{profile.payload["semantics"]["concept_code"]}', effective_on=now.date(), tenant_id=restored["tenant_id"])
            if restored_authorities["operating_context"].resolve(tenant_id=restored["tenant_id"], key="ui.language", as_of=now).value != "en-ca":
                raise RuntimeError("portable restore lost typed configuration")
            if BusinessTimeResolver.resolve(restored["calendar"], now).calendar_code != profile.payload["calendar"]["code"]:
                raise RuntimeError("portable restore lost business time")
            restored_security = restored_authorities["security"]
            restored_session = restored_security.create_session(command_key="pc6:restored-session", identity_id=restored["identity_id"], tenant_id=restored["tenant_id"], actor_type=ActorType.HUMAN, assurance_level=2, authenticated_at=now-timedelta(minutes=1), expires_at=now+timedelta(hours=1))
            restored_request = AuthorizationRequest(restored_session.public_id, profile.payload["security"]["permission_code"], restored["tenant_id"], StructuralScope(ScopeType.ORGANIZATION_UNIT, restored["organization_unit_id"]), "platform_context", "restored", now)
            if restored_security.authorize(restored_request).decision is not Decision.ALLOW or restored_security.export_identity(restored["identity_id"])["credential_material_included"]:
                raise RuntimeError("portable restore lost authorization or exposed credential material")
            if restored_security.query_audit(AuditQuery(restored_session.public_id, restored["tenant_id"], now, now+timedelta(hours=1), scope=StructuralScope(ScopeType.ORGANIZATION_UNIT, restored["organization_unit_id"]))):
                raise RuntimeError("historical audit evidence was silently restored")
        pg_dump, pg_restore = shutil.which("pg_dump"), shutil.which("pg_restore")
        if not pg_dump or not pg_restore: raise RuntimeError("PostgreSQL backup/restore tools unavailable")
        descriptor, backup_path = tempfile.mkstemp(prefix="xbos_pc6_", suffix=".backup"); os.close(descriptor)
        backup_started = clock.perf_counter()
        test_cli_url = url.set(drivername="postgresql", database=TEST).render_as_string(hide_password=False)
        restore_cli_url = url.set(drivername="postgresql", database=BACKUP_RESTORE).render_as_string(hide_password=False)
        subprocess.run([pg_dump, "--format=custom", "--file", backup_path, test_cli_url], check=True, capture_output=True)
        create(BACKUP_RESTORE)
        subprocess.run([pg_restore, "--exit-on-error", "--no-owner", "--dbname", restore_cli_url, backup_path], check=True, capture_output=True)
        timings["backup_restore"] = clock.perf_counter() - backup_started
        backup_engine = selected(BACKUP_RESTORE); engines.append(backup_engine)
        with backup_engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD: raise RuntimeError("backup restore changed canonical head")
            if connection.execute(text("SELECT count(*) FROM tenants WHERE code='NORTHSTAR'")).scalar_one() != 1: raise RuntimeError("backup restore lost second tenant")
        with _database_session(backup_engine) as session:
            backup_authorities = _facades(session)
            backup_context = backup_authorities["structure"].resolve(tenant_id=result["tenant_id"], organization_unit_id=result["organization_unit_id"], legal_entity_id=result["legal_entity_id"], location_id=result["location_id"])
            if backup_context.tenant.code != "NORTHSTAR" or backup_authorities["operating_context"].resolve(tenant_id=result["tenant_id"], key="ui.language", as_of=now).value != "en-ca":
                raise RuntimeError("backup restore lost structure or configuration")
            if backup_authorities["security"].authorize(request).decision is not Decision.DENY:
                raise RuntimeError("backup restore lost revoked-membership authorization state")
            try: backup_authorities["structure"].resolve(tenant_id=control.tenant.id, organization_unit_id=result["organization_unit_id"])
            except StructuralAuthorityError: pass
            else: raise RuntimeError("backup restore lost tenant isolation")
        if _source_snapshot() != source_before: raise RuntimeError("bootstrap modified neutral source")
        elapsed = clock.perf_counter() - started
        operation_bounds = {"bootstrap":30,"authorization":5,"export":5,"portable_restore":30,"backup_restore":60}
        exceeded = {key:value for key,value in timings.items() if value > operation_bounds[key]}
        if elapsed > 120 or exceeded: raise RuntimeError(f"PC6 proof performance bound exceeded total={elapsed:.3f}, operations={exceeded}")
        success = True
        return {"second_tenant_bootstrap":"PASS","no_source_change":"PASS","isolation":"PASS","portability_restore":"PASS","fresh_install":"PASS","upgrade":"PASS","public_contract_proof":"PASS","backup_restore":"PASS","financial_effects":"UNCHANGED","elapsed_seconds":round(elapsed,3),"operation_seconds":{key:round(value,3) for key,value in timings.items()},"cleanup":"PASS"}
    finally:
        for engine in engines: engine.dispose()
        if backup_path and Path(backup_path).exists(): Path(backup_path).unlink()
        if success:
            for name in names: drop(name)
        admin.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance: result["database"] = database_acceptance()
    except Exception as exc:
        print(f"PC6_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("PC6_VERIFY=PASS");return 0


if __name__=="__main__":raise SystemExit(main())
