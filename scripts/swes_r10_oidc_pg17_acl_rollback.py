"""Isolated local PostgreSQL 17 TEST-only OIDC challenge table acceptance.

Requires locally installed PostgreSQL 17 binaries. No existing DB, dev server,
hosted service, credential file, or environment URL is read or modified.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from platform_admin.swes_google_oidc_r7 import Challenge, digest
from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore

DIR=Path(r"C:\Users\jdkam\XafPayOps\PCR_WORKTREES\SWES_R10_OIDC_PG17_DISPOSABLE_20261031")
BIN=Path(r"C:\Program Files\PostgreSQL\17\bin")
PORT=55476
ROLE="swes_oidc_disposable"
DB="wnd_xafpay_demo_austin_db"

def execute(name,*args):
    result=subprocess.run([str(BIN/name),*map(str,args)],check=False,
                          text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          timeout=90)
    if result.returncode:
        raise RuntimeError("DISPOSABLE_STEP_FAILED:"+name+":"+str(result.returncode))
    return ""

def main():
    if DIR.exists():raise RuntimeError("HOLD_DISPOSABLE_PATH_ALREADY_EXISTS")
    if not (BIN/"initdb.exe").is_file():raise RuntimeError("HOLD_PG17_UNAVAILABLE")
    if os.environ.get("SWES_OIDC_ENABLED")=="true":
        raise RuntimeError("HOLD_OIDC_LIVE_ENV_ACTIVE")
    started=False
    try:
        DIR.mkdir(parents=True)
        execute("initdb.exe","-D",DIR/"data","-U",ROLE,"--auth=trust",
                "--encoding=UTF8","--no-instructions")
        execute("pg_ctl.exe","-D",DIR/"data","-l",DIR/"server.log",
                "-o",f"-h 127.0.0.1 -p {PORT}","-w","start")
        started=True
        execute("createdb.exe","-h","127.0.0.1","-p",PORT,"-U",ROLE,DB)
        execute("psql.exe","-w","-h","127.0.0.1","-p",PORT,"-U",ROLE,"-d",DB,
                "-v","ON_ERROR_STOP=1","-f",
                ROOT/"platform_admin"/"swes_google_oidc_challenges_r7.sql")
        engine=create_engine(f"postgresql+psycopg2://{ROLE}@127.0.0.1:{PORT}/{DB}")
        try:
            store=SQLChallengeStore(engine,fernet_key=Fernet.generate_key().decode("ascii"))
            now=datetime.now(timezone.utc)
            challenge=Challenge(digest("local-state"),digest("local-nonce"),
                                "local-verifier-not-a-secret",now,now+timedelta(minutes=5))
            store.issue(challenge)
            with engine.connect() as c:
                before=c.execute(text("SELECT count(*) FROM swes_pa_oidc_challenges")).scalar_one()
            first=store.consume(challenge.state_digest)
            repeated=store.consume(challenge.state_digest)
            with engine.connect() as c:
                after=c.execute(text("SELECT count(*) FROM swes_pa_oidc_challenges")).scalar_one()
            assert before==1 and first==challenge and repeated is None and after==0
            print("SWES_R10_PG17_OIDC_REPLAY_SEALED_CHALLENGE=PASS")

            # New disposable PostgreSQL role, NOT a human or hosted service actor.
            # Test only the minimal table privileges that the OIDC challenge store
            # requires. The runtime principal must never own the table.
            from sqlalchemy.exc import SQLAlchemyError
            runtime_role = "swes_oidc_r10_writer"
            with engine.begin() as c:
                c.exec_driver_sql("CREATE ROLE swes_oidc_r10_writer NOLOGIN")
                c.exec_driver_sql("GRANT USAGE ON SCHEMA public TO swes_oidc_r10_writer")
                c.exec_driver_sql(
                    "GRANT SELECT, INSERT, DELETE ON "
                    "public.swes_pa_oidc_challenges TO swes_oidc_r10_writer"
                )
                for privilege, permitted in (
                    ("SELECT", True), ("INSERT", True), ("DELETE", True),
                    ("UPDATE", False), ("TRUNCATE", False), ("REFERENCES", False),
                ):
                    actual = c.execute(text(
                        "SELECT has_table_privilege(:role,"
                        "'public.swes_pa_oidc_challenges',:p)"
                    ), {"role": runtime_role, "p": privilege}).scalar_one()
                    assert actual is permitted, (privilege, actual)
            with engine.begin() as c:
                c.exec_driver_sql("SET LOCAL ROLE swes_oidc_r10_writer")
                c.execute(text("""
                    INSERT INTO public.swes_pa_oidc_challenges
                      (state_digest,nonce_digest,verifier_ciphertext,tenant_id,created_at,expires_at)
                    VALUES (:s,:n,:v,910001,:created,:expires)
                """), {
                    "s": digest("restricted-test-ticket"),
                    "n": digest("restricted-test-nonce"),
                    "v": b"encrypted-only-test-fixture",
                    "created": now,
                    "expires": now + timedelta(minutes=5),
                })
            try:
                with engine.begin() as c:
                    c.exec_driver_sql("SET LOCAL ROLE swes_oidc_r10_writer")
                    c.exec_driver_sql(
                        "UPDATE public.swes_pa_oidc_challenges "
                        "SET verifier_ciphertext='\\x00'::bytea"
                    )
            except SQLAlchemyError as exc:
                assert getattr(exc.orig, "pgcode", None) == "42501", (
                    "HOLD_EXPECTED_PRIVILEGE_DENIAL", type(exc).__name__
                )
            else:
                raise AssertionError("HOLD_OIDC_WRITER_UNAUTHORIZED_UPDATE_ACCEPTED")
            print("SWES_R10_PG17_MINIMAL_WRITER_PERMISSIONS=PASS")

            down = (ROOT/"platform_admin"/"swes_google_oidc_challenges_r10_down.sql").read_text(
                encoding="utf-8"
            )
            try:
                with engine.begin() as c:
                    c.exec_driver_sql(down)
            except SQLAlchemyError as exc:
                assert "HOLD_OIDC_CHALLENGES_PENDING" in str(exc), type(exc).__name__
            else:
                raise AssertionError("HOLD_OIDC_DOWNGRADE_DROPPED_PENDING_TICKETS")
            with engine.begin() as c:
                assert c.execute(text(
                    "SELECT count(*) FROM public.swes_pa_oidc_challenges"
                )).scalar_one() == 1
                c.execute(text(
                    "DELETE FROM public.swes_pa_oidc_challenges "
                    "WHERE state_digest=:state"
                ), {"state": digest("restricted-test-ticket")})
                c.exec_driver_sql(down)
                assert c.execute(text(
                    "SELECT to_regclass('public.swes_pa_oidc_challenges')"
                )).scalar_one() is None
            with engine.begin() as c:
                c.exec_driver_sql((
                    ROOT/"platform_admin"/"swes_google_oidc_challenges_r7.sql"
                ).read_text(encoding="utf-8"))
            challenge2 = Challenge(
                digest("reinstalled-state"), digest("reinstalled-nonce"),
                "local-only-reinstalled-verifier", now,
                now + timedelta(minutes=5)
            )
            store.issue(challenge2)
            assert store.consume(challenge2.state_digest) == challenge2
            assert store.consume(challenge2.state_digest) is None
            print("SWES_R10_PG17_DOWNGRADE_GUARD_REINSTALL_REPLAY=PASS")
        finally:engine.dispose()
    finally:
        if started:
            execute("pg_ctl.exe","-D",DIR/"data","-m","fast","-w","stop")
        shutil.rmtree(DIR)
        print("SWES_R10_PG17_DISPOSABLE_CLEANUP=PASS")

if __name__=="__main__":main()
