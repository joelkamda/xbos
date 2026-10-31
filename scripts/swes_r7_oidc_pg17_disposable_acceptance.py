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
from sqlalchemy import create_engine,text
from platform_admin.swes_google_oidc_r7 import Challenge,digest
from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore

DIR=Path(r"C:\Users\jdkam\XafPayOps\PCR_WORKTREES\SWES_R7_OIDC_PG17_DISPOSABLE_20261031")
BIN=Path(r"C:\Program Files\PostgreSQL\17\bin")
PORT=55473
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
            print("SWES_R7_PG17_OIDC_REPLAY_SEALED_CHALLENGE=PASS")
        finally:engine.dispose()
    finally:
        if started:
            execute("pg_ctl.exe","-D",DIR/"data","-m","fast","-w","stop")
        shutil.rmtree(DIR)
        print("SWES_R7_PG17_DISPOSABLE_CLEANUP=PASS")

if __name__=="__main__":main()
