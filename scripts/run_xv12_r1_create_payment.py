"""Create a neutral XBOS intent/attempt and initiate a real Gateway V2 payment over HTTP."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from uuid import uuid4

from database import SessionLocal
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.integrations.xafpay_v2.client import XafPayV2Client
from core.integrations.xafpay_v2.service import XafPayV2Service
from sqlalchemy import text


def required(name: str) -> str:
    value=os.environ.get(name,"").strip()
    if not value: raise RuntimeError(f"XV12_R1_CONFIG:{name}")
    return value


def main() -> None:
    output=Path(required("XV12_R1_STATE_FILE"))
    amount=int(os.environ.get("XV12_R1_AMOUNT","2500"))
    now=datetime.now(timezone.utc); correlation=uuid4(); intent_id=uuid4(); attempt_id=uuid4()
    with SessionLocal() as session:
        with session.begin():
            row=session.execute(text("""
                SELECT t.id AS tenant_id,ou.id AS organization_unit_id
                FROM public.tenants t JOIN public.organization_units ou ON ou.tenant_id=t.id
                WHERE t.code='XAFPAYXV12' ORDER BY ou.id LIMIT 1
            """)).mappings().one()
            tenant=int(row["tenant_id"]); org=int(row["organization_unit_id"])
            intent=TransactionalPaymentIntentEngine.create_intent(session,CreatePaymentIntentCommand(
                public_id=intent_id,tenant_id=tenant,organization_unit_id=org,requested_amount=amount,
                currency_code="XAF",payment_method_policy={"allowed_methods":["mobile_money"],"allow_mixed_tender":False,"max_tenders":1},
                occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,
                actor_service="xbos.xafpay_v2",source_component="xbos.xafpay_v2.acceptance",source_record_id=str(intent_id),
                idempotency_scope="xafpay_v2.r1.intent",idempotency_key=str(intent_id),metadata={"xv12":True},
            )).payment_intent
            attempt=TransactionalPaymentAttemptEngine.create(session,CreatePaymentAttemptCommand(
                public_id=attempt_id,tenant_id=tenant,organization_unit_id=org,payment_intent_public_id=intent.public_id,
                attempted_amount=amount,currency_code="XAF",payment_method_code="mobile_money",payment_rail_code="mtn_momo",
                orchestrator_code="xafpay",provider_account_public_id=None,underlying_provider_code=None,
                occurred_at=now,business_date=now.date(),calendar_policy_version=1,correlation_id=correlation,
                timeout_at=now+timedelta(minutes=30),actor_service="xbos.xafpay_v2",source_component="xbos.xafpay_v2.acceptance",
                source_record_id=str(attempt_id),idempotency_scope="xafpay_v2.r1.attempt",idempotency_key=str(attempt_id),
                metadata={"xv12":True},
            )).payment_attempt
        # Deliberately perform external initiation after the canonical attempt commits. A lost response is replayable by stable idempotency key.
        with session.begin():
            client=XafPayV2Client(required("XAFPAY_V2_GATEWAY_BASE_URL"),required("XAFPAY_V2_SERVICE_CREDENTIAL"))
            response=XafPayV2Service.initiate_attempt(session,attempt_public_id=attempt.public_id,client=client)
            snap=XafPayV2Service.repository.snapshot_for_attempt(session,attempt.public_id)
            if snap["provider_account_id"] is not None or snap["underlying_provider_code"] is not None:
                raise RuntimeError("XV12_GATEWAY_PROVIDER_AUTHORITY_LEAK")
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({
        "tenant_id":tenant,"organization_unit_id":org,"intent_public_id":str(intent_id),
        "attempt_public_id":str(attempt_id),"gateway_payment_id":response.payment_id,
        "external_reference":response.external_reference,"amount_minor":amount,"gateway_status":response.status,
    },indent=2,sort_keys=True),encoding="utf-8")
    print("XV12_2_CREATE_PAYMENT=PASS")
    print("XV12_12_GATEWAY_PROVIDER_AUTHORITY_ABSENT_FROM_XBOS=PASS")

if __name__=="__main__": main()
