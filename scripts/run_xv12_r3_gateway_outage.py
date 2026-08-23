"""Prove Gateway API outage and replay-safe recovery using one stable XBOS attempt identity."""
from __future__ import annotations
import json,os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import UUID,uuid4
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from sqlalchemy import text
from database import SessionLocal
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.integrations.xafpay_v2.client import XafPayV2Client
from core.integrations.xafpay_v2.contract import XafPayV2IntegrationError
from core.integrations.xafpay_v2.service import XafPayV2Service

def req(n):
 v=os.environ.get(n,'').strip()
 if not v: raise RuntimeError(f'XV12_R3_CONFIG:{n}')
 return v

def main():
 mode=sys.argv[1] if len(sys.argv)>1 else ''; path=Path(req('XV12_R3_GATEWAY_OUTAGE_STATE_FILE'))
 if mode=='prepare':
  now=datetime.now(timezone.utc);intent_id=uuid4();attempt_id=uuid4();cor=uuid4();amount=1700
  with SessionLocal() as session:
   with session.begin():
    scope=session.execute(text("SELECT t.id tenant_id,ou.id organization_unit_id FROM tenants t JOIN organization_units ou ON ou.tenant_id=t.id WHERE t.code='XAFPAYXV12' ORDER BY ou.id LIMIT 1")).mappings().one();tenant=int(scope['tenant_id']);org=int(scope['organization_unit_id'])
    intent=TransactionalPaymentIntentEngine.create_intent(session,CreatePaymentIntentCommand(public_id=intent_id,tenant_id=tenant,organization_unit_id=org,requested_amount=amount,currency_code='XAF',payment_method_policy={'allowed_methods':['mobile_money'],'allow_mixed_tender':False,'max_tenders':1},occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=cor,actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.outage',source_record_id=str(intent_id),idempotency_scope='xafpay_v2.r3.outage.intent',idempotency_key=str(intent_id),metadata={'xv12':True})).payment_intent
    TransactionalPaymentAttemptEngine.create(session,CreatePaymentAttemptCommand(public_id=attempt_id,tenant_id=tenant,organization_unit_id=org,payment_intent_public_id=intent.public_id,attempted_amount=amount,currency_code='XAF',payment_method_code='mobile_money',payment_rail_code='mtn_momo',orchestrator_code='xafpay',occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=cor,timeout_at=now+timedelta(minutes=30),actor_service='xbos.xafpay_v2',source_component='xbos.xafpay_v2.r3.outage',source_record_id=str(attempt_id),idempotency_scope='xafpay_v2.r3.outage.attempt',idempotency_key=str(attempt_id),metadata={'xv12':True}))
  path.write_text(json.dumps({'tenant_id':tenant,'organization_unit_id':org,'intent_public_id':str(intent_id),'attempt_public_id':str(attempt_id),'amount_minor':amount,'external_reference':f'xbos:pay:{attempt_id}'},indent=2,sort_keys=True),encoding='utf-8');print('XV12_13_XAFPAY_OUTAGE_STABLE_ATTEMPT_PREPARED=PASS');return
 state=json.loads(path.read_text(encoding='utf-8')); attempt_id=UUID(state['attempt_public_id'])
 with SessionLocal() as session:
  if mode=='down':
   try:
    with session.begin(): XafPayV2Service.initiate_attempt(session,attempt_public_id=attempt_id,client=XafPayV2Client(req('XAFPAY_V2_GATEWAY_BASE_URL'),req('XAFPAY_V2_SERVICE_CREDENTIAL'),timeout_seconds=2))
   except XafPayV2IntegrationError as exc:
    if exc.code!='gateway_transport_error': raise
   else: raise RuntimeError('XV12_13_GATEWAY_OUTAGE_UNEXPECTED_SUCCESS')
   snap=XafPayV2Service.repository.snapshot_for_attempt(session,attempt_id)
   if snap['attempt_state']!='pending' or snap['external_attempt_reference'] is not None: raise RuntimeError(f'XV12_13_GATEWAY_OUTAGE_MUTATED_ATTEMPT:{snap}')
   print('XV12_13_XAFPAY_OUTAGE_PRESERVED_STABLE_ATTEMPT=PASS');return
  if mode=='recover':
   with session.begin(): response=XafPayV2Service.initiate_attempt(session,attempt_public_id=attempt_id,client=XafPayV2Client(req('XAFPAY_V2_GATEWAY_BASE_URL'),req('XAFPAY_V2_SERVICE_CREDENTIAL')))
   count=session.execute(text('SELECT count(*) FROM canonical_payment_attempts WHERE public_id=:p'),{'p':str(attempt_id)}).scalar_one()
   if int(count)!=1: raise RuntimeError('XV12_13_BLIND_XBOS_ATTEMPT_RETRY')
   state.update({'gateway_payment_id':response.payment_id,'gateway_status':response.status});path.write_text(json.dumps(state,indent=2,sort_keys=True),encoding='utf-8');print('XV12_13_XAFPAY_OUTAGE_RECOVERY_CREATE=PASS');return
 raise RuntimeError('usage: run_xv12_r3_gateway_outage.py prepare|down|recover')
if __name__=='__main__':main()
