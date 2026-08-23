"""Request a real Gateway V2 partial refund from the already-succeeded R1 XBOS attempt."""
from __future__ import annotations
import json, os, sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from database import SessionLocal
from core.integrations.xafpay_v2.client import XafPayV2Client
from core.integrations.xafpay_v2.service import XafPayV2Service

def required(name):
    value=os.environ.get(name,'').strip()
    if not value: raise RuntimeError(f'XV12_R3_CONFIG:{name}')
    return value

def main():
    base=json.loads(Path(required('XV12_R1_STATE_FILE')).read_text(encoding='utf-8'))
    output=Path(required('XV12_R3_REFUND_STATE_FILE')); amount=Decimal(os.environ.get('XV12_R3_REFUND_AMOUNT','500'))
    with SessionLocal() as session:
        with session.begin():
            response=XafPayV2Service.request_refund(session,attempt_public_id=UUID(base['attempt_public_id']),refund_request_public_id=uuid4(),amount=amount,client=XafPayV2Client(required('XAFPAY_V2_GATEWAY_BASE_URL'),required('XAFPAY_V2_SERVICE_CREDENTIAL')))
    output.write_text(json.dumps({**base,'gateway_refund_id':response.refund_id,'refund_amount_minor':response.amount_minor,'refund_status':response.status},indent=2,sort_keys=True),encoding='utf-8')
    print('XV12_10_REFUND_REQUEST=PASS')

if __name__=='__main__': main()
