"""Disposable proof for M3.4 deterministic obligation aging."""

from __future__ import annotations
import argparse,os,sys
from contextlib import contextmanager
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from core.domain.finance.aging_contract import AgingPolicy,AsOfAgingQuery
from core.domain.finance.allocation_contract import AllocateValueCommand,CreateValueSourceCommand,ReverseAllocationCommand
from core.domain.finance.allocation_engine import TransactionalAllocationEngine
from core.domain.finance.obligation_aging_service import ObligationAgingService
from core.domain.finance.obligation_contract import CreateObligationCommand,ObligationLineCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from database import engine as application_engine

TEST_DATABASE_NAME="xbos_track_b_m34_aging_test"; DEVELOPMENT_DATABASE_NAME="xbos_track_b_dev"
PARENT_REVISION="m32_allocation_engine_009"; TARGET_REVISION="m34_obligation_aging_010"
TENANT=3401; ORG=3411; CORRELATION=UUID("34000000-0000-0000-0000-000000000099")

def _app_url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _url(name): return _app_url().set(database=name)
def _engine(name,auto=False): return create_engine(_url(name),pool_pre_ping=True,**({"isolation_level":"AUTOCOMMIT"} if auto else {}))
def _exists(name):
    e=_engine("postgres",True)
    try:
        with e.connect() as c: return bool(c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"),{"n":name}).scalar_one_or_none())
    finally: e.dispose()
def _create():
    if _exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    e=_engine("postgres",True)
    try:
        with e.connect() as c: c.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally: e.dispose()
def _drop(name):
    if name!=TEST_DATABASE_NAME: raise RuntimeError(f"refusing unapproved database: {name}")
    e=_engine("postgres",True)
    try:
        with e.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name})
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally: e.dispose()
@contextmanager
def _selected(name):
    prior=os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"]=_url(name).render_as_string(hide_password=False)
    try: yield
    finally:
        if prior is None: os.environ.pop("DATABASE_URL",None)
        else: os.environ["DATABASE_URL"]=prior
def _upgrade(revision):
    with _selected(TEST_DATABASE_NAME): alembic_command.upgrade(Config(str(ROOT/"alembic.ini")),revision)
def _downgrade(revision):
    with _selected(TEST_DATABASE_NAME): alembic_command.downgrade(Config(str(ROOT/"alembic.ini")),revision)
def _seed(e):
    with e.begin() as c:
        c.execute(text("""INSERT INTO tenants(id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
          VALUES(:t,'M34T','M3.4 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)"""),{"t":TENANT})
        c.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata) VALUES('XAF','fiat','CFA',0,8,TRUE,'{}'::jsonb)"))
        c.execute(text("INSERT INTO organization_units(id,tenant_id,unit_type,code,name,timezone_name,active) VALUES(:o,:t,'legal_entity','M34','M3.4 Entity','Africa/Douala',TRUE)"),{"o":ORG,"t":TENANT})

def _obligation(public_id,amount,key,occurred,due):
    return CreateObligationCommand(public_id=public_id,tenant_id=TENANT,organization_unit_id=ORG,
      debtor_party_id=UUID("34000000-0000-0000-0000-000000000010"),creditor_party_id=UUID("34000000-0000-0000-0000-000000000011"),
      obligation_type="trade_receivable",original_amount=Decimal(amount),currency_code="XAF",due_at=due,occurred_at=occurred,
      business_date=occurred.date(),calendar_policy_version=1,correlation_id=CORRELATION,actor_service="m34.verifier",
      source_component="m34.verifier",source_record_id=key,idempotency_scope="m34.obligation",idempotency_key=key,
      lines=(ObligationLineCommand(1,"principal","Principal",Decimal("1"),Decimal(amount),Decimal(amount),key+"-line"),))
def _source(public_id,amount,key,occurred):
    return CreateValueSourceCommand(public_id=public_id,tenant_id=TENANT,organization_unit_id=ORG,
      owner_party_id=UUID("34000000-0000-0000-0000-000000000010"),source_type="payment",source_amount=Decimal(amount),currency_code="XAF",
      occurred_at=occurred,business_date=occurred.date(),calendar_policy_version=1,correlation_id=CORRELATION,actor_service="m34.verifier",
      source_component="m34.verifier",source_record_id=key,idempotency_scope="m34.source",idempotency_key=key)
def _allocation(public_id,source,obligation,amount,key,occurred):
    return AllocateValueCommand(public_id=public_id,tenant_id=TENANT,organization_unit_id=ORG,value_source_public_id=source,
      obligation_public_id=obligation,allocation_amount=Decimal(amount),currency_code="XAF",occurred_at=occurred,business_date=occurred.date(),
      calendar_policy_version=1,correlation_id=CORRELATION,actor_service="m34.verifier",source_component="m34.verifier",
      source_record_id=key,idempotency_scope="m34.allocate",idempotency_key=key)

def _exercise(e):
    base=datetime(2026,8,1,10,tzinfo=timezone.utc); oid=UUID("34000000-0000-0000-0000-000000000101")
    sid=UUID("34000000-0000-0000-0000-000000000201"); aid=UUID("34000000-0000-0000-0000-000000000301")
    with Session(e) as s,s.begin():
        TransactionalObligationEngine.create(s,_obligation(oid,"100","o1",base,base+timedelta(days=30)))
        TransactionalAllocationEngine.create_value_source(s,_source(sid,"60","s1",base+timedelta(days=1)))
        TransactionalAllocationEngine.allocate(s,_allocation(aid,sid,oid,"60","a1",base+timedelta(days=2)))
        reverse=ReverseAllocationCommand(public_id=UUID("34000000-0000-0000-0000-000000000401"),tenant_id=TENANT,organization_unit_id=ORG,
          payment_allocation_public_id=aid,reversal_amount=Decimal("20"),currency_code="XAF",reason_code="correction",occurred_at=base+timedelta(days=4),
          business_date=(base+timedelta(days=4)).date(),calendar_policy_version=1,correlation_id=CORRELATION,actor_service="m34.verifier",
          source_component="m34.verifier",source_record_id="r1",idempotency_scope="m34.reverse",idempotency_key="r1")
        TransactionalAllocationEngine.reverse(s,reverse)
    def outstanding(cutoff):
        with Session(e) as s:
            q=AsOfAgingQuery(TENANT,cutoff,cutoff.date(),include_terminal=True)
            return ObligationAgingService.get(s,q).rows[0].outstanding_amount
    if [outstanding(base+timedelta(days=n)) for n in (1,3,5)] != [Decimal("100"),Decimal("40"),Decimal("60")]:
        raise RuntimeError("as-of allocation/reversal cutoffs differ")
    policy=AgingPolicy(); expected={-1:"not_due",0:"due_today",30:"past_due_1_30",31:"past_due_31_60",61:"past_due_61_90",91:"past_due_91_plus"}
    if {d:policy.classify(d) for d in expected}!=expected: raise RuntimeError("bucket boundary differs")
    # Database captures a direct state change and default aging excludes terminal rows.
    with e.begin() as c:
        c.execute(text("UPDATE financial_obligations SET obligation_state='written_off',row_version=row_version+1 WHERE public_id=:id"),{"id":str(oid)})
    future=datetime.now(timezone.utc)+timedelta(days=1)
    with Session(e) as s:
        hidden=ObligationAgingService.get(s,AsOfAgingQuery(TENANT,future,future.date()))
        visible=ObligationAgingService.get(s,AsOfAgingQuery(TENANT,future,future.date(),include_terminal=True))
        if hidden.rows or visible.rows[0].state_as_of!="written_off": raise RuntimeError("historical terminal filter differs")
        if ObligationAgingService.get(s,AsOfAgingQuery(TENANT+1,future,future.date(),include_terminal=True)).rows:
            raise RuntimeError("tenant isolation failed")
        if ObligationAgingService.get(s,AsOfAgingQuery(TENANT,future,future.date(),ORG+1,True)).rows:
            raise RuntimeError("organization isolation failed")
        transitions=s.execute(text("SELECT count(*) FROM obligation_state_transitions WHERE tenant_id=:t AND obligation_id=(SELECT id FROM financial_obligations WHERE public_id=:id)"),{"t":TENANT,"id":str(oid)}).scalar_one()
        if transitions < 3: raise RuntimeError(f"state transition capture differs: {transitions}")
    with e.connect() as c:
        try:
            with c.begin(): c.execute(text("UPDATE obligation_state_transitions SET to_state='open' WHERE tenant_id=:t"),{"t":TENANT})
        except Exception: pass
        else: raise RuntimeError("history immutability bypass succeeded")

def _dev_verify():
    if _app_url().database!=DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected {DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as c:
        revision=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision not in {PARENT_REVISION,TARGET_REVISION}: raise RuntimeError(f"unexpected revision: {revision}")
        if c.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one()!=20: raise RuntimeError("catalog count differs")
        tables=["idempotency_records","financial_events","outbox_messages","journal_entries","journal_lines","financial_obligations","financial_obligation_lines","value_sources","payment_allocations","allocation_reversals","allocation_scope_policies"]
        if revision==TARGET_REVISION: tables.append("obligation_state_transitions")
        for table in tables:
            count=c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count: raise RuntimeError(f"development table not empty: {table}={count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={revision}"); print("m34_obligation_aging_development=PASS")

def _create_verify():
    _dev_verify(); _create(); e=None
    try:
        _upgrade(TARGET_REVISION); e=_engine(TEST_DATABASE_NAME); _seed(e); _exercise(e); e.dispose(); e=None
        _downgrade(PARENT_REVISION); _upgrade(TARGET_REVISION); _drop(TEST_DATABASE_NAME); _dev_verify()
        print("m34_obligation_aging=PASS database=xbos_track_b_m34_aging_test buckets=PASS allocation_cutoff=PASS reversal_cutoff=PASS historical_state=PASS terminal_filter=PASS tenant_scope=PASS organization_scope=PASS immutability=PASS direct_sql_capture=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if e is not None: e.dispose()
        print(f"M3.4 verification failed; retained disposable database={TEST_DATABASE_NAME}",file=sys.stderr); raise

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True); sub.add_parser("status"); sub.add_parser("verify"); sub.add_parser("create-and-verify")
    d=sub.add_parser("drop"); d.add_argument("--confirm-database-name",required=True); a=p.parse_args()
    if a.command=="status": print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif a.command=="verify": _dev_verify()
    elif a.command=="drop": _drop(a.confirm_database_name); print(f"dropped={a.confirm_database_name}")
    else: _create_verify()
    return 0
if __name__=="__main__": raise SystemExit(main())
