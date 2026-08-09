"""Persistence for M4.4 governed tender composition."""

from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any,Mapping
from uuid import UUID
from sqlalchemy import text
from .payment_tender_contract import CreatePaymentTenderCommand,TransitionPaymentTenderCommand

@dataclass(frozen=True)
class TenderIntentAuthority:
    id:int; public_id:UUID; tenant_id:int; organization_unit_id:int; intent_state:str; requested_amount:Decimal; currency_code:str; payment_method_policy:Mapping[str,Any]; expires_at:datetime|None

@dataclass(frozen=True)
class PaymentTenderRecord:
    id:int; public_id:UUID; tenant_id:int; organization_unit_id:int; payment_intent_id:int; tender_number:int; tender_state:str; tender_amount:Decimal; currency_code:str; payment_method_code:str; instrument_reference:str|None; terminal_at:datetime|None; failure_code:str|None; evidence_payload:Mapping[str,Any]; occurred_at:datetime; row_version:int; replayed:bool=False

@dataclass(frozen=True)
class PaymentTenderTransitionRecord:
    id:int; public_id:UUID; tenant_id:int; organization_unit_id:int; payment_tender_id:int; sequence_number:int; from_state:str|None; to_state:str; reason_code:str; failure_code:str|None; evidence_payload:Mapping[str,Any]; occurred_at:datetime

_TENDER="id,public_id,tenant_id,organization_unit_id,payment_intent_id,tender_number,tender_state,tender_amount,currency_code,payment_method_code,instrument_reference,terminal_at,failure_code,evidence_payload,occurred_at,row_version"
_TRANSITION="id,public_id,tenant_id,organization_unit_id,payment_tender_id,sequence_number,from_state,to_state,reason_code,failure_code,evidence_payload,occurred_at"

def _tender(row,replayed=False):
    values=dict(row); values["public_id"]=UUID(str(values["public_id"])); values["tender_amount"]=Decimal(values["tender_amount"]); return PaymentTenderRecord(**values,replayed=replayed)
def _transition(row):
    values=dict(row); values["public_id"]=UUID(str(values["public_id"])); return PaymentTenderTransitionRecord(**values)

class PaymentTenderRepository:
    @staticmethod
    def lock_intent(session,tenant_id,public_id):
        row=session.execute(text("SELECT id,public_id,tenant_id,organization_unit_id,intent_state,requested_amount,currency_code,payment_method_policy,expires_at FROM canonical_payment_intents WHERE tenant_id=:t AND public_id=:p FOR UPDATE"),{"t":tenant_id,"p":str(public_id)}).mappings().one_or_none()
        if not row:return None
        values=dict(row); values["public_id"]=UUID(str(values["public_id"])); values["requested_amount"]=Decimal(values["requested_amount"]); return TenderIntentAuthority(**values)
    @staticmethod
    def composition(session,tenant_id,intent_id):
        row=session.execute(text("SELECT count(*)::int AS tender_count,COALESCE(sum(tender_amount),0) AS tender_total FROM canonical_payment_tenders WHERE tenant_id=:t AND payment_intent_id=:i AND tender_state NOT IN ('failed','cancelled')"),{"t":tenant_id,"i":intent_id}).mappings().one(); return int(row["tender_count"]),Decimal(row["tender_total"])
    @staticmethod
    def next_tender_number(session,tenant_id,intent_id):
        return int(session.execute(text("SELECT COALESCE(max(tender_number),0)+1 FROM canonical_payment_tenders WHERE tenant_id=:t AND payment_intent_id=:i"),{"t":tenant_id,"i":intent_id}).scalar_one())
    @staticmethod
    def find_tender(session,tenant_id,public_id,lock=False):
        locking="FOR UPDATE" if lock else ""; row=session.execute(text(f"SELECT {_TENDER} FROM canonical_payment_tenders WHERE tenant_id=:t AND public_id=:p {locking}"),{"t":tenant_id,"p":str(public_id)}).mappings().one_or_none(); return _tender(row) if row else None
    @staticmethod
    def public_id_exists(session,public_id):
        return bool(session.execute(text("SELECT 1 FROM (SELECT public_id FROM canonical_payment_requests WHERE public_id=:p UNION ALL SELECT public_id FROM canonical_payment_intents WHERE public_id=:p UNION ALL SELECT public_id FROM canonical_payment_tenders WHERE public_id=:p UNION ALL SELECT public_id FROM canonical_payment_attempts WHERE public_id=:p UNION ALL SELECT public_id FROM payment_settlements WHERE public_id=:p) ids LIMIT 1"),{"p":str(public_id)}).scalar_one_or_none())
    @staticmethod
    def insert_tender(session,command,intent_id):
        row=session.execute(text(f"INSERT INTO canonical_payment_tenders(public_id,tenant_id,organization_unit_id,payment_intent_id,tender_number,tender_state,tender_amount,currency_code,payment_method_code,instrument_reference,occurred_at,business_date,calendar_policy_version,correlation_id,actor_user_id,actor_service,source_component,source_record_id,metadata) VALUES(:public_id,:tenant_id,:organization_unit_id,:intent_id,:tender_number,'pending',:tender_amount,:currency_code,:payment_method_code,:instrument_reference,:occurred_at,:business_date,:calendar_policy_version,:correlation_id,:actor_user_id,:actor_service,:source_component,:source_record_id,CAST(:metadata AS JSONB)) RETURNING {_TENDER}"),{**command.canonical_payload(),"public_id":str(command.public_id),"intent_id":intent_id,"tender_amount":command.tender_amount,"correlation_id":str(command.correlation_id),"metadata":json.dumps(command.metadata,sort_keys=True)}).mappings().one(); return _tender(row)
    @staticmethod
    def insert_transition(session,tender,command):
        row=session.execute(text(f"INSERT INTO payment_tender_transitions(tenant_id,organization_unit_id,payment_tender_id,sequence_number,from_state,to_state,reason_code,failure_code,evidence_payload,occurred_at,business_date,calendar_policy_version,correlation_id,actor_user_id,actor_service,source_component,source_record_id,metadata) VALUES(:tenant_id,:organization_unit_id,:id,:sequence,:from_state,:target_state,:reason_code,:failure_code,CAST(:evidence AS JSONB),:occurred_at,:business_date,:calendar_policy_version,:correlation_id,:actor_user_id,:actor_service,:source_component,:source_record_id,CAST(:metadata AS JSONB)) RETURNING {_TRANSITION}"),{**command.canonical_payload(),"id":tender.id,"sequence":tender.row_version+1,"from_state":tender.tender_state,"evidence":json.dumps(command.evidence_payload,sort_keys=True),"correlation_id":str(command.correlation_id),"metadata":json.dumps(command.metadata,sort_keys=True)}).mappings().one(); return _transition(row)
    @staticmethod
    def apply_transition(session,tender,command):
        terminal=command.occurred_at if command.target_state in {"succeeded","failed","cancelled"} else None
        row=session.execute(text(f"UPDATE canonical_payment_tenders SET tender_state=:target_state,terminal_at=:terminal,failure_code=:failure_code,evidence_payload=CAST(:evidence AS JSONB),row_version=row_version+1,updated_at=now() WHERE id=:id AND tenant_id=:tenant_id AND row_version=:expected_row_version AND tender_state=:from_state RETURNING {_TENDER}"),{**command.canonical_payload(),"id":tender.id,"from_state":tender.tender_state,"terminal":terminal,"evidence":json.dumps(command.evidence_payload,sort_keys=True)}).mappings().one_or_none(); return _tender(row) if row else None
    @staticmethod
    def find_transition(session,public_id):
        row=session.execute(text(f"SELECT {_TRANSITION} FROM payment_tender_transitions WHERE public_id=:p"),{"p":str(public_id)}).mappings().one_or_none(); return _transition(row) if row else None
