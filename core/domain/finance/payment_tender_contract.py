"""Typed payment-tender composition and lifecycle commands for M4.4."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping
from uuid import UUID

from .payment_intent_contract import (
    PaymentCommandValidationError, _decimal_text, _fingerprint, _json_object,
    _money, _timestamp, _timestamp_text,
)

CONTRACT_CODE="XBOS_M44_SUPPORTED_PAYMENT_PATTERNS"
CONTRACT_VERSION=1
PaymentTenderValidationError=PaymentCommandValidationError
_METHOD=re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CODE=re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


def _identity(command):
    for name in ("source_component","source_record_id","idempotency_scope","idempotency_key"):
        object.__setattr__(command,name,str(getattr(command,name)).strip())
    object.__setattr__(command,"actor_service",str(command.actor_service).strip() if command.actor_service else None)


def _common(command):
    if command.tenant_id<=0 or command.organization_unit_id<=0: raise PaymentTenderValidationError("invalid_scope","tenant and organization must be positive")
    if command.calendar_policy_version<=0: raise PaymentTenderValidationError("invalid_calendar_version","calendar version must be positive")
    if command.actor_user_id is None and not command.actor_service: raise PaymentTenderValidationError("actor_required","an actor is required")
    if not all((command.source_component,command.source_record_id,command.idempotency_scope,command.idempotency_key)):
        raise PaymentTenderValidationError("missing_command_identity","source and idempotency identity are required")


@dataclass(frozen=True)
class CreatePaymentTenderCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_intent_public_id: UUID
    tender_number: int
    tender_amount: Any
    currency_code: str
    payment_method_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    instrument_reference: str | None=None
    actor_user_id: int | None=None
    actor_service: str | None=None
    metadata: Mapping[str,Any]=field(default_factory=dict)

    def __post_init__(self):
        for name in ("public_id","payment_intent_public_id","correlation_id"): object.__setattr__(self,name,UUID(str(getattr(self,name))))
        object.__setattr__(self,"tender_amount",_money(self.tender_amount,"tender_amount"))
        object.__setattr__(self,"currency_code",str(self.currency_code).strip().upper())
        object.__setattr__(self,"payment_method_code",str(self.payment_method_code).strip().lower())
        object.__setattr__(self,"instrument_reference",self.instrument_reference.strip() if self.instrument_reference else None)
        object.__setattr__(self,"occurred_at",_timestamp(self.occurred_at,"occurred_at"))
        object.__setattr__(self,"metadata",_json_object(self.metadata,"metadata")); _identity(self); _common(self)
        if self.tender_number<=0: raise PaymentTenderValidationError("invalid_tender_number","tender number must be positive")
        if not _METHOD.fullmatch(self.payment_method_code): raise PaymentTenderValidationError("invalid_payment_method","payment method is invalid")
        if self.instrument_reference and len(self.instrument_reference)>255: raise PaymentTenderValidationError("instrument_reference_too_long","instrument reference exceeds limit")

    def canonical_payload(self):
        return {"schema":CONTRACT_CODE,"schema_version":CONTRACT_VERSION,"command":"create_payment_tender","public_id":str(self.public_id),
            "tenant_id":self.tenant_id,"organization_unit_id":self.organization_unit_id,"payment_intent_public_id":str(self.payment_intent_public_id),
            "tender_number":self.tender_number,"tender_amount":_decimal_text(self.tender_amount),"currency_code":self.currency_code,
            "payment_method_code":self.payment_method_code,"instrument_reference":self.instrument_reference,
            "occurred_at":_timestamp_text(self.occurred_at),"business_date":self.business_date.isoformat(),"calendar_policy_version":self.calendar_policy_version,
            "correlation_id":str(self.correlation_id),"actor_user_id":self.actor_user_id,"actor_service":self.actor_service,
            "source_component":self.source_component,"source_record_id":self.source_record_id,"idempotency_scope":self.idempotency_scope,
            "idempotency_key":self.idempotency_key,"metadata":self.metadata}

    @property
    def request_fingerprint(self): return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class TransitionPaymentTenderCommand:
    tenant_id: int
    organization_unit_id: int
    payment_tender_public_id: UUID
    expected_row_version: int
    target_state: str
    reason_code: str
    evidence_payload: Mapping[str,Any]
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    failure_code: str | None=None
    actor_user_id: int | None=None
    actor_service: str | None=None
    metadata: Mapping[str,Any]=field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self,"payment_tender_public_id",UUID(str(self.payment_tender_public_id))); object.__setattr__(self,"correlation_id",UUID(str(self.correlation_id)))
        for name in ("target_state","reason_code"): object.__setattr__(self,name,str(getattr(self,name)).strip().lower())
        object.__setattr__(self,"failure_code",self.failure_code.strip().lower() if self.failure_code else None)
        object.__setattr__(self,"occurred_at",_timestamp(self.occurred_at,"occurred_at")); object.__setattr__(self,"evidence_payload",_json_object(self.evidence_payload,"evidence_payload")); object.__setattr__(self,"metadata",_json_object(self.metadata,"metadata")); _identity(self); _common(self)
        if self.expected_row_version<=0: raise PaymentTenderValidationError("invalid_expected_version","expected version must be positive")
        if self.target_state not in {"processing","partially_succeeded","succeeded","failed","cancelled"}: raise PaymentTenderValidationError("invalid_tender_state","target state is invalid")
        if not _CODE.fullmatch(self.reason_code): raise PaymentTenderValidationError("invalid_reason_code","reason code is invalid")
        if self.target_state=="failed" and (not self.failure_code or not _CODE.fullmatch(self.failure_code)): raise PaymentTenderValidationError("failure_code_required","failed tender requires failure code")
        if self.target_state!="failed" and self.failure_code: raise PaymentTenderValidationError("unexpected_failure_code","failure code only belongs to failed tender")
        if self.target_state in {"partially_succeeded","succeeded","failed"} and not self.evidence_payload: raise PaymentTenderValidationError("tender_evidence_required","result state requires evidence")

    def canonical_payload(self):
        return {"schema":CONTRACT_CODE,"schema_version":CONTRACT_VERSION,"command":"transition_payment_tender","tenant_id":self.tenant_id,
            "organization_unit_id":self.organization_unit_id,"payment_tender_public_id":str(self.payment_tender_public_id),"expected_row_version":self.expected_row_version,
            "target_state":self.target_state,"reason_code":self.reason_code,"failure_code":self.failure_code,"evidence_payload":self.evidence_payload,
            "occurred_at":_timestamp_text(self.occurred_at),"business_date":self.business_date.isoformat(),"calendar_policy_version":self.calendar_policy_version,
            "correlation_id":str(self.correlation_id),"actor_user_id":self.actor_user_id,"actor_service":self.actor_service,
            "source_component":self.source_component,"source_record_id":self.source_record_id,"idempotency_scope":self.idempotency_scope,"idempotency_key":self.idempotency_key,"metadata":self.metadata}

    @property
    def request_fingerprint(self): return _fingerprint(self.canonical_payload())
