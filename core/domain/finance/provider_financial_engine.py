"""Atomic component, canonical event, outbox and journal orchestration."""
from __future__ import annotations
from dataclasses import dataclass,replace
from uuid import NAMESPACE_URL,UUID,uuid5
from .atomic_posting_engine import AtomicPostedFinancialEventEngine,PostedFinancialEventResult
from .event_contract import CanonicalFinancialEventCommand
from .provider_financial_contract import CreateProviderSettlementComponentCommand,ProviderFinancialIdempotencyConflict,ProviderFinancialValidationError
from .provider_financial_repository import ProviderFinancialRepository,ProviderSettlementComponentRecord

_PROFILES={"provider_fee":("PROVIDER_FEE_RECOGNIZED","recognition","provider_fee"),"reserve_hold":("PROVIDER_SETTLEMENT_ADJUSTED","correction","provider_reserve_hold"),"reserve_release":("PROVIDER_SETTLEMENT_ADJUSTED","correction","provider_reserve_release"),"chargeback_loss":("PROVIDER_SETTLEMENT_ADJUSTED","correction","provider_chargeback_loss")}

@dataclass(frozen=True)
class ProviderFinancialResult:
    component:ProviderSettlementComponentRecord
    posted_financial_event:PostedFinancialEventResult
    replayed:bool

class TransactionalProviderFinancialEngine:
    repository=ProviderFinancialRepository
    @classmethod
    def create(cls,session,command:CreateProviderSettlementComponentCommand):
        with session.begin_nested():
            existing=cls.repository.find_by_idempotency(session,command)
            if existing:
                if existing.request_fingerprint!=command.request_fingerprint:raise ProviderFinancialIdempotencyConflict("idempotency_conflict","component idempotency identity has different content")
                if existing.source_record_authority_id is None:raise ProviderFinancialValidationError("source_authority_missing","existing component lacks source authority")
                posted=AtomicPostedFinancialEventEngine.emit_and_post(session,cls._event(command,existing,existing.source_record_authority_id))
                return ProviderFinancialResult(existing,posted,True)
            if cls.repository.public_id_exists(session,command.public_id):raise ProviderFinancialValidationError("public_id_conflict","provider component public id already exists")
            settlement=cls.repository.settlement_authority(session,tenant_id=command.tenant_id,public_id=command.payment_settlement_public_id,lock=True)
            if settlement is None:raise ProviderFinancialValidationError("settlement_not_found","external settlement authority does not exist")
            if settlement["organization_unit_id"]!=command.organization_unit_id or settlement["currency_code"]!=command.currency_code:raise ProviderFinancialValidationError("settlement_scope_mismatch","settlement scope or currency differs")
            if settlement["settlement_state"]!="confirmed" or not settlement["provider_active"]:raise ProviderFinancialValidationError("settlement_not_eligible","confirmed settlement and active provider are required")
            if UUID(str(settlement["provider_account_public_id"]))!=command.provider_account_public_id:raise ProviderFinancialValidationError("provider_account_mismatch","provider account differs from settlement attempt")
            original_id=None
            if command.original_component_public_id:
                original=cls.repository.find_component(session,tenant_id=command.tenant_id,public_id=command.original_component_public_id,lock=True)
                if original is None or original.component_type!="reserve_hold" or original.payment_settlement_id!=settlement["id"] or original.provider_account_id!=settlement["provider_account_id"]:raise ProviderFinancialValidationError("original_hold_mismatch","reserve release original does not match settlement authority")
                original_id=original.id
            component=cls.repository.insert(session,command,settlement=settlement,original_id=original_id)
            source_id=cls.repository.register_source(session,component)
            component=replace(component,source_record_authority_id=source_id)
            posted=AtomicPostedFinancialEventEngine.emit_and_post(session,cls._event(command,component,source_id))
            return ProviderFinancialResult(component,posted,False)
    @staticmethod
    def _event(command,component,source_id):
        event_type,economic_role,profile=_PROFILES[command.component_type]
        classification={"provider_fee_type":{"code":command.classification_code}} if command.component_type=="provider_fee" else {"provider_adjustment_class":{"code":command.component_type}}
        return CanonicalFinancialEventCommand(public_id=uuid5(NAMESPACE_URL,f"xbos:m46:event:{command.tenant_id}:{component.public_id}"),tenant_id=command.tenant_id,organization_unit_id=command.organization_unit_id,event_type_code=event_type,event_version=1,amount=command.amount,currency_code=command.currency_code,economic_role=economic_role,source_operational_account_id=component.operational_account_id,target_operational_account_id=None,source_record_id=source_id,occurred_at=command.occurred_at,business_date=command.business_date,calendar_policy_version=command.calendar_policy_version,idempotency_scope=f"m46.{command.component_type}",idempotency_key=str(component.public_id),correlation_id=command.correlation_id,classification_snapshot=classification,posting_context={"posting_profile_code":profile},metadata={"provider_component_public_id":str(component.public_id),"provider_event_reference":command.provider_event_reference},actor_user_id=command.actor_user_id,actor_service=command.actor_service,evidence_hash=command.evidence_hash)
