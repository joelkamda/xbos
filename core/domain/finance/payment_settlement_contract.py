"""Typed settlement, terminal-evidence, and reversal commands for M4.3."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .payment_intent_contract import (
    PaymentCommandValidationError,
    _decimal_text,
    _fingerprint,
    _json_object,
    _money,
    _timestamp,
    _timestamp_text,
)


CONTRACT_CODE = "XBOS_M43_TRANSACTIONAL_PAYMENT_SETTLEMENTS"
CONTRACT_VERSION = 1
PaymentSettlementValidationError = PaymentCommandValidationError
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_ROUTING = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_QUANTUM = Decimal("0.00000001")
_LIMIT = Decimal("10000000000000000")


def _identity(command) -> None:
    for name in ("source_component", "source_record_id", "idempotency_scope", "idempotency_key"):
        object.__setattr__(command, name, str(getattr(command, name)).strip())
    object.__setattr__(command, "actor_service", str(command.actor_service).strip() if command.actor_service else None)


def _common(command) -> None:
    if command.tenant_id <= 0 or command.organization_unit_id <= 0:
        raise PaymentSettlementValidationError("invalid_scope", "tenant and organization must be positive")
    if command.calendar_policy_version <= 0:
        raise PaymentSettlementValidationError("invalid_calendar_version", "calendar version must be positive")
    if command.actor_user_id is None and not command.actor_service:
        raise PaymentSettlementValidationError("actor_required", "a user or service actor is required")
    if not all((command.source_component, command.source_record_id, command.idempotency_scope, command.idempotency_key)):
        raise PaymentSettlementValidationError("missing_command_identity", "source and idempotency identities are required")
    if len(command.source_component) > 120 or len(command.source_record_id) > 191:
        raise PaymentSettlementValidationError("command_identity_too_long", "source identity exceeds storage limit")


def _settlement_money(value: Any, name: str, *, positive: bool, code: str) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentSettlementValidationError(code, f"{name} is invalid") from exc
    if (not selected.is_finite() or selected >= _LIMIT or selected.as_tuple().exponent < -8
            or (selected <= 0 if positive else selected < 0)):
        raise PaymentSettlementValidationError(code, f"{name} is invalid")
    return selected.quantize(_QUANTUM)


@dataclass(frozen=True)
class CreatePaymentSettlementCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_intent_public_id: UUID
    operational_account_public_id: UUID
    settlement_direction: str
    gross_amount: Any
    fee_amount: Any
    net_amount: Any
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    value_date: date
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    payment_attempt_public_id: UUID | None = None
    payment_tender_public_id: UUID | None = None
    provider_callback_event_public_id: UUID | None = None
    external_settlement_reference: str | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("public_id", "payment_intent_public_id", "operational_account_public_id", "correlation_id"):
            object.__setattr__(self, name, UUID(str(getattr(self, name))))
        for name in ("payment_attempt_public_id", "payment_tender_public_id", "provider_callback_event_public_id"):
            value = getattr(self, name)
            object.__setattr__(self, name, UUID(str(value)) if value else None)
        for name in ("settlement_direction", "payment_method_code", "payment_rail_code"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().lower())
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "gross_amount", _settlement_money(self.gross_amount, "gross_amount", positive=True, code="invalid_settlement_amount"))
        object.__setattr__(self, "fee_amount", _settlement_money(self.fee_amount, "fee_amount", positive=False, code="invalid_settlement_amount"))
        object.__setattr__(self, "net_amount", _settlement_money(self.net_amount, "net_amount", positive=False, code="invalid_settlement_amount"))
        if self.external_settlement_reference is not None:
            object.__setattr__(self, "external_settlement_reference", self.external_settlement_reference.strip())
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _identity(self)
        _common(self)
        if self.settlement_direction not in {"incoming", "outgoing"}:
            raise PaymentSettlementValidationError("invalid_settlement_direction", "settlement direction is invalid")
        if self.gross_amount <= 0 or self.fee_amount < 0 or self.net_amount < 0:
            raise PaymentSettlementValidationError("invalid_settlement_amount", "settlement amounts are invalid")
        if self.net_amount != self.gross_amount - self.fee_amount:
            raise PaymentSettlementValidationError("settlement_amount_mismatch", "net amount must equal gross less fee")
        if not _CURRENCY.fullmatch(self.currency_code):
            raise PaymentSettlementValidationError("invalid_currency", "currency must be a three-letter code")
        if not _ROUTING.fullmatch(self.payment_method_code) or not _ROUTING.fullmatch(self.payment_rail_code):
            raise PaymentSettlementValidationError("invalid_settlement_routing", "method or rail code is invalid")
        if self.external_settlement_reference == "":
            raise PaymentSettlementValidationError("empty_provider_identity", "provider transaction identity cannot be blank")
        if self.external_settlement_reference and len(self.external_settlement_reference) > 255:
            raise PaymentSettlementValidationError("provider_identity_too_long", "provider transaction identity exceeds storage limit")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
            "command": "create_payment_settlement", "public_id": str(self.public_id),
            "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "payment_intent_public_id": str(self.payment_intent_public_id),
            "payment_attempt_public_id": str(self.payment_attempt_public_id) if self.payment_attempt_public_id else None,
            "payment_tender_public_id": str(self.payment_tender_public_id) if self.payment_tender_public_id else None,
            "provider_callback_event_public_id": str(self.provider_callback_event_public_id) if self.provider_callback_event_public_id else None,
            "operational_account_public_id": str(self.operational_account_public_id),
            "settlement_direction": self.settlement_direction,
            "gross_amount": _decimal_text(self.gross_amount), "fee_amount": _decimal_text(self.fee_amount),
            "net_amount": _decimal_text(self.net_amount), "currency_code": self.currency_code,
            "payment_method_code": self.payment_method_code, "payment_rail_code": self.payment_rail_code,
            "external_settlement_reference": self.external_settlement_reference,
            "value_date": self.value_date.isoformat(), "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id), "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service, "source_component": self.source_component,
            "source_record_id": self.source_record_id, "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class TransitionPaymentSettlementCommand:
    tenant_id: int
    organization_unit_id: int
    payment_settlement_public_id: UUID
    expected_row_version: int
    target_state: str
    finality_status: str
    availability_state: str
    reason_code: str
    evidence_payload: Mapping[str, Any]
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    external_settlement_reference: str | None = None
    failure_code: str | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payment_settlement_public_id", UUID(str(self.payment_settlement_public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        for name in ("target_state", "finality_status", "availability_state", "reason_code"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().lower())
        if self.failure_code is not None:
            object.__setattr__(self, "failure_code", self.failure_code.strip().lower())
        if self.external_settlement_reference is not None:
            object.__setattr__(self, "external_settlement_reference", self.external_settlement_reference.strip())
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "evidence_payload", _json_object(self.evidence_payload, "evidence_payload"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _identity(self); _common(self)
        if self.expected_row_version <= 0:
            raise PaymentSettlementValidationError("invalid_expected_version", "expected version must be positive")
        if self.target_state not in {"confirmed", "failed"}:
            raise PaymentSettlementValidationError("invalid_settlement_target_state", "only confirmation or failure is command-driven")
        if not _CODE.fullmatch(self.reason_code):
            raise PaymentSettlementValidationError("invalid_reason_code", "reason code is invalid")
        if not self.evidence_payload:
            raise PaymentSettlementValidationError("settlement_evidence_required", "terminal settlement evidence is required")
        if self.target_state == "failed":
            if not self.failure_code or not _CODE.fullmatch(self.failure_code):
                raise PaymentSettlementValidationError("failure_code_required", "failed settlement requires failure code")
            if self.finality_status != "rejected" or self.availability_state != "unavailable":
                raise PaymentSettlementValidationError("invalid_failure_disposition", "failed settlement must be rejected and unavailable")
        elif self.failure_code is not None:
            raise PaymentSettlementValidationError("unexpected_failure_code", "failure code is only valid for failed settlement")
        if self.target_state == "confirmed" and self.finality_status != "final":
            raise PaymentSettlementValidationError("confirmation_not_final", "confirmed settlement must be final")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
            "command": "transition_payment_settlement", "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "payment_settlement_public_id": str(self.payment_settlement_public_id),
            "expected_row_version": self.expected_row_version, "target_state": self.target_state,
            "finality_status": self.finality_status, "availability_state": self.availability_state,
            "reason_code": self.reason_code, "failure_code": self.failure_code,
            "external_settlement_reference": self.external_settlement_reference,
            "evidence_payload": self.evidence_payload, "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id), "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service, "source_component": self.source_component,
            "source_record_id": self.source_record_id, "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class ReversePaymentSettlementCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_settlement_public_id: UUID
    reversal_amount: Any
    currency_code: str
    reason_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("public_id", "payment_settlement_public_id", "correlation_id"):
            object.__setattr__(self, name, UUID(str(getattr(self, name))))
        object.__setattr__(self, "reversal_amount", _settlement_money(self.reversal_amount, "reversal_amount", positive=True, code="invalid_reversal_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "reason_code", str(self.reason_code).strip().lower())
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _identity(self); _common(self)
        if self.reversal_amount <= 0:
            raise PaymentSettlementValidationError("invalid_reversal_amount", "reversal amount must be positive")
        if not _CURRENCY.fullmatch(self.currency_code) or not _CODE.fullmatch(self.reason_code):
            raise PaymentSettlementValidationError("invalid_reversal_identity", "reversal currency or reason is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
            "command": "reverse_payment_settlement", "public_id": str(self.public_id),
            "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "payment_settlement_public_id": str(self.payment_settlement_public_id),
            "reversal_amount": _decimal_text(self.reversal_amount), "currency_code": self.currency_code,
            "reason_code": self.reason_code, "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id), "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service, "source_component": self.source_component,
            "source_record_id": self.source_record_id, "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())
