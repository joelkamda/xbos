"""Read-only development gate and disposable M4.5 XafPay rehearsal."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_tender_contract import CreatePaymentTenderCommand
from core.domain.finance.payment_tender_engine import TransactionalPaymentTenderEngine
from core.integrations.xafpay.contract import ProcessXafPayCallbackCommand,RecordXafPayInitiationCommand,XafPayIntegrationError
from core.integrations.xafpay.orchestration_service import XafPayOrchestrationService
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME="xbos_track_b_dev"
TEST_DATABASE_NAME="xbos_track_b_m45_xafpay_test"
TARGET_REVISION="m44_payment_patterns_014"
BASE=datetime(2026,8,9,15,tzinfo=timezone.utc)
TENANT_UUID=UUID("45000000-0000-0000-0000-000000000001")

PAYMENT_TABLES=(
    "canonical_payment_requests","canonical_payment_intents","canonical_payment_tenders",
    "payment_tender_transitions","canonical_payment_attempts","canonical_payment_attempt_transitions",
    "provider_callback_events","payment_settlements","payment_settlement_transitions",
    "payment_settlement_reversals",
)

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
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name})
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:e.dispose()
def _revision(c):return c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
def _verify_dev():
    if _url().database!=DEVELOPMENT_DATABASE_NAME:raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as c:
        revision=_revision(c)
        if revision!=TARGET_REVISION:raise RuntimeError(f"unexpected development revision={revision}")
        for table in PAYMENT_TABLES+("idempotency_records","financial_events","outbox_messages","journal_entries","journal_lines"):
            if c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():raise RuntimeError(f"development table not empty={table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}\nrevision={revision}\nm45_xafpay_development=PASS")
def _status():
    value=_exists(TEST_DATABASE_NAME);print(f"database={TEST_DATABASE_NAME} exists={str(value).lower()}");return not value

def _seed(session):
    tenant=int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    org=session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:t ORDER BY id LIMIT 1"),{"t":tenant}).scalar_one_or_none()
    if org is None:
        org=session.execute(text("INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active) VALUES(:t,'branch','m45-verifier','M4.5 Verifier','Africa/Douala',true) RETURNING id"),{"t":tenant}).scalar_one()
    provider=UUID(str(session.execute(text("""
        INSERT INTO payment_provider_accounts(
          public_id,tenant_id,organization_unit_id,provider_code,external_account_reference,
          credential_reference,environment,active
        ) VALUES(:p,:t,:o,'tranzak','m45-sandbox','secret://m45','sandbox',true)
        ON CONFLICT(provider_code,environment,external_account_reference)
        DO UPDATE SET active=true RETURNING public_id
    """),{"p":"45000000-0000-0000-0000-000000000010","t":tenant,"o":org}).scalar_one()))
    operational=UUID(str(session.execute(text("""
        INSERT INTO operational_financial_accounts(
          public_id,tenant_id,organization_unit_id,account_class,account_type,code,display_name,
          currency_code,channel_code,aggregation_role,reconciliation_enabled,active,opened_at
        ) VALUES(:p,:t,:o,'treasury','mobile_money','m45-xafpay','M4.5 XafPay','XAF','xafpay','leaf',true,true,:opened)
        ON CONFLICT(tenant_id,organization_unit_id,code) DO UPDATE SET active=true RETURNING public_id
    """),{"p":"45000000-0000-0000-0000-000000000011","t":tenant,"o":org,"opened":BASE}).scalar_one()))
    return tenant,int(org),provider,operational

def _intent(t,o):return CreatePaymentIntentCommand(
    public_id=UUID("45000000-0000-0000-0001-000000000001"),tenant_id=t,organization_unit_id=o,
    requested_amount="100",currency_code="XAF",payment_method_policy={"allowed_methods":["mobile_money"],"allow_mixed_tender":False,"max_tenders":1},
    expires_at=BASE+timedelta(hours=4),occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,
    correlation_id=TENANT_UUID,actor_service="m45.verifier",source_component="m45.verifier",source_record_id="intent",
    idempotency_scope="m45.intent",idempotency_key="intent")
def _tender(t,o,intent):return CreatePaymentTenderCommand(
    public_id=UUID("45000000-0000-0000-0002-000000000001"),tenant_id=t,organization_unit_id=o,
    payment_intent_public_id=intent.public_id,tender_number=1,tender_amount="100",currency_code="XAF",payment_method_code="mobile_money",
    occurred_at=BASE+timedelta(minutes=1),business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=TENANT_UUID,
    actor_service="m45.verifier",source_component="m45.verifier",source_record_id="tender",idempotency_scope="m45.tender",idempotency_key="tender")
def _attempt(t,o,intent,tender,provider):return CreatePaymentAttemptCommand(
    public_id=UUID("45000000-0000-0000-0003-000000000001"),tenant_id=t,organization_unit_id=o,
    payment_intent_public_id=intent.public_id,payment_tender_public_id=tender.public_id,attempted_amount="100",currency_code="XAF",
    payment_method_code="mobile_money",payment_rail_code="mtn_momo",orchestrator_code="xafpay",provider_account_public_id=provider,
    underlying_provider_code="tranzak",timeout_at=BASE+timedelta(hours=2),occurred_at=BASE+timedelta(minutes=2),
    business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=TENANT_UUID,actor_service="m45.verifier",
    source_component="m45.verifier",source_record_id="attempt",idempotency_scope="m45.attempt",idempotency_key="attempt")

class _FakeTransport:
    def __init__(self):self.calls=[]
    def post(self,*,path,headers,body):
        self.calls.append((path,headers,body))
        return {"id":"45000000-0000-0000-0004-000000000001","status":"created","paymentUrl":"https://pay.xafpay.test/450"}

def _callback(status,event,*,amount=100,secret="m45-callback-secret"):
    payload={"callback_reference":event,"payment_id":"45000000-0000-0000-0003-000000000001","gateway_intent_id":"45000000-0000-0000-0004-000000000001","status":status,"amount":amount,"currency":"XAF","provider":"tranzak","provider_ref":"tranzak-transaction-450","occurred_at":"2026-08-09T15:15:00Z"}
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode();signature=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    return raw,{"X-Xafpay-Event-Id":event,"X-Xafpay-Signature":signature}
def _callback_command(t,o,provider,operational,event,status,*,amount=100,secret="m45-callback-secret",signature_secret=None):
    raw,headers=_callback(status,event,amount=amount,secret=signature_secret or secret)
    return ProcessXafPayCallbackCommand(t,o,provider,operational,raw,headers,secret,BASE+timedelta(minutes=16),date(2026,8,9),1,TENANT_UUID)

def _exercise(engine):
    with Session(engine) as s,s.begin():
        t,o,provider,operational=_seed(s);intent=_intent(t,o);tender=_tender(t,o,intent);attempt=_attempt(t,o,intent,tender,provider)
        TransactionalPaymentIntentEngine.create_intent(s,intent);TransactionalPaymentTenderEngine.create(s,tender);TransactionalPaymentAttemptEngine.create(s,attempt)
        initiation=XafPayOrchestrationService.prepare_initiation(s,tenant_id=t,organization_unit_id=o,payment_attempt_public_id=attempt.public_id,customer_phone="+237670000000",return_url="https://merchant.test/paid",cancel_url="https://merchant.test/cancelled",idempotency_key="m45-initiation")
        transport=_FakeTransport();response=XafPayOrchestrationService.initiate(s,initiation,api_key="not-persisted",transport=transport)
        if len(transport.calls)!=1 or transport.calls[0][2]["externalId"]!=str(attempt.public_id):raise RuntimeError("initiation translation failed")
        XafPayOrchestrationService.record_initiation(s,RecordXafPayInitiationCommand(t,o,attempt.public_id,response,BASE+timedelta(minutes=5),date(2026,8,9),1,TENANT_UUID))
        success=_callback_command(t,o,provider,operational,"m45-success","succeeded")
        result=XafPayOrchestrationService.process_callback(s,success)
        if result.attempt_state!="succeeded" or result.settlement_public_id is None:raise RuntimeError("success callback did not settle")
        replay=XafPayOrchestrationService.process_callback(s,success)
        if not replay.replayed or replay.callback_public_id!=result.callback_public_id:raise RuntimeError("callback replay failed")
        conflict=_callback_command(t,o,provider,operational,"m45-success","succeeded",amount=99)
        try:XafPayOrchestrationService.process_callback(s,conflict)
        except XafPayIntegrationError as exc:
            if exc.code!="callback_replay_conflict":raise
        else:raise RuntimeError("callback_replay_conflict was accepted")
        out_of_order=XafPayOrchestrationService.process_callback(s,_callback_command(t,o,provider,operational,"m45-late-failure","failed"))
        if out_of_order.processing_state!="ignored" or out_of_order.attempt_state!="succeeded":raise RuntimeError("out_of_order callback regressed terminal state")
        rejected=XafPayOrchestrationService.process_callback(s,_callback_command(t,o,provider,operational,"m45-bad-signature","failed",signature_secret="wrong-secret"))
        if rejected.processing_state!="rejected":raise RuntimeError("invalid signature was accepted")
        try:XafPayOrchestrationService.process_callback(s,_callback_command(t,o,provider,operational,"m45-amount-mismatch","succeeded",amount=90))
        except XafPayIntegrationError as exc:
            if exc.code!="callback_amount_mismatch":raise
        else:raise RuntimeError("callback amount mismatch was accepted")
        try:XafPayOrchestrationService.process_callback(s,_callback_command(t+999,o,provider,operational,"m45-cross-tenant","succeeded"))
        except XafPayIntegrationError:pass
        else:raise RuntimeError("cross-tenant callback was accepted")
    with engine.connect() as c:
        counts={table:c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ("canonical_payment_attempts","provider_callback_events","payment_settlements","payment_settlement_transitions")}
        if counts!={"canonical_payment_attempts":1,"provider_callback_events":3,"payment_settlements":1,"payment_settlement_transitions":2}:raise RuntimeError(f"unexpected atomic counts={counts}")
        history=[tuple(row) for row in c.execute(text("SELECT sequence_number,from_state,to_state FROM payment_settlement_transitions ORDER BY sequence_number"))]
        if history!=[(1,None,"pending"),(2,"pending","confirmed")]:raise RuntimeError(f"unexpected settlement lifecycle={history}")
        if c.execute(text("SELECT count(*) FROM outbox_messages")).scalar_one():raise RuntimeError("M4.5 dispatched or enqueued outbox work")
        try:
            with c.begin_nested():c.execute(text("UPDATE provider_callback_events SET processing_state='received' WHERE provider_event_reference='m45-success'"))
        except DBAPIError:pass
        else:raise RuntimeError("callback immutability bypass succeeded")

def _run():
    _verify_dev();_create();e=None
    try:
        e=_engine(TEST_DATABASE_NAME)
        with e.connect() as c:
            if _revision(c)!=TARGET_REVISION:raise RuntimeError("disposable clone changed canonical head")
        _exercise(e);e.dispose();e=None;_drop(TEST_DATABASE_NAME);_verify_dev()
        print("m45_xafpay_orchestration=PASS database="+TEST_DATABASE_NAME+" initiation=PASS signature=PASS replay=PASS conflict=PASS out_of_order=PASS settlement=PASS tenant_scope=PASS immutability=PASS atomicity=PASS side_effects=0 canonical_head_unchanged=PASS dropped=true")
    except Exception:
        if e is not None:e.dispose()
        print(f"M4.5 verification failed; retained disposable database={TEST_DATABASE_NAME}");raise
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
