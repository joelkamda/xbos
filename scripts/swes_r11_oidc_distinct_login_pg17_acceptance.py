"""Real separate-password LOGIN and owner vs OIDC restricted PG17 acceptance.

Only newly created disposable loopback PostgreSQL cluster, exact TEST database
NAME inside local cluster. Passwords never logged, copied or persisted afterward.
No live hosted Render role or schema changes.
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cryptography.fernet import Fernet
from psycopg2 import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from platform_admin.swes_google_oidc_r7 import Challenge, OIDCHold, digest
from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore
from platform_admin.swes_oidc_writer_r11 import create_restricted_oidc_engine

CLUSTER=Path(r"C:\Users\jdkam\XafPayOps\PCR_WORKTREES\SWES_R11_OIDC_LOGIN_PG17_DISPOSABLE_20261031")
BIN=Path(r"C:\Program Files\PostgreSQL\17\bin")
PORT=55477
OWNER="swes_r11_disposable_owner"
WRITER="swes_oidc_austin_writer_r11"
DB="wnd_xafpay_demo_austin_db"


def run_bin(program,*args,env=None):
    proc=subprocess.run(
        [str(BIN/program),*[str(a) for a in args]],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        env=env,check=False,timeout=100,
    )
    if proc.returncode:
        raise RuntimeError("HOLD_DISPOSABLE_PROCESS_"+program+"_"+str(proc.returncode))


def engine_url(user,password):
    return URL.create(
        "postgresql+psycopg2",username=user,password=password,
        host="127.0.0.1",port=PORT,database=DB
    )


def test():
    if CLUSTER.exists():raise RuntimeError("HOLD_DISPOSABLE_PATH_EXISTS")
    if os.getenv("SWES_OIDC_ENABLED")=="true":
        raise RuntimeError("HOLD_EXTERNAL_OIDC_ENABLED")
    owner_password=secrets.token_urlsafe(36)
    writer_password=secrets.token_urlsafe(36)
    started=False
    owner_engine=None
    writer_engine=None
    try:
        CLUSTER.mkdir(parents=True)
        pwfile=CLUSTER/"owner_pw.txt"
        pwfile.write_text(owner_password+"\n",encoding="utf-8")
        run_bin("initdb.exe","-D",CLUSTER/"data","-U",OWNER,
                "--auth-host=scram-sha-256","--auth-local=scram-sha-256",
                "--pwfile",pwfile,"--encoding=UTF8","--no-instructions")
        pwfile.unlink()
        run_bin("pg_ctl.exe","-D",CLUSTER/"data","-l",CLUSTER/"server.log",
                "-o",f"-h 127.0.0.1 -p {PORT}","-w","start")
        started=True
        osenv=os.environ.copy()
        osenv["PGPASSWORD"]=owner_password
        run_bin("createdb.exe","-h","127.0.0.1","-p",PORT,"-U",OWNER,DB,env=osenv)
        run_bin("psql.exe","-w","-h","127.0.0.1","-p",PORT,"-U",OWNER,"-d",DB,
                "-v","ON_ERROR_STOP=1","-f",
                ROOT/"platform_admin"/"swes_google_oidc_challenges_r7.sql",env=osenv)

        owner_engine=create_engine(engine_url(OWNER,owner_password),pool_pre_ping=True)
        with owner_engine.begin() as conn:
            # Prove no unexpected merchant privilege under the dedicated writer
            # against an existing table that is NOT the OIDC tickets relation.
            conn.exec_driver_sql("""
                CREATE TABLE public.pa_merchants(
                    id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL
                )
            """)
            raw=conn.connection.driver_connection
            with raw.cursor() as cursor:
                cursor.execute(sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(WRITER),sql.Literal(writer_password)))
            conn.exec_driver_sql(
                "GRANT USAGE ON SCHEMA public TO "+WRITER
            )
            conn.exec_driver_sql(
                "GRANT SELECT,INSERT,DELETE ON TABLE "
                "public.swes_pa_oidc_challenges TO "+WRITER
            )
        # No general WND owner fallback even if DATABASE_URL is present.
        prior_db=os.environ.get("DATABASE_URL")
        prior_oidc=os.environ.get("SWES_OIDC_WRITER_DATABASE_URL")
        os.environ["DATABASE_URL"]=engine_url(OWNER,owner_password).render_as_string(hide_password=False)
        os.environ.pop("SWES_OIDC_WRITER_DATABASE_URL",None)
        try:
            try:
                create_restricted_oidc_engine()
            except OIDCHold as exc:
                assert exc.code=="HOLD_OIDC_DEDICATED_WRITER_URL_ABSENT"
            else:
                raise AssertionError("HOLD_GENERIC_DATABASE_FALLBACK")
            try:
                create_restricted_oidc_engine(
                    url=engine_url(OWNER,owner_password).render_as_string(hide_password=False)
                )
            except OIDCHold as exc:
                assert exc.code=="HOLD_OIDC_WRITER_URL_UNTRUSTED"
            else:
                raise AssertionError("HOLD_OWNER_ROLE_ADMITTED")
            wrong_pw=engine_url(WRITER,secrets.token_urlsafe(36)).render_as_string(hide_password=False)
            try:
                create_restricted_oidc_engine(url=wrong_pw)
            except OIDCHold as exc:
                assert exc.code=="HOLD_OIDC_DEDICATED_WRITER_CONNECT_FAILED"
            else:
                raise AssertionError("HOLD_WRONG_PASSWORD_ADMITTED")
            writer_url=engine_url(WRITER,writer_password).render_as_string(hide_password=False)
            writer_engine=create_restricted_oidc_engine(url=writer_url)
            with writer_engine.connect() as conn:
                evidence=conn.execute(text("SELECT session_user,current_user")).one()
                assert evidence==(WRITER,WRITER), "HOLD_NOT_SEPARATE_DB_LOGIN"
            print("R11_AUTHENTICATED_DISTINCT_DB_LOGIN_AND_NO_FALLBACK=PASS")
            store=SQLChallengeStore(
                writer_engine,fernet_key=Fernet.generate_key().decode("ascii")
            )
            now=datetime.now(timezone.utc).replace(microsecond=0)
            challenge=Challenge(
                digest("isolated-r11-state"),digest("isolated-r11-nonce"),
                "opaque-test-pkce-verifier",now,now+timedelta(minutes=5)
            )
            store.issue(challenge)
            assert store.consume(challenge.state_digest)==challenge
            assert store.consume(challenge.state_digest) is None
            with writer_engine.connect() as c:
                assert c.execute(text(
                    "SELECT count(*) FROM public.swes_pa_oidc_challenges"
                )).scalar_one()==0
            print("R11_SEALED_TICKETS_ATOMIC_REDEMPTION_REPLAY_DENIED=PASS")
            for label, sql_text in (
                ("OTHER_TABLE", "SELECT count(*) FROM public.pa_merchants"),
                ("UPDATE","UPDATE public.swes_pa_oidc_challenges SET tenant_id=910001"),
                ("CREATE","CREATE TABLE public.bad_oidc_writer_ddl(id INT)"),
            ):
                try:
                    with writer_engine.begin() as c:
                        c.exec_driver_sql(sql_text)
                except SQLAlchemyError as exc:
                    assert getattr(exc.orig,"pgcode",None)=="42501", (label,type(exc).__name__)
                else:
                    raise AssertionError("HOLD_WRITER_OVERPRIVILEGED_"+label)
            print("R11_UNRELATED_MERCHANT_READ_UPDATE_AND_DDL_DENIED=PASS")
            # Tenant row CHECK restricts tickets even with valid LOGIN grants.
            try:
                with writer_engine.begin() as c:
                    c.execute(text("""
                        INSERT INTO public.swes_pa_oidc_challenges
                          (state_digest,nonce_digest,verifier_ciphertext,
                           tenant_id,created_at,expires_at)
                        VALUES (:s,:n,:v,910002,:created,:expires)
                    """), {
                        "s": digest("wrong-tenant-ticket"),
                        "n": digest("wrong-tenant-nonce"),
                        "v": b"local-encrypted-ticket-fixture",
                        "created": now,
                        "expires": now + timedelta(minutes=5),
                    })
            except SQLAlchemyError as exc:
                assert getattr(exc.orig, "pgcode", None) == "23514"
            else:
                raise AssertionError("HOLD_OTHER_TENANT_TICKET_ACCEPTED")
            print("R11_TICKET_CROSS_TENANT_DENIAL=PASS")
            # Changing role ACL after connect must fail the NEXT checkout,
            # not silently reuse an overprivileged pooled connection.
            with owner_engine.begin() as conn:
                conn.exec_driver_sql(
                    "GRANT SELECT ON TABLE public.pa_merchants TO "+WRITER
                )
            try:
                with writer_engine.connect():
                    pass
            except OIDCHold as exc:
                assert exc.code=="HOLD_OIDC_WRITER_UNRELATED_TABLE_ACCESS"
            else:
                raise AssertionError("HOLD_WRITER_BROAD_TABLE_GRANT_ACCEPTED")
            with owner_engine.begin() as conn:
                conn.exec_driver_sql(
                    "REVOKE SELECT ON TABLE public.pa_merchants FROM "+WRITER
                )
                conn.exec_driver_sql(
                    "GRANT UPDATE ON TABLE public.swes_pa_oidc_challenges TO "+WRITER
                )
            try:
                with writer_engine.connect():
                    pass
            except OIDCHold as exc:
                assert exc.code=="HOLD_OIDC_WRITER_TABLE_ACL_MISMATCH"
            else:
                raise AssertionError("HOLD_WRITER_UPDATE_GRANT_ACCEPTED")
            with owner_engine.begin() as conn:
                conn.exec_driver_sql(
                    "REVOKE UPDATE ON TABLE public.swes_pa_oidc_challenges FROM "+WRITER
                )
                conn.exec_driver_sql(
                    "ALTER ROLE "+WRITER+" CREATEROLE"
                )
            try:
                with writer_engine.connect():
                    pass
            except OIDCHold as exc:
                assert exc.code=="HOLD_OIDC_WRITER_ROLE_NOT_RESTRICTED"
            else:
                raise AssertionError("HOLD_WRITER_ROLE_ESCALATION_ACCEPTED")
            print("R11_DRIFT_DENIAL_BROAD_TABLE_UPDATE_GRANT_ROLE_ESCALATION=PASS")
        finally:
            if prior_db is None:os.environ.pop("DATABASE_URL",None)
            else:os.environ["DATABASE_URL"]=prior_db
            if prior_oidc is None:os.environ.pop("SWES_OIDC_WRITER_DATABASE_URL",None)
            else:os.environ["SWES_OIDC_WRITER_DATABASE_URL"]=prior_oidc
    finally:
        if writer_engine is not None:writer_engine.dispose()
        if owner_engine is not None:owner_engine.dispose()
        if started:
            run_bin("pg_ctl.exe","-D",CLUSTER/"data","-m","fast","-w","stop")
        if CLUSTER.exists():shutil.rmtree(CLUSTER)
        print("R11_DISPOSABLE_SCRAM_PG17_STOP_AND_CLEANUP=PASS")


if __name__=="__main__":test()
