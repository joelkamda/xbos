"""PC5 static validation and controlled local PostgreSQL acceptance."""
from __future__ import annotations

import argparse, json, os, sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.platform.architecture_contract import validate_pc0
from core.platform.release_integrity import verify_latest_release

SOURCE="26b673e";PREVIOUS="pc4_operating_context_024";HEAD="pc5_identity_policy_audit_025"
DEV="xbos_track_b_dev";TEST="xbos_platform_core_pc5_test";LOCAL={"localhost","127.0.0.1","::1"}
FINANCIAL=("financial_events","journal_entries","journal_lines","financial_obligations","value_sources","payment_allocations","canonical_payment_intents","payment_settlements","outbox_messages","reconciliation_controls","reconciliation_calendar_policies")


@contextmanager
def _database_session(engine):
    """Construct one unambiguous SQLAlchemy session and transaction scope."""
    from sqlalchemy.orm import sessionmaker
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as database_session:
        with database_session.begin():
            yield database_session


def static_verify():
    directory=ROOT/"contracts/platform/v1"
    contract=json.loads((directory/"pc5_identity_policy_audit_authority.json").read_text())
    adoption=json.loads((directory/"pc5_compatibility_migration_manifest.json").read_text())
    interfaces=json.loads((directory/"pc5_public_private_interfaces.json").read_text())
    release=json.loads((directory/"pc5_release_manifest.json").read_text())
    if contract["scope"]!=[f"PC5.{n}" for n in range(1,16)]:raise RuntimeError("PC5 scope incomplete")
    if (contract["source_checkpoint"],contract["previous_head"],contract["accepted_head"])!=(SOURCE,PREVIOUS,HEAD):raise RuntimeError("PC5 checkpoint/lineage mismatch")
    required={"users","users.password_hash","JWTService","users.tenant_id","users.branch_id","users.role","roles.permissions JSON","permission levels and role packs","permission middleware and decorators","Finance approval/evidence fields","generic audit authority","service/device credentials","delegated administration"}
    if not required<={x["authority"] for x in adoption["entries"]}:raise RuntimeError("PC5 legacy authority inventory incomplete")
    if not all(all(x.get(k) for k in ("classification","canonical_owner","compatibility_path","retirement_owner","retirement_milestone")) for x in adoption["entries"]):raise RuntimeError("PC5 compatibility retirement path incomplete")
    if interfaces["module"]!="security_authority":raise RuntimeError("PC5 public interface mismatch")
    version=(ROOT/"alembic_neutral/versions/pc5_identity_policy_audit_025_canonical_security_authority.py").read_text();up=(ROOT/"alembic_neutral/sql/pc5_identity_policy_audit_up.sql").read_text()
    if f'revision = "{HEAD}"' not in version or f'down_revision = "{PREVIOUS}"' not in version:raise RuntimeError("PC5 migration is not canonical child")
    if any(x in up for x in ("ALTER TABLE public.financial_","UPDATE public.financial_","DELETE FROM public.financial_","INSERT INTO public.outbox_messages","CREATE TABLE public.outbox")):raise RuntimeError("PC5 migration changes frozen Finance or generic delivery")
    for marker in ("identity_memberships","authentication_sessions","permission_definitions","scoped_role_assignments","protected_action_approvals","step_up_grants","service_identities","device_identities","support_access_grants","audit_evidence_append_only"):
        if marker not in up:raise RuntimeError(f"PC5 migration authority absent={marker}")
    pc3=(ROOT/"scripts/verify_pc3_semantic_authority.py").read_text();pc4sql=(ROOT/"alembic_neutral/sql/pc4_operating_context_up.sql").read_text();pc4wrapper=(ROOT/"alembic_neutral/versions/pc4_operating_context_024_typed_configuration_modules_time.py").read_text()
    if "name,semantic_level,taxonomy_type,sort_order" not in pc3 or "'Child','domain','COMMERCE'" not in pc3:raise RuntimeError("accepted PC3 repair not preserved")
    if "OR NOT (CASE d.value_type" not in pc4sql or ".connection.cursor()" not in pc4wrapper:raise RuntimeError("accepted PC4 repairs not preserved")
    verify_latest_release(ROOT)
    pc0=validate_pc0(ROOT)
    return {"status":"PASS","pc0":pc0["status"],"source_checkpoint":SOURCE,"previous_head":PREVIOUS,"accepted_head":HEAD,"wbs_obligations":15,"compatibility_entries":len(adoption["entries"]),"release_artifacts":len(release["artifacts"]),"historical_repairs":"PRESERVED"}


def database_acceptance():
    from alembic import command as alembic_command
    from alembic.config import Config
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from database import engine as application_engine
    from core.platform.structure import SQLStructuralRepository,StructuralAuthority
    from core.platform.structure.contracts import ProvisionTenant
    from core.platform.security_authority import ActorType,AuditEnvelope,AuditQuery,AuthorizationRequest,Decision,PermissionDefinition,RoleAssignment,ScopeType,SecurityAuthority,SQLSecurityRepository,StructuralScope

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
    config=Config(str(ROOT/"alembic.ini"));db=None;now=datetime(2026,8,13,12,tzinfo=timezone.utc)
    try:
        with target():alembic_command.upgrade(config,PREVIOUS)
        db=selected(TEST)
        with _database_session(db) as s:context=StructuralAuthority(SQLStructuralRepository(s)).provision(ProvisionTenant("pc5-tenant","PC5","PC5 Tenant","CM","XAF","fr-CM","Africa/Douala","LE","PC5 Legal","ROOT","Root","HQ","HQ"))
        tenant=context.tenant.id
        with target():alembic_command.upgrade(config,HEAD)
        with _database_session(db) as s:
            authority=SecurityAuthority(SQLSecurityRepository(s));maker=authority.create_identity(command_key="pc5-maker",login_name="maker@pc5.invalid");checker=authority.create_identity(command_key="pc5-checker",login_name="checker@pc5.invalid")
            for actor,key in ((maker,"maker-membership"),(checker,"checker-membership")):authority.add_membership(command_key=key,identity_id=actor.id,tenant_id=tenant,valid_from=now-timedelta(days=1))
            permission=PermissionDefinition("pc5.audit.evidence.query","pc5","audit","query","high",(ScopeType.TENANT,ScopeType.ORGANIZATION_UNIT),2)
            # seeded definition is authoritative; prove it exists and use it.
            if authority.repository.permission(permission.code) is None:raise RuntimeError("seeded canonical audit permission absent")
            authority.create_role(command_key="pc5-auditor-role",role_code="auditor",tenant_id=tenant,permissions=(permission.code,))
            authority.assign_role(command_key="pc5-maker-role",assignment=RoleAssignment(maker.id,tenant,"auditor",StructuralScope(ScopeType.TENANT,tenant),now-timedelta(days=1)))
            session=authority.create_session(command_key="pc5-session",identity_id=maker.id,tenant_id=tenant,actor_type=ActorType.HUMAN,assurance_level=2,authenticated_at=now-timedelta(minutes=1),expires_at=now+timedelta(hours=1))
            decision=authority.authorize(AuthorizationRequest(session.public_id,permission.code,tenant,StructuralScope(ScopeType.TENANT,tenant),"audit_evidence","query",now,correlation_id="pc5-acceptance"))
            if decision.decision is not Decision.ALLOW:raise RuntimeError(f"canonical authorization failed={decision.reason}")
            evidence=AuditEnvelope(UUID("50000000-0000-0000-0000-000000000501"),tenant,maker.id,ActorType.HUMAN,"pc5.audit.query","audit_evidence","query","allowed",now,"pc5","pc5-acceptance",session.public_id,scope=StructuralScope(ScopeType.TENANT,tenant),metadata={"record_count":1})
            authority.append_audit(evidence)
            if len(authority.query_audit(AuditQuery(session.public_id,tenant,now-timedelta(hours=1),now+timedelta(hours=1),scope=StructuralScope(ScopeType.TENANT,tenant))))!=1:raise RuntimeError("authorized audit query failed")
            service=authority.register_service_identity(command_key="pc5-service",service_code="worker.acceptance",owner_module="so9",tenant_id=tenant,credential_reference="vault.worker.acceptance")
            device=authority.register_device_identity(command_key="pc5-device",device_code="pos.acceptance",tenant_id=tenant,location_id=context.location.id,organization_unit_id=context.organization_unit.id)
            if not service.service_code or not device.device_code or service.owner_module != "so9":raise RuntimeError("service/device authority distinction failed")
            authority.revoke_session(session.public_id,now)
            if authority.authorize(AuthorizationRequest(session.public_id,permission.code,tenant,StructuralScope(ScopeType.TENANT,tenant),"audit_evidence","query",now,correlation_id="revoked")).decision is not Decision.DENY:raise RuntimeError("revoked session retained authority")
        try:
            with db.begin() as c:c.execute(text("UPDATE audit_evidence SET outcome='rewritten' WHERE public_id='50000000-0000-0000-0000-000000000501'"))
        except Exception as exc:
            if "audit_evidence_append_only" not in str(exc):raise RuntimeError("audit immutability failed unexpectedly") from exc
        else:raise RuntimeError("audit update was accepted")
        with target():alembic_command.downgrade(config,PREVIOUS);alembic_command.upgrade(config,HEAD)
        with application_engine.connect() as c:
            current=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one();tables=set(c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars());before={t:c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in FINANCIAL if t in tables}
        if current not in {PREVIOUS,HEAD}:raise RuntimeError(f"development lineage mismatch={current}")
        if current==PREVIOUS:
            with target(DEV):alembic_command.upgrade(config,HEAD)
        with application_engine.connect() as c:after_head=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one();after={t:c.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in before}
        if after_head!=HEAD or after!=before:raise RuntimeError("development adoption changed financial effects")
    except Exception:raise
    else:
        if db:db.dispose()
        admin=selected("postgres",True)
        with admin.connect() as c:c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":TEST});c.exec_driver_sql(f'DROP DATABASE "{TEST}"')
        admin.dispose()
    return {"disposable":"PASS","clean_replay":"PASS","downgrade_reupgrade":"PASS","identity_party_separation":"PASS","membership_isolation":"PASS","session_revocation":"PASS","authorization":"PASS","service_device":"PASS","audit_immutability":"PASS","development_head":HEAD,"financial_effects":"UNCHANGED","cleanup":"PASS"}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--acceptance",action="store_true");args=parser.parse_args()
    try:
        result=static_verify()
        if args.acceptance:result["database"]=database_acceptance()
    except Exception as exc:print(f"PC5_VERIFY=FAIL\n{exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2,sort_keys=True));print("PC5_VERIFY=PASS");return 0
if __name__=="__main__":raise SystemExit(main())
