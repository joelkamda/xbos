"""SWES PA R9: disposable real-Postgres PC5 first-owner transaction proof.

SYNTHETIC owner assertion is for local NEGATIVE/POSITIVE TEST ONLY.
NEVER treats this assertion as real CEO sign-in or hosted PC5 authority.
Target isolated new loopback PG17; no existing/hosted DB operations.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

CLUSTER=Path(r"C:\Users\jdkam\XafPayOps\PCR_WORKTREES\SWES_R9_PC5_PG17_DISPOSABLE_20261031")
BIN=Path(r"C:\Program Files\PostgreSQL\17\bin")
PORT=55475
ROLE="swes_pc5_r9_disposable"
DB="wnd_xafpay_demo_austin_db"
BASE_URL=f"postgresql+psycopg2://{ROLE}@127.0.0.1:{PORT}/{DB}"

def call(name,*args):
    r=subprocess.run([str(BIN / name), *[str(x) for x in args]],
          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
          check=False,timeout=100)
    if r.returncode:
        raise RuntimeError(f"FAIL_DISPOSABLE_PROCESS_{name}_{r.returncode}")

def run():
    if CLUSTER.exists():raise RuntimeError("HOLD_DISPOSABLE_CLUSTER_ALREADY_EXISTS")
    if os.environ.get("SWES_OIDC_ENABLED")=="true":
        raise RuntimeError("HOLD_HOSTED_OIDC_ENABLED_IN_LOCAL_PROCESS")
    started=False
    previous=os.environ.get("DATABASE_URL")
    engine=None
    try:
        CLUSTER.mkdir(parents=True)
        call("initdb.exe","-D",CLUSTER/"data","-U",ROLE,"--auth=trust",
              "--encoding=UTF8","--no-instructions")
        call("pg_ctl.exe","-D",CLUSTER/"data","-l",CLUSTER/"server.log",
             "-o",f"-h 127.0.0.1 -p {PORT}","-w","start")
        started=True
        call("createdb.exe","-h","127.0.0.1","-p",PORT,"-U",ROLE,DB)
        os.environ["DATABASE_URL"]=BASE_URL
        from alembic.config import Config

        from alembic import command
        cfg=Config(str(ROOT/"alembic.ini"))
        command.upgrade(cfg,"pc4_operating_context_024")
        engine=create_engine(BASE_URL)
        from core.platform.structure import SQLStructuralRepository, StructuralAuthority
        from core.platform.structure.contracts import (
            LocationKind,
            ProvisionTenant,
            TenantLifecycle,
        )
        with sessionmaker(bind=engine).begin() as s:
            for table,start in [("tenants",910000),("locations",4)]:
                sequence=s.execute(text("SELECT pg_get_serial_sequence(:table,'id')"),
                                  {"table":"public."+table}).scalar_one()
                assert sequence is not None, f"HOLD_NO_LOCAL_SEQUENCE_{table}"
                s.execute(text("SELECT setval(CAST(:seq AS regclass),:start,true)"),
                          {"seq":sequence,"start":start})
            structure=StructuralAuthority(SQLStructuralRepository(s))
            result=structure.provision(ProvisionTenant(
                "swes-r9-local-pc5-fixture", "SWES_WND_AUSTIN_TEST",
                "SWES WND Austin Fixture Only", "CM", "XAF", "fr-CM",
                "Africa/Douala","TEST_LE","TEST Legal Entity","ROOT_TEST",
                "Test Root","swes-wnd-austin-virtual",
                "Virtual Studio",LocationKind.VIRTUAL,
            ))
            assert result.tenant.id==910001 and result.location.id==5, "HOLD_LOCAL_TARGET_NOT_EXACT"
            if result.tenant.lifecycle is TenantLifecycle.ACTIVE:
                updated=result.tenant
            else:
                updated=structure.transition_tenant(result.tenant.id,
                    result.tenant.row_version,TenantLifecycle.ACTIVE)
            assert updated.lifecycle is TenantLifecycle.ACTIVE
        engine.dispose()
        command.upgrade(cfg,"pc5_identity_policy_audit_025")
        engine=create_engine(BASE_URL,pool_pre_ping=True)
        from core.platform.security_authority import (
            AuthorizationRequest,
            Decision,
            ScopeType,
            SecurityAuthority,
            SQLSecurityRepository,
            StructuralScope,
        )
        from platform_admin.swes_google_oidc_r7 import (
            OIDCConfig,
            OIDCHold,
            VerifiedIdentity,
            subject_digest,
        )
        from platform_admin.swes_google_pc5_enrollment_r7 import enroll_verified_ceo
        callback="https://wnd-xafpay-demo-austin-backend.onrender.com/internal/swes/pa/oidc/callback"
        issuer_hash=subject_digest("LOCAL-TEST-NOT-REAL-CEO-SUB")
        config=OIDCConfig(
            "123456789-swestest.apps.googleusercontent.com",
            "LOCAL_TEST_ONLY_NEVER_HOSTED",""+callback,issuer_hash
        )
        at=datetime.now(timezone.utc).replace(microsecond=0)
        identity=VerifiedIdentity("https://accounts.google.com",issuer_hash,
             config.client_id,at,"f"*64,910001,1)
        factory=sessionmaker(bind=engine,expire_on_commit=False)
        with factory.begin() as s:
            enrollment=enroll_verified_ceo(db_session=s,identity=identity,
                          config=config,ceo_approval_registered=True,at=at)
            assert enrollment.tenant_id==910001
            assert enrollment.permission_code=="pa.merchant.admin"
            assert enrollment.authorization_decision=="require_step_up"
            assert enrollment.required_assurance==2
            assert not enrollment.operational_admission
            assert len(enrollment.identity_public_id)==36
            assert len(enrollment.session_public_id)==36
            print("DISPOSABLE_FIRST_OWNER_CANONICAL_PC5_TRANSACTION=PASS")
        with factory.begin() as s:
            a=SecurityAuthority(SQLSecurityRepository(s))
            from uuid import UUID
            decision=a.authorize(AuthorizationRequest(UUID(enrollment.session_public_id),
                 "pa.merchant.admin",910001,StructuralScope(ScopeType.TENANT,910001),
                 "merchant","wnd-austin-test",at+timedelta(seconds=1)))
            assert decision.decision is Decision.REQUIRE_STEP_UP
            for table in ("identities","identity_memberships","authorization_roles",
                          "scoped_role_assignments","authentication_sessions"):
                count=s.execute(text("SELECT count(*) FROM public."+table)).scalar_one()
                assert count==1,(table,count)
            count=s.execute(text(
                "SELECT count(*) FROM public.audit_evidence WHERE tenant_id=910001"
            )).scalar_one()
            assert count==1
            try:
                enroll_verified_ceo(db_session=s,identity=identity,config=config,
                                   ceo_approval_registered=True,at=at)
            except OIDCHold as exc:
                assert exc.code=="HOLD_FIRST_OPERATOR_ALREADY_ESTABLISHED"
            else:raise AssertionError("HOLD_DUPLICATE_BOOTSTRAP_NOT_DENIED")
            a.revoke_session(UUID(enrollment.session_public_id),at+timedelta(seconds=2))
            denied=a.authorize(AuthorizationRequest(UUID(enrollment.session_public_id),
                 "pa.merchant.admin",910001,StructuralScope(ScopeType.TENANT,910001),
                 "merchant","wnd-austin-test",at+timedelta(seconds=3)))
            assert denied.decision is Decision.DENY
            print("DISPOSABLE_SESSION_STEPUP_REQUIRED_DUPLICATE_DENIED_REVOCATION=PASS")
        with engine.connect() as c:
            revision=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert revision=="pc5_identity_policy_audit_025"
            print("DISPOSABLE_ALCHEMY_REAL_PG17_PC5_REVISION=PASS")
    finally:
        if engine is not None:engine.dispose()
        if previous is None:os.environ.pop("DATABASE_URL",None)
        else:os.environ["DATABASE_URL"]=previous
        if started:
            call("pg_ctl.exe","-D",CLUSTER/"data","-m","fast","-w","stop")
        if CLUSTER.exists():
            shutil.rmtree(CLUSTER)
        print("DISPOSABLE_PC5_PG17_SHUTDOWN_CLEANUP=PASS")

if __name__=="__main__":run()
