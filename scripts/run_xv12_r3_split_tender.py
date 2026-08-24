"""Create a real mixed-tender XBOS intent and send only its XafPay leg to Gateway V2."""
from __future__ import annotations
import json, os, sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from sqlalchemy import text
from database import SessionLocal
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_tender_contract import CreatePaymentTenderCommand,TransitionPaymentTenderCommand
from core.domain.finance.payment_tender_engine import TransactionalPaymentTenderEngine
from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.integrations.xafpay_v2.client import XafPayV2Client
from core.integrations.xafpay_v2.service import XafPayV2Service

def req(n):
    v=os.environ.get(n,'').strip()
    if not v: raise RuntimeError(f'XV12_R3_CONFIG:{n}')
    return v

def main():
    out=Path(req('XV12_R3_SPLIT_STATE_FILE')); now=datetime.now(timezone.utc); correlation=uuid4(); intent_id=uuid4(); cash_id=uuid4(); xaf_id=uuid4(); attempt_id=uuid4(); total=3000; cash_amount=1000; xaf_amount=2000
    with SessionLocal() as session:
      with session.begin():
        scope=session.execute(text("SELECT t.id tenant_id,ou.id organization_unit_id FROM tenants t JOIN organization_units ou ON ou.tenant_id=t.id WHERE t.code='XAFPAYXV12' ORDER BY ou.id LIMIT 1")).mappings().one(); tenant=int(scope['tenant_id']);org=int(scope['organization_unit_id'])
        intent=TransactionalPaymentIntentEngine.create_intent(session,CreatePaymentIntentCommand(public_id=intent_id,tenant_id=tenant,organization_unit_id=org,requested_amount=total,currency_code='XAF',payment_method_policy={'allowed_methods':['cash','mobile_money'],'allow_mixed_tender':True,'max_tenders':2},occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.split',source_record_id=str(intent_id),idempotency_scope='xafpay_v2.r3.split.intent',idempotency_key=str(intent_id),metadata={'xv12':True})).payment_intent
        cash=TransactionalPaymentTenderEngine.create(session,CreatePaymentTenderCommand(public_id=cash_id,tenant_id=tenant,organization_unit_id=org,payment_intent_public_id=intent.public_id,tender_number=1,tender_amount=cash_amount,currency_code='XAF',payment_method_code='cash',occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.split',source_record_id=str(cash_id),idempotency_scope='xafpay_v2.r3.split.cash',idempotency_key=str(cash_id),metadata={'authority':'XBOS'})).tender
        cash=TransactionalPaymentTenderEngine.transition(session,TransitionPaymentTenderCommand(tenant_id=tenant,organization_unit_id=org,payment_tender_public_id=cash.public_id,expected_row_version=cash.row_version,target_state='succeeded',reason_code='cash_received',evidence_payload={'source':'XBOS','amount':cash_amount},occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.split',source_record_id=str(cash_id),idempotency_scope='xafpay_v2.r3.split.cash.success',idempotency_key=str(cash_id),metadata={'authority':'XBOS'})).tender
        xaf=TransactionalPaymentTenderEngine.create(session,CreatePaymentTenderCommand(public_id=xaf_id,tenant_id=tenant,organization_unit_id=org,payment_intent_public_id=intent.public_id,tender_number=2,tender_amount=xaf_amount,currency_code='XAF',payment_method_code='mobile_money',occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.split',source_record_id=str(xaf_id),idempotency_scope='xafpay_v2.r3.split.xafpay',idempotency_key=str(xaf_id),metadata={'authority':'XBOS','external_leg':'xafpay'})).tender
        attempt=TransactionalPaymentAttemptEngine.create(session,CreatePaymentAttemptCommand(public_id=attempt_id,tenant_id=tenant,organization_unit_id=org,payment_intent_public_id=intent.public_id,payment_tender_public_id=xaf.public_id,attempted_amount=xaf_amount,currency_code='XAF',payment_method_code='mobile_money',payment_rail_code='mtn_momo',orchestrator_code='xafpay',occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,timeout_at=now+timedelta(minutes=30),actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.split',source_record_id=str(attempt_id),idempotency_scope='xafpay_v2.r3.split.attempt',idempotency_key=str(attempt_id),metadata={'xv12':True})).payment_attempt
      with session.begin(): response=XafPayV2Service.initiate_attempt(session,attempt_public_id=attempt.public_id,client=XafPayV2Client(req('XAFPAY_V2_GATEWAY_BASE_URL'),req('XAFPAY_V2_SERVICE_CREDENTIAL')))
    out.write_text(json.dumps({'tenant_id':tenant,'organization_unit_id':org,'intent_public_id':str(intent_id),'cash_tender_public_id':str(cash_id),'xafpay_tender_public_id':str(xaf_id),'attempt_public_id':str(attempt_id),'gateway_payment_id':response.payment_id,'external_reference':response.external_reference,'amount_minor':xaf_amount,'cash_amount_minor':cash_amount,'total_amount_minor':total},indent=2,sort_keys=True),encoding='utf-8')
    print('XV12_11_SPLIT_TENDER_CREATED=PASS')

if __name__=='__main__': main()
