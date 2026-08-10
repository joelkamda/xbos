"""SQL authority for immutable M4.6 provider settlement components."""
from __future__ import annotations
import json
from dataclasses import dataclass,replace
from decimal import Decimal
from uuid import NAMESPACE_URL,UUID,uuid5
from sqlalchemy import text
from .provider_financial_contract import CreateProviderSettlementComponentCommand

@dataclass(frozen=True)
class ProviderSettlementComponentRecord:
    id:int;public_id:UUID;tenant_id:int;organization_unit_id:int;payment_settlement_id:int;provider_account_id:int;operational_account_id:int;original_component_id:int|None;component_type:str;classification_code:str;amount:Decimal;currency_code:str;provider_event_reference:str;value_date:object;evidence_hash:str;evidence_payload:dict;occurred_at:object;request_fingerprint:str;source_record_authority_id:int|None=None;replayed:bool=False

def _record(row,replayed=False):
    values=dict(row);values["public_id"]=UUID(str(values["public_id"]));values["amount"]=Decimal(values["amount"]);return ProviderSettlementComponentRecord(**values,replayed=replayed)

_COLUMNS="""c.id,c.public_id,c.tenant_id,c.organization_unit_id,c.payment_settlement_id,c.provider_account_id,c.operational_account_id,c.original_component_id,c.component_type,c.classification_code,c.amount,c.currency_code,c.provider_event_reference,c.value_date,c.evidence_hash,c.evidence_payload,c.occurred_at,c.request_fingerprint,(SELECT k.id FROM public.kernel_source_records k WHERE k.tenant_id=c.tenant_id AND k.source_component='m46.provider_financials' AND k.aggregate_type=CASE WHEN c.component_type='provider_fee' THEN 'provider_fee' ELSE 'provider_settlement_adjustment' END AND k.aggregate_external_id=c.public_id::text) AS source_record_authority_id"""

class ProviderFinancialRepository:
    @staticmethod
    def settlement_authority(session,*,tenant_id,public_id,lock=False):
        locking="FOR UPDATE OF s" if lock else ""
        return session.execute(text(f"""SELECT s.id,s.public_id,s.tenant_id,s.organization_unit_id,s.payment_intent_id,s.payment_attempt_id,s.operational_account_id,s.settlement_state,s.gross_amount,s.currency_code,s.payment_method_code,s.payment_rail_code,s.occurred_at,a.provider_account_id,p.public_id AS provider_account_public_id,p.active AS provider_active FROM public.payment_settlements s JOIN public.canonical_payment_attempts a ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id JOIN public.payment_provider_accounts p ON p.tenant_id=a.tenant_id AND p.id=a.provider_account_id WHERE s.tenant_id=:tenant_id AND s.public_id=:public_id {locking}"""),{"tenant_id":tenant_id,"public_id":str(public_id)}).mappings().one_or_none()
    @staticmethod
    def find_by_idempotency(session,command):
        row=session.execute(text(f"SELECT {_COLUMNS} FROM public.provider_settlement_components c WHERE c.tenant_id=:tenant AND c.idempotency_scope=:scope AND c.idempotency_key=:key"),{"tenant":command.tenant_id,"scope":command.idempotency_scope,"key":command.idempotency_key}).mappings().one_or_none();return _record(row,True) if row else None
    @staticmethod
    def find_component(session,*,tenant_id,public_id,lock=False):
        locking="FOR UPDATE OF c" if lock else "";row=session.execute(text(f"SELECT {_COLUMNS} FROM public.provider_settlement_components c WHERE c.tenant_id=:tenant AND c.public_id=:public {locking}"),{"tenant":tenant_id,"public":str(public_id)}).mappings().one_or_none();return _record(row) if row else None
    @staticmethod
    def public_id_exists(session,public_id):return bool(session.execute(text("SELECT 1 FROM public.provider_settlement_components WHERE public_id=:public"),{"public":str(public_id)}).scalar_one_or_none())
    @staticmethod
    def insert(session,command,*,settlement,original_id):
        session.execute(text("SELECT set_config('xbos.m46_component_authorized','on',true)"))
        row=session.execute(text(f"""INSERT INTO public.provider_settlement_components(public_id,tenant_id,organization_unit_id,payment_settlement_id,provider_account_id,operational_account_id,original_component_id,component_type,classification_code,amount,currency_code,provider_event_reference,value_date,evidence_hash,evidence_payload,occurred_at,business_date,calendar_policy_version,correlation_id,actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata) VALUES(:public,:tenant,:org,:settlement,:provider,:operational,:original,:component_type,:classification,:amount,:currency,:provider_reference,:value_date,:evidence_hash,CAST(:evidence AS JSONB),:occurred,:business_date,:calendar_version,:correlation,:actor_user,:actor_service,:source_component,:source_record_id,:scope,:key,:fingerprint,CAST(:metadata AS JSONB)) RETURNING id,public_id,tenant_id,organization_unit_id,payment_settlement_id,provider_account_id,operational_account_id,original_component_id,component_type,classification_code,amount,currency_code,provider_event_reference,value_date,evidence_hash,evidence_payload,occurred_at,request_fingerprint,NULL::bigint AS source_record_authority_id"""),{"public":str(command.public_id),"tenant":command.tenant_id,"org":command.organization_unit_id,"settlement":int(settlement["id"]),"provider":int(settlement["provider_account_id"]),"operational":int(settlement["operational_account_id"]),"original":original_id,"component_type":command.component_type,"classification":command.classification_code,"amount":command.amount,"currency":command.currency_code,"provider_reference":command.provider_event_reference,"value_date":command.value_date,"evidence_hash":command.evidence_hash,"evidence":json.dumps(command.evidence_payload,sort_keys=True),"occurred":command.occurred_at,"business_date":command.business_date,"calendar_version":command.calendar_policy_version,"correlation":str(command.correlation_id),"actor_user":command.actor_user_id,"actor_service":command.actor_service,"source_component":command.source_component,"source_record_id":command.source_record_id,"scope":command.idempotency_scope,"key":command.idempotency_key,"fingerprint":command.request_fingerprint,"metadata":json.dumps(command.metadata,sort_keys=True)}).mappings().one()
        session.execute(text("SELECT set_config('xbos.m46_component_authorized','off',true)"))
        return _record(row)
    @staticmethod
    def register_source(session,component):
        aggregate="provider_fee" if component.component_type=="provider_fee" else "provider_settlement_adjustment"
        source_public_id=uuid5(NAMESPACE_URL,f"xbos:m46:source:{component.tenant_id}:{component.public_id}")
        return int(session.execute(text("""INSERT INTO public.kernel_source_records(public_id,tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,aggregate_version,source_occurred_at,metadata) VALUES(:public,:tenant,:org,'m46.provider_financials',:aggregate,:external,'1',:occurred,'{}'::jsonb) ON CONFLICT(tenant_id,source_component,aggregate_type,aggregate_external_id) DO UPDATE SET aggregate_external_id=EXCLUDED.aggregate_external_id RETURNING id"""),{"public":str(source_public_id),"tenant":component.tenant_id,"org":component.organization_unit_id,"aggregate":aggregate,"external":str(component.public_id),"occurred":component.occurred_at}).scalar_one())
    @staticmethod
    def projection(session,*,tenant_id,settlement_public_id):
        return session.execute(text("""SELECT s.public_id,s.gross_amount,s.currency_code,COALESCE(sum(c.amount) FILTER(WHERE c.component_type='provider_fee'),0) AS fee_amount,COALESCE(sum(c.amount) FILTER(WHERE c.component_type='reserve_hold'),0)-COALESCE(sum(c.amount) FILTER(WHERE c.component_type='reserve_release'),0) AS reserve_held,COALESCE(sum(c.amount) FILTER(WHERE c.component_type='chargeback_loss'),0) AS chargeback_loss,s.gross_amount-COALESCE(sum(CASE WHEN c.component_type='reserve_release' THEN -c.amount ELSE c.amount END),0) AS expected_net FROM public.payment_settlements s LEFT JOIN public.provider_settlement_components c ON c.tenant_id=s.tenant_id AND c.payment_settlement_id=s.id WHERE s.tenant_id=:tenant AND s.public_id=:public GROUP BY s.id"""),{"tenant":tenant_id,"public":str(settlement_public_id)}).mappings().one_or_none()
