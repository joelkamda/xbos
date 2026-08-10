"""Typed M4.6 provider fee, reserve and adjustment commands."""
from __future__ import annotations
import hashlib,json,re
from dataclasses import dataclass,field
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from typing import Any,Mapping
from uuid import UUID

COMPONENT_TYPES=frozenset({"provider_fee","reserve_hold","reserve_release","chargeback_loss"})
_CODE=re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_LIMIT=Decimal("10000000000000000")

class ProviderFinancialValidationError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code
class ProviderFinancialIdempotencyConflict(ProviderFinancialValidationError):pass

def _money(value):
    try:selected=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc:raise ProviderFinancialValidationError("invalid_amount","amount is invalid") from exc
    if not selected.is_finite() or selected<=0 or selected>=_LIMIT or selected.as_tuple().exponent < -8:raise ProviderFinancialValidationError("invalid_amount","amount must be positive and fit NUMERIC(24,8)")
    return selected.quantize(Decimal("0.00000001"))
def _time(value,name):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:raise ProviderFinancialValidationError("timezone_required",f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
def _json(value,name):
    if not isinstance(value,Mapping):raise ProviderFinancialValidationError("invalid_json_object",f"{name} must be an object")
    try:selected=json.loads(json.dumps(value,sort_keys=True,allow_nan=False))
    except (TypeError,ValueError) as exc:raise ProviderFinancialValidationError("invalid_json_value",f"{name} is invalid") from exc
    return selected
def _decimal_text(value):
    rendered=format(value.normalize(),"f");return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
def _timestamp_text(value):return value.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

@dataclass(frozen=True)
class CreateProviderSettlementComponentCommand:
    public_id:UUID
    tenant_id:int
    organization_unit_id:int
    payment_settlement_public_id:UUID
    provider_account_public_id:UUID
    component_type:str
    classification_code:str
    amount:Any
    currency_code:str
    provider_event_reference:str
    value_date:date
    evidence_payload:Mapping[str,Any]
    occurred_at:datetime
    business_date:date
    calendar_policy_version:int
    correlation_id:UUID
    source_component:str
    source_record_id:str
    idempotency_scope:str
    idempotency_key:str
    original_component_public_id:UUID|None=None
    actor_user_id:int|None=None
    actor_service:str|None=None
    metadata:Mapping[str,Any]=field(default_factory=dict)

    def __post_init__(self):
        for name in ("public_id","payment_settlement_public_id","provider_account_public_id","correlation_id"):
            object.__setattr__(self,name,UUID(str(getattr(self,name))))
        if self.original_component_public_id is not None:object.__setattr__(self,"original_component_public_id",UUID(str(self.original_component_public_id)))
        object.__setattr__(self,"component_type",str(self.component_type).strip().lower())
        object.__setattr__(self,"classification_code",str(self.classification_code).strip().lower())
        object.__setattr__(self,"currency_code",str(self.currency_code).strip().upper())
        object.__setattr__(self,"provider_event_reference",str(self.provider_event_reference).strip())
        object.__setattr__(self,"amount",_money(self.amount));object.__setattr__(self,"occurred_at",_time(self.occurred_at,"occurred_at"))
        object.__setattr__(self,"evidence_payload",_json(self.evidence_payload,"evidence_payload"));object.__setattr__(self,"metadata",_json(self.metadata,"metadata"))
        for name in ("source_component","source_record_id","idempotency_scope","idempotency_key"):
            object.__setattr__(self,name,str(getattr(self,name)).strip())
        object.__setattr__(self,"actor_service",str(self.actor_service).strip() if self.actor_service else None)
        if self.tenant_id<=0 or self.organization_unit_id<=0 or self.calendar_policy_version<=0:raise ProviderFinancialValidationError("invalid_scope","tenant organization and calendar version must be positive")
        if not isinstance(self.value_date,date) or isinstance(self.value_date,datetime):raise ProviderFinancialValidationError("invalid_value_date","value_date must be a date")
        if not isinstance(self.business_date,date) or isinstance(self.business_date,datetime):raise ProviderFinancialValidationError("invalid_business_date","business_date must be a date")
        if self.component_type not in COMPONENT_TYPES:raise ProviderFinancialValidationError("invalid_component_type","provider component type is invalid")
        if not _CODE.fullmatch(self.classification_code):raise ProviderFinancialValidationError("invalid_classification","classification code is invalid")
        if self.component_type!="provider_fee" and self.classification_code!=self.component_type:raise ProviderFinancialValidationError("classification_mismatch","adjustment classification must equal component type")
        if self.component_type=="reserve_release" and self.original_component_public_id is None:raise ProviderFinancialValidationError("original_hold_required","reserve release requires original hold")
        if self.component_type!="reserve_release" and self.original_component_public_id is not None:raise ProviderFinancialValidationError("original_component_forbidden","only reserve release links an original component")
        if not re.fullmatch(r"[A-Z]{3,12}",self.currency_code):raise ProviderFinancialValidationError("invalid_currency","currency code is invalid")
        if not self.provider_event_reference or len(self.provider_event_reference)>255:raise ProviderFinancialValidationError("invalid_provider_reference","provider event reference is required")
        if not self.evidence_payload:raise ProviderFinancialValidationError("evidence_required","provider component requires evidence")
        if self.actor_user_id is None and not self.actor_service:raise ProviderFinancialValidationError("actor_required","actor is required")
        if not all((self.source_component,self.source_record_id,self.idempotency_scope,self.idempotency_key)):raise ProviderFinancialValidationError("command_identity_required","source and idempotency identities are required")
        if len(self.source_component)>120 or len(self.source_record_id)>191 or len(self.idempotency_scope)>80 or len(self.idempotency_key)>200:raise ProviderFinancialValidationError("command_identity_too_long","command identity exceeds storage limit")

    def canonical_payload(self):
        return {"schema":"XBOS_M46_PROVIDER_FINANCIALS","schema_version":1,"public_id":str(self.public_id),"tenant_id":self.tenant_id,"organization_unit_id":self.organization_unit_id,"payment_settlement_public_id":str(self.payment_settlement_public_id),"provider_account_public_id":str(self.provider_account_public_id),"original_component_public_id":str(self.original_component_public_id) if self.original_component_public_id else None,"component_type":self.component_type,"classification_code":self.classification_code,"amount":_decimal_text(self.amount),"currency_code":self.currency_code,"provider_event_reference":self.provider_event_reference,"value_date":self.value_date.isoformat(),"evidence_payload":self.evidence_payload,"occurred_at":_timestamp_text(self.occurred_at),"business_date":self.business_date.isoformat(),"calendar_policy_version":self.calendar_policy_version,"correlation_id":str(self.correlation_id),"actor_user_id":self.actor_user_id,"actor_service":self.actor_service,"source_component":self.source_component,"source_record_id":self.source_record_id,"idempotency_scope":self.idempotency_scope,"idempotency_key":self.idempotency_key,"metadata":self.metadata}
    @property
    def request_fingerprint(self):return hashlib.sha256(json.dumps(self.canonical_payload(),sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    @property
    def evidence_hash(self):return hashlib.sha256(json.dumps(self.evidence_payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
