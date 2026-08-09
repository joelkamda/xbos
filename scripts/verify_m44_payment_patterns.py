"""Development safety gate and disposable M4.4 payment-pattern rehearsal."""
from __future__ import annotations
import argparse,os,sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand,CreatePaymentRequestCommand,PaymentCommandIdempotencyConflict
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_tender_contract import CreatePaymentTenderCommand,TransitionPaymentTenderCommand,PaymentTenderValidationError
from core.domain.finance.payment_tender_engine import TransactionalPaymentTenderEngine
from core.domain.finance.payment_tender_repository import PaymentTenderRepository
from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand,TransitionPaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_settlement_contract import CreatePaymentSettlementCommand,TransitionPaymentSettlementCommand
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.persistence.m40_payment_foundation import FOUNDATION_TABLES
from core.persistence.m44_payment_patterns import *
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME="xbos_track_b_dev"; BASE=datetime(2026,8,9,16,tzinfo=timezone.utc)
def _url():return make_url(application_engine.url.render_as_string(hide_password=False))
def _engine(name,isolation_level=None):return create_engine(_url().set(database=name),isolation_level=isolation_level,pool_pre_ping=True)
def _exists(name):
    e=_engine("postgres","AUTOCOMMIT")
    try:
        with e.connect() as c:return bool(c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"),{"n":name}).scalar_one_or_none())
    finally:e.dispose()
def _create():
    if _exists(TEST_DATABASE_NAME):raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose();e=_engine("postgres","AUTOCOMMIT")
    try:
        with e.connect() as c:c.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally:e.dispose()
def _drop(name):
    if name!=TEST_DATABASE_NAME:raise RuntimeError(f"unsafe target={name}")
    e=_engine("postgres","AUTOCOMMIT")
    try:
        with e.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name});c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:e.dispose()
@contextmanager
def _migration_db(name):
    old=os.environ.get("DATABASE_URL");os.environ["DATABASE_URL"]=_url().set(database=name).render_as_string(hide_password=False)
    try:yield
    finally:
        if old is None:os.environ.pop("DATABASE_URL",None)
        else:os.environ["DATABASE_URL"]=old
def _migrate(name,revision,down=False):
    with _migration_db(name):(alembic_command.downgrade if down else alembic_command.upgrade)(Config(str(ROOT/"alembic.ini")),revision)
def _revision(c):return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
def _schema(c,expected):
    tables=set(c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
    tcols=set(c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='canonical_payment_tenders'")).scalars())
    scols=set(c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='payment_settlements'")).scalars())
    triggers=set(c.execute(text("SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal")).scalars())
    present=not(set(M44_TABLES)-tables or set(M44_TENDER_COLUMNS)-tcols or set(M44_SETTLEMENT_COLUMNS)-scols or set(M44_TRIGGERS)-triggers)
    if expected and not present:raise RuntimeError("M4.4 schema inventory incomplete")
    if not expected and (set(M44_TABLES)&tables or set(M44_TENDER_COLUMNS)&tcols or set(M44_SETTLEMENT_COLUMNS)&scols or set(M44_TRIGGERS)&triggers):raise RuntimeError("M4.4 schema remains at parent")
def _verify_dev():
    if _url().database!=DEVELOPMENT_DATABASE_NAME:raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as c:
        revision=_revision(c)
        if revision not in {PARENT_REVISION,TARGET_REVISION}:raise RuntimeError(f"unexpected development revision={revision}")
        for table in FOUNDATION_TABLES:
            if c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():raise RuntimeError(f"development payment table not empty={table}")
        for table in ("idempotency_records","value_sources","financial_events","outbox_messages","journal_entries","journal_lines"):
            if c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():raise RuntimeError(f"development side effect not empty={table}")
        _schema(c,revision==TARGET_REVISION)
    print(f"database={DEVELOPMENT_DATABASE_NAME}\nrevision={revision}\nm44_payment_patterns_development=PASS");return revision
def _status():
    value=_exists(TEST_DATABASE_NAME);print(f"database={TEST_DATABASE_NAME} exists={str(value).lower()}");return not value

def _seed(s):
    tenant=int(s.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one());s.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    org=s.execute(text("SELECT id FROM organization_units WHERE tenant_id=:t ORDER BY id LIMIT 1"),{"t":tenant}).scalar_one_or_none()
    if org is None:org=s.execute(text("INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active) VALUES(:t,'branch','m44-verifier','M4.4 Verifier','Africa/Douala',true) RETURNING id"),{"t":tenant}).scalar_one()
    provider=s.execute(text("INSERT INTO payment_provider_accounts(tenant_id,organization_unit_id,provider_code,external_account_reference,credential_reference,environment,active) VALUES(:t,:o,'mtn_momo','m44-sandbox','secret://m44','sandbox',true) ON CONFLICT(provider_code,environment,external_account_reference) DO UPDATE SET active=true RETURNING public_id"),{"t":tenant,"o":org}).scalar_one()
    accounts={}
    for code,kind in (("cash","cash"),("mobile","mobile_money")):
        pid=UUID(f"44000000-0000-0000-0000-{10 if code=='cash' else 11:012d}")
        accounts[code]=UUID(str(s.execute(text("INSERT INTO operational_financial_accounts(public_id,tenant_id,organization_unit_id,account_class,account_type,code,display_name,currency_code,channel_code,aggregation_role,reconciliation_enabled,active,opened_at) VALUES(:p,:t,:o,'treasury',:kind,:code,:name,'XAF',:code,'leaf',true,true,:opened) ON CONFLICT(tenant_id,organization_unit_id,code) DO UPDATE SET active=true RETURNING public_id"),{"p":str(pid),"t":tenant,"o":org,"kind":kind,"code":f"m44-{code}","name":f"M4.4 {code}","opened":BASE}).scalar_one()))
    return tenant,int(org),UUID(str(provider)),accounts
def _request(t,o):return CreatePaymentRequestCommand(public_id=UUID("44000000-0000-0000-0001-000000000001"),tenant_id=t,organization_unit_id=o,purpose_code="payment_link",requested_amount="100",currency_code="XAF",expires_at=BASE+timedelta(hours=3),occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id="request",idempotency_scope="m44.request",idempotency_key="request")
def _intent(t,o,n,amount,methods,mixed=False,max_tenders=1,request=None):return CreatePaymentIntentCommand(public_id=UUID(f"44000000-0000-0000-0002-{n:012d}"),tenant_id=t,organization_unit_id=o,payment_request_public_id=request,requested_amount=amount,currency_code="XAF",payment_method_policy={"allowed_methods":methods,"allow_mixed_tender":mixed,"max_tenders":max_tenders},expires_at=BASE+timedelta(hours=3),occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id=f"intent-{n}",idempotency_scope="m44.intent",idempotency_key=f"intent-{n}")
def _tender(t,o,intent,n,number,amount,method):return CreatePaymentTenderCommand(public_id=UUID(f"44000000-0000-0000-0003-{n:012d}"),tenant_id=t,organization_unit_id=o,payment_intent_public_id=intent.public_id,tender_number=number,tender_amount=amount,currency_code="XAF",payment_method_code=method,occurred_at=BASE+timedelta(minutes=n),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id=f"tender-{n}",idempotency_scope="m44.tender",idempotency_key=f"tender-{n}")
def _tender_transition(command,state,key):return TransitionPaymentTenderCommand(tenant_id=command.tenant_id,organization_unit_id=command.organization_unit_id,payment_tender_public_id=command.public_id,expected_row_version=1,target_state=state,reason_code=key,evidence_payload={"result":state},occurred_at=command.occurred_at+timedelta(minutes=10),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id=key,idempotency_scope="m44.tender.transition",idempotency_key=key)
def _attempt(t,o,intent,tender,provider):return CreatePaymentAttemptCommand(public_id=UUID("44000000-0000-0000-0004-000000000001"),tenant_id=t,organization_unit_id=o,payment_intent_public_id=intent.public_id,payment_tender_public_id=tender.public_id,attempted_amount=tender.tender_amount,currency_code="XAF",payment_method_code=tender.payment_method_code,payment_rail_code="mtn_momo",orchestrator_code="xbos_direct",provider_account_public_id=provider,underlying_provider_code="mtn_momo",timeout_at=BASE+timedelta(hours=1),occurred_at=BASE+timedelta(minutes=20),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id="attempt",idempotency_scope="m44.attempt",idempotency_key="attempt")
def _attempt_transition(a,version,state,key,minute):return TransitionPaymentAttemptCommand(tenant_id=a.tenant_id,organization_unit_id=a.organization_unit_id,payment_attempt_public_id=a.public_id,expected_row_version=version,target_state=state,reason_code=key,external_attempt_reference="m44-provider-attempt",evidence_payload={"result":state} if state=="succeeded" else {},occurred_at=BASE+timedelta(minutes=minute),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id=key,idempotency_scope="m44.attempt.transition",idempotency_key=key)
def _settlement(t,o,intent,tender,account,n,amount,method,rail,attempt=None):return CreatePaymentSettlementCommand(public_id=UUID(f"44000000-0000-0000-0005-{n:012d}"),tenant_id=t,organization_unit_id=o,payment_intent_public_id=intent.public_id,payment_tender_public_id=tender.public_id,payment_attempt_public_id=attempt.public_id if attempt else None,operational_account_public_id=account,settlement_direction="incoming",gross_amount=amount,fee_amount="0",net_amount=amount,currency_code="XAF",payment_method_code=method,payment_rail_code=rail,value_date=date(2026,8,10),occurred_at=BASE+timedelta(minutes=40+n),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id=f"settlement-{n}",idempotency_scope="m44.settlement",idempotency_key=f"settlement-{n}")
def _confirm(c,key,reference=None):return TransitionPaymentSettlementCommand(tenant_id=c.tenant_id,organization_unit_id=c.organization_unit_id,payment_settlement_public_id=c.public_id,expected_row_version=1,target_state="confirmed",finality_status="final",availability_state="available",reason_code=key,external_settlement_reference=reference,evidence_payload={"result":"confirmed"},occurred_at=c.occurred_at+timedelta(minutes=1),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=44),actor_service="m44.verifier",source_component="m44.verifier",source_record_id=key,idempotency_scope="m44.settlement.transition",idempotency_key=key)

def _exercise(engine):
    with Session(engine) as s,s.begin():
        t,o,provider,accounts=_seed(s);request=_request(t,o);TransactionalPaymentIntentEngine.create_request(s,request)
        mixed=_intent(t,o,1,"100",["cash","mobile_money"],True,2,request.public_id);card=_intent(t,o,2,"10",["card"]);orange=_intent(t,o,3,"10",["mobile_money"]);bank=_intent(t,o,4,"10",["bank_transfer"])
        for i in (mixed,card,orange,bank):TransactionalPaymentIntentEngine.create_intent(s,i)
        cash=_tender(t,o,mixed,1,1,"40","cash");mobile=_tender(t,o,mixed,2,2,"60","mobile_money");card_t=_tender(t,o,card,3,1,"10","card");orange_t=_tender(t,o,orange,4,1,"10","mobile_money");bank_t=_tender(t,o,bank,5,1,"10","bank_transfer")
        for tender in (cash,mobile,card_t,orange_t,bank_t):TransactionalPaymentTenderEngine.create(s,tender)
        if not TransactionalPaymentTenderEngine.create(s,cash).replayed:raise RuntimeError("tender replay failed")
        try:TransactionalPaymentTenderEngine.create(s,replace(cash,tender_amount=Decimal("39")))
        except PaymentCommandIdempotencyConflict:pass
        else:raise RuntimeError("tender conflict accepted")
        try:TransactionalPaymentTenderEngine.create(s,_tender(t,o,mixed,6,3,"1","cash"))
        except PaymentTenderValidationError as exc:
            if exc.code not in {"maximum_tenders_exceeded","tender_capacity_exceeded"}:raise
        else:raise RuntimeError("over-capacity tender accepted")
        mixed_authority=PaymentTenderRepository.lock_intent(s,t,mixed.public_id)
        count,total=PaymentTenderRepository.composition(s,t,mixed_authority.id)
        if count!=2 or total!=Decimal("100"):raise RuntimeError("split tender does not exactly compose intent")
        attempt=_attempt(t,o,mixed,mobile,provider);TransactionalPaymentAttemptEngine.create(s,attempt);TransactionalPaymentAttemptEngine.transition(s,_attempt_transition(attempt,1,"processing","m44_attempt_processing",30));TransactionalPaymentAttemptEngine.transition(s,_attempt_transition(attempt,2,"succeeded","m44_attempt_succeeded",31))
        cash_set=_settlement(t,o,mixed,cash,accounts["cash"],1,"40","cash","cash");mobile_set=_settlement(t,o,mixed,mobile,accounts["mobile"],2,"60","mobile_money","mtn_momo",attempt)
        TransactionalPaymentSettlementEngine.create(s,cash_set);TransactionalPaymentSettlementEngine.transition(s,_confirm(cash_set,"m44_cash_confirmed"));TransactionalPaymentSettlementEngine.create(s,mobile_set);TransactionalPaymentSettlementEngine.transition(s,_confirm(mobile_set,"m44_mobile_confirmed","m44-provider-settlement"))
        TransactionalPaymentTenderEngine.transition(s,_tender_transition(cash,"succeeded","m44_cash_tender_succeeded"));TransactionalPaymentTenderEngine.transition(s,_tender_transition(mobile,"succeeded","m44_mobile_tender_succeeded"))
        if PaymentTenderRepository.find_tender(s,t+100000,cash.public_id) is not None:raise RuntimeError("cross-tenant tender lookup succeeded")
    with engine.connect() as c:
        counts={"requests":c.execute(text("SELECT count(*) FROM canonical_payment_requests")).scalar_one(),"intents":c.execute(text("SELECT count(*) FROM canonical_payment_intents")).scalar_one(),"tenders":c.execute(text("SELECT count(*) FROM canonical_payment_tenders")).scalar_one(),"tender_transitions":c.execute(text("SELECT count(*) FROM payment_tender_transitions")).scalar_one(),"attempts":c.execute(text("SELECT count(*) FROM canonical_payment_attempts")).scalar_one(),"settlements":c.execute(text("SELECT count(*) FROM payment_settlements")).scalar_one()}
        if counts!={"requests":1,"intents":4,"tenders":5,"tender_transitions":7,"attempts":1,"settlements":2}:raise RuntimeError(f"unexpected pattern counts={counts}")
        if c.execute(text("SELECT count(*) FROM payment_settlements s JOIN canonical_payment_attempts a ON a.id=s.payment_attempt_id WHERE s.payment_tender_id IS DISTINCT FROM a.payment_tender_id")).scalar_one():raise RuntimeError("settlement crossed tender authority")
        dates=c.execute(text("SELECT value_date,recorded_at::date FROM payment_settlements WHERE payment_rail_code='mtn_momo'")).one();
        if dates[0]==dates[1]:raise RuntimeError("delayed settlement date semantics collapsed")
        for statement in ("UPDATE canonical_payment_tenders SET tender_amount=1 WHERE tender_number=1","UPDATE payment_tender_transitions SET reason_code='changed' WHERE sequence_number=1"):
            try:
                with c.begin_nested():c.exec_driver_sql(statement)
            except DBAPIError:pass
            else:raise RuntimeError("direct SQL tender bypass succeeded")
        side={x:c.execute(text(f"SELECT count(*) FROM {x}")).scalar_one() for x in FORBIDDEN_SIDE_EFFECT_TABLES};side={k:v for k,v in side.items() if v}
        if side:raise RuntimeError(f"forbidden side effects={side}")

def _run():
    if _verify_dev()!=PARENT_REVISION:raise RuntimeError(f"development must start at {PARENT_REVISION}")
    _create();e=None
    try:
        _migrate(TEST_DATABASE_NAME,TARGET_REVISION);e=_engine(TEST_DATABASE_NAME)
        with e.connect() as c:_schema(c,True)
        e.dispose();e=None;_migrate(TEST_DATABASE_NAME,PARENT_REVISION,True);e=_engine(TEST_DATABASE_NAME)
        with e.connect() as c:_schema(c,False)
        e.dispose();e=None;_migrate(TEST_DATABASE_NAME,TARGET_REVISION);e=_engine(TEST_DATABASE_NAME);_exercise(e);e.dispose();e=None;_drop(TEST_DATABASE_NAME);_verify_dev()
        print("m44_payment_patterns=PASS database="+TEST_DATABASE_NAME+" cash=PASS mtn=PASS orange=PASS bank=PASS card=PASS split_tender=PASS standalone=PASS payment_link=PASS delayed_settlement=PASS capacity=PASS replay=PASS conflict=PASS tenant_scope=PASS direct_sql=PASS side_effects=0 upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if e is not None:e.dispose()
        print(f"M4.4 verification failed; retained disposable database={TEST_DATABASE_NAME}");raise
def main():
    p=argparse.ArgumentParser();subs=p.add_subparsers(dest="command",required=True);subs.add_parser("status");subs.add_parser("verify");subs.add_parser("create-and-verify");d=subs.add_parser("drop");d.add_argument("--confirm-database-name",required=True);a=p.parse_args()
    if a.command=="status":return 0 if _status() else 1
    if a.command=="verify":_verify_dev()
    elif a.command=="create-and-verify":_run()
    else:
        if a.confirm_database_name!=TEST_DATABASE_NAME:raise RuntimeError("exact disposable confirmation required")
        _drop(TEST_DATABASE_NAME);print(f"dropped={TEST_DATABASE_NAME}")
    return 0
if __name__=="__main__":raise SystemExit(main())
