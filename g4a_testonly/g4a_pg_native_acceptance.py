"""Opt-in G4-A isolated PostgreSQL17 acceptance (Pavilion TEST ONLY).

Requires G4A_TEST_DATABASE_URL, specifically DB g4a_v24_native_product_test
on loopback port 55449. Does not create database, contact WND, send provider
requests, create genuine PC5 accounts or write to official SO1 catalog.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
import json,os
from pathlib import Path
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from restaurant.g4a_canonical_product_publication import (
    CanonicalProductError, ProductState,
)
from restaurant.g4a_canonical_product_pg_repository import (
    PgProductCandidateStore,
)

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT
DB="g4a_v24_native_product_test"
dsn=os.environ.get("G4A_TEST_DATABASE_URL","")
if not dsn or "password=" not in dsn:
    raise SystemExit("G4A_PG_TEST_REQUIRES_PRIVATE_CONNECTION")
COUNTER=0
def check(v,description):
    global COUNTER
    if not v:raise AssertionError("G4A_NATIVE_PG_"+description)
    COUNTER+=1

def connect():
    conn=psycopg2.connect(dsn,connect_timeout=5)
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_database(),inet_server_addr()::text,inet_server_port()")
        database,ip,port=cursor.fetchone()
    if (database,ip.split("/",1)[0],port)!=(DB,"127.0.0.1",55449):
        conn.close()
        raise RuntimeError("G4A_PG_TEST_DATABASE_OR_HOST_NOT_ALLOWED "+repr((database,ip,port)))
    return conn

# Bring in canonical focused test helpers, but use real PostgreSQL for storage.
suite=REPO/"tests/contracts/test_g4a_canonical_product_publication.py"
spec=importlib.util.spec_from_file_location("g4a_test_fixtures",suite)
fixture=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

def insert(product=fixture.PRODUCT,*,tenant=920002,branch=1,
           correlation=None):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""INSERT INTO g4a_product_review_candidates(
                 public_id,tenant_id,location_id,creator_identity_id,
                 atomic_unit_public_id,atomic_unit_version,
                 semantic_qualified_code,semantic_version,pack_code,
                 pack_version,revision,state,zone_prices)
                 VALUES (%s,%s,%s,100,%s,3,%s,2,%s,%s,3,'review',%s::jsonb)""",
                (str(product),tenant,branch,str(fixture.ATOMIC),
                 "industry.restaurant:soft_drink","wnd.restaurant","1.0.0",
                 json.dumps({
                    "MAIN":{"amount_xaf":1700,"revision":2},
                    "VIP":{"amount_xaf":2300,"revision":2},
                    "BAR":{"amount_xaf":1900,"revision":2}})))
    return product

def row(product):
    with connect() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as c:
            c.execute("SELECT state,revision,reviewer_identity_id FROM g4a_product_review_candidates WHERE public_id=%s",(str(product),))
            r=c.fetchone()
            c.execute("SELECT COUNT(*) AS n FROM g4a_product_candidate_audit WHERE product_public_id=%s",(str(product),))
            a=c.fetchone()["n"]
    return r,a

def pair(product=fixture.PRODUCT):
    app,cmd,i,sem,pk,so,store,control=fixture.build()
    app.store=PgProductCandidateStore(connect)
    return app,replace(cmd,product_public_id=product),i,sem,pk,so,control

def rejected(app,cmd,code):
    try:app.publish(cmd)
    except CanonicalProductError as e:
        check(e.code==code,"FAIL_CLOSED_"+code)
        return
    raise AssertionError("G4A_UNEXPECTED_PUBLISH_SUCCESS")

def main():
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("SELECT count(*) FROM g4a_product_review_candidates")
            check(c.fetchone()[0]==0,"FRESH_CANONICAL_TEST_SCHEMA")

    a=insert()
    app,cmd,identity,sem,pk,so,control=pair()
    first=app.publish(cmd)
    check(first.committed_revision==4,"FIRST_CANONICAL_PRODUCT_COMMIT")
    state,audit=row(a)
    check(state["state"]=="published" and state["revision"]==4,"PG_SOURCE_STATE_CAS")
    check(state["reviewer_identity_id"]==200 and audit==1,"PG_ONE_AUDIT")
    check(first.finance_binding_version==8 and not first.official_finance_posted,
          "NO_OFFICIAL_FINANCE_POSTED")
    rejected(app,cmd,"G4A_SOURCE_REVISION_OR_STATE_STALE")
    check(row(a)[1]==1,"REPLAY_NO_DUPLICATE_AUDIT")

    # Separate real connection transactions race on identical product:
    # SELECT FOR UPDATE serializes and exactly one can win.
    b=insert(UUID("aaaaaaaa-0000-4000-8000-000000000018"))
    app2,cmd2,*_=pair(b)
    cmd2=replace(cmd2,correlation_id="G4A-RACE-CORRELATION-018")
    def race(_):
        try:app2.publish(cmd2);return "PASS"
        except CanonicalProductError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        race_results=list(pool.map(race,[1,2]))
    print("G4A_NATIVE_CONCURRENCY_OUTCOMES="+repr(race_results))
    check(race_results.count("PASS")==1,"PG_CONCURRENT_ONE_WINNER")
    check(race_results.count("G4A_SOURCE_REVISION_OR_STATE_STALE")==1,
          "PG_CONCURRENT_ONE_STALE")
    check(row(b)[1]==1,"PG_ONE_WINNER_ONE_AUDIT")

    # True canonical PC5 denies revoked identity; no source write.
    c=insert(UUID("aaaaaaaa-0000-4000-8000-000000000019"))
    app3,cmd3,i3,sem3,pk3,so3,config3=pair(c)
    i3.revoked=True
    rejected(app3,cmd3,"G4A_REAL_PC5_DENIED_OR_NOT_ADMITTED")
    check(row(c)[0]["state"]=="review" and row(c)[1]==0,"PG_REVOKED_DENIAL_NO_WRITE")

    i3.revoked=False
    pk3.active=False
    rejected(app3,cmd3,"G4A_CANONICAL_PACK_NOT_ACTIVE")
    check(row(c)[1]==0,"PG_PACK_DENIAL_NO_WRITE")

    pk3.active=True
    config3["finance"]=False
    rejected(app3,cmd3,"G4A_FINANCE_ACCOUNT_MAPPING_NOT_CERTIFIED")
    check(row(c)[1]==0,"PG_FINANCE_DENIAL_NO_WRITE")

    # Collision of immutable correlation_id must rollback state under SQL error.
    config3["finance"]=True
    rejected(app3,cmd3,"G4A_CANONICAL_AUTHORITY_OR_TRANSACTION_UNAVAILABLE")
    check(row(c)[0]["state"]=="review" and row(c)[1]==0,
          "PG_DUPLICATE_AUDIT_ROLLS_BACK")
    # Now a different correlation id can commit normally.
    good=app3.publish(replace(cmd3,correlation_id="G4A-UNIQUE-CORRELATION-019"))
    check(good.committed_revision==4 and row(c)[1]==1,"PG_RECOVER_AFTER_COLLISION")

    # Source request cannot see a different branch.
    wrong=replace(cmd3,location_id=999,correlation_id="G4A-WRONG-LOCATION")
    rejected(app3,wrong,"G4A_PRODUCT_SCOPE_NOT_FOUND")
    check(row(c)[1]==1,"PG_CROSS_BRANCH_DENIED")
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM g4a_product_candidate_audit")
            check(cursor.fetchone()[0]==3,"PG_FINAL_THREE_PUBLICATION_EVENTS")
    print("G4A_CANONICAL_NATIVE_POSTGRESQL17_PASS="+str(COUNTER))
    print("G4A_OFFICIAL_FINANCE_POSTED=NO")
    print("G4A_GENUINE_PC5_ISSUER_ADMITTED=NO")
    print("G4A_LIVE_WND_WRITES=NO")

if __name__=="__main__":main()
