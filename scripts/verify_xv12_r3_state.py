"""Cumulative XV12 R3 XBOS financial/control-total verifier."""
from __future__ import annotations
import json,sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from sqlalchemy import text
from database import SessionLocal
from core.integrations.xafpay_v2.repository import XafPayV2Repository

def main():
    if len(sys.argv)!=3: raise SystemExit('usage: verify_xv12_r3_state.py repair|refund_pending|refund|split|xbos_outage|gateway_recovered state.json')
    mode=sys.argv[1]; state=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')); attempt=UUID(state['attempt_public_id'])
    with SessionLocal() as session:
        snap=XafPayV2Repository.snapshot_for_attempt(session,attempt)
        if snap['tenant_id']!=state['tenant_id'] or snap['organization_unit_id']!=state['organization_unit_id']: raise SystemExit('XV12_R3_SCOPE_CHANGED')
        if snap['provider_account_id'] is not None or snap['underlying_provider_code'] is not None: raise SystemExit('XV12_R3_PROVIDER_AUTHORITY_LEAK')
        if mode in {'repair','xbos_outage','gateway_recovered'}:
            if snap['attempt_state']!='succeeded' or int(snap['confirmed_settlements'])!=1: raise SystemExit(f'XV12_R3_SUCCESS_CONTROL_FAILED:{snap}')
            if mode=='repair': print('XV12_9_REPAIR_XBOS_FINANCIAL_EFFECT=PASS')
            elif mode=='xbos_outage': print('XV12_13_XBOS_OUTAGE_EXACTLY_ONE_EFFECT=PASS')
            else: print('XV12_13_XAFPAY_RECOVERY_EXACTLY_ONE_EFFECT=PASS')
        elif mode in {'refund_pending','refund'}:
            settlement=XafPayV2Repository.settlement_for_attempt(session,tenant_id=int(snap['tenant_id']),attempt_public_id=attempt)
            reversals=XafPayV2Repository.reversal_count_for_attempt(session,tenant_id=int(snap['tenant_id']),attempt_public_id=attempt)
            expected=Decimal(str(state['refund_amount_minor']))
            if mode=='refund_pending':
                if state.get('refund_status')!='PENDING' or snap['attempt_state']!='succeeded' or settlement is None or Decimal(settlement['reversed_amount'])!=0 or settlement['settlement_state']!='confirmed' or reversals!=0: raise SystemExit(f'XV12_10_REFUND_PENDING_CONTROL_FAILED:{settlement}, reversals={reversals}, snap={snap}')
                print('XV12_10_REFUND_REQUEST_NO_CORRECTION=PASS')
            else:
                if snap['attempt_state']!='succeeded' or settlement is None or Decimal(settlement['reversed_amount'])!=expected or settlement['settlement_state']!='partially_reversed' or reversals!=1: raise SystemExit(f'XV12_10_REFUND_CONTROL_FAILED:{settlement}, reversals={reversals}, snap={snap}')
                print('XV12_10_REFUND_CORRECTION_EXACTLY_ONCE=PASS')
        elif mode=='split':
            rows=session.execute(text("""SELECT public_id,tender_number,tender_state,tender_amount,payment_method_code FROM canonical_payment_tenders WHERE public_id IN (:cash,:xaf) ORDER BY tender_number"""),{'cash':state['cash_tender_public_id'],'xaf':state['xafpay_tender_public_id']}).mappings().all()
            if len(rows)!=2: raise SystemExit('XV12_11_TENDER_CARDINALITY_CHANGED')
            cash,xaf=rows
            if str(cash['public_id'])!=state['cash_tender_public_id'] or cash['tender_state']!='succeeded' or Decimal(cash['tender_amount'])!=Decimal(state['cash_amount_minor']) or cash['payment_method_code']!='cash': raise SystemExit(f'XV12_11_CASH_TENDER_CHANGED:{cash}')
            if str(xaf['public_id'])!=state['xafpay_tender_public_id'] or xaf['tender_state']!='succeeded' or Decimal(xaf['tender_amount'])!=Decimal(state['amount_minor']) or xaf['payment_method_code']!='mobile_money': raise SystemExit(f'XV12_11_XAFPAY_TENDER_CHANGED:{xaf}')
            bound=session.execute(text("SELECT t.public_id FROM canonical_payment_attempts a JOIN canonical_payment_tenders t ON t.id=a.payment_tender_id AND t.tenant_id=a.tenant_id WHERE a.public_id=:p"),{'p':str(attempt)}).scalar_one()
            if str(bound)!=state['xafpay_tender_public_id']: raise SystemExit('XV12_11_ATTEMPT_BOUND_TO_WRONG_TENDER')
            if int(snap['confirmed_settlements'])!=1 or Decimal(cash['tender_amount'])+Decimal(xaf['tender_amount'])!=Decimal(state['total_amount_minor']): raise SystemExit('XV12_11_COMPOSITION_CONTROL_FAILED')
            print('XV12_11_NON_XAFPAY_TENDER_REMAINS_XBOS_AUTHORITY=PASS')
            print('XV12_11_SPLIT_TENDER_AUTHORITY=PASS')
        else: raise SystemExit('unknown mode')
    print('XV12_12_TENANT_LOCATION_ISOLATION=PASS')
if __name__=='__main__': main()
