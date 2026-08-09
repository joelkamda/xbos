"""Typed payment-attempt commands and append-only transition evidence for M4.2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
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


CONTRACT_CODE = "XBOS_M42_TRANSACTIONAL_PAYMENT_ATTEMPTS"
CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_ROUTING_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "expired"})
TRANSITION_STATES = frozenset(
    {"processing", "requires_action", "authorized", *TERMINAL_STATES}
)


PaymentAttemptValidationError = PaymentCommandValidationError


def _identity(command) -> None:
    for name in ("source_component", "source_record_id", "idempotency_scope", "idempotency_key"):
        object.__setattr__(command, name, str(getattr(command, name)).strip())
    object.__setattr__(
        command,
        "actor_service",
        str(command.actor_service).strip() if command.actor_service else None,
    )


def _common(command) -> None:
    if command.tenant_id <= 0 or command.organization_unit_id <= 0:
        raise PaymentAttemptValidationError("invalid_scope", "tenant and organization must be positive")
    if command.calendar_policy_version <= 0:
        raise PaymentAttemptValidationError("invalid_calendar_version", "calendar version must be positive")
    if command.actor_user_id is None and not command.actor_service:
        raise PaymentAttemptValidationError("actor_required", "a user or service actor is required")
    if not all(
        (command.source_component, command.source_record_id, command.idempotency_scope, command.idempotency_key)
    ):
        raise PaymentAttemptValidationError("missing_command_identity", "source and idempotency identities are required")
    if len(command.source_component) > 120 or len(command.source_record_id) > 191:
        raise PaymentAttemptValidationError("command_identity_too_long", "source identity exceeds storage limit")
    if len(command.idempotency_scope) > 80 or len(command.idempotency_key) > 200:
        raise PaymentAttemptValidationError("command_identity_too_long", "idempotency identity exceeds storage limit")


@dataclass(frozen=True)
class CreatePaymentAttemptCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_intent_public_id: UUID
    attempted_amount: Any
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    orchestrator_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    payment_tender_public_id: UUID | None = None
    provider_account_public_id: UUID | None = None
    underlying_provider_code: str | None = None
    external_attempt_reference: str | None = None
    retry_of_attempt_public_id: UUID | None = None
    timeout_at: datetime | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("public_id", "payment_intent_public_id", "correlation_id"):
            object.__setattr__(self, name, UUID(str(getattr(self, name))))
        for name in ("payment_tender_public_id", "provider_account_public_id", "retry_of_attempt_public_id"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, UUID(str(getattr(self, name))))
        object.__setattr__(self, "attempted_amount", _money(self.attempted_amount, "attempted_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        for name in ("payment_method_code", "payment_rail_code", "orchestrator_code"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().lower())
        if self.underlying_provider_code is not None:
            object.__setattr__(self, "underlying_provider_code", self.underlying_provider_code.strip().lower())
        if self.external_attempt_reference is not None:
            object.__setattr__(self, "external_attempt_reference", self.external_attempt_reference.strip())
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        if self.timeout_at is not None:
            object.__setattr__(self, "timeout_at", _timestamp(self.timeout_at, "timeout_at"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _identity(self)
        _common(self)
        if not _CURRENCY.fullmatch(self.currency_code):
            raise PaymentAttemptValidationError("invalid_currency", "currency code must be three uppercase letters")
        for name in ("payment_method_code", "payment_rail_code", "orchestrator_code"):
            if not _ROUTING_CODE.fullmatch(getattr(self, name)):
                raise PaymentAttemptValidationError("invalid_routing_code", f"{name} is invalid")
        if self.underlying_provider_code and not _ROUTING_CODE.fullmatch(self.underlying_provider_code):
            raise PaymentAttemptValidationError("invalid_provider_code", "underlying provider code is invalid")
        if self.underlying_provider_code and self.provider_account_public_id is None:
            raise PaymentAttemptValidationError(
                "provider_account_required", "an underlying provider requires a provider account authority"
            )
        if self.external_attempt_reference == "":
            raise PaymentAttemptValidationError("empty_external_reference", "external attempt reference cannot be blank")
        if self.external_attempt_reference and len(self.external_attempt_reference) > 255:
            raise PaymentAttemptValidationError("external_reference_too_long", "external attempt reference exceeds storage limit")
        if self.timeout_at is not None and self.timeout_at <= self.occurred_at:
            raise PaymentAttemptValidationError("invalid_timeout", "timeout must follow attempt occurrence")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "command": "create_payment_attempt",
            "public_id": str(self.public_id),
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "payment_intent_public_id": str(self.payment_intent_public_id),
            "payment_tender_public_id": str(self.payment_tender_public_id) if self.payment_tender_public_id else None,
            "attempted_amount": _decimal_text(self.attempted_amount),
            "currency_code": self.currency_code,
            "payment_method_code": self.payment_method_code,
            "payment_rail_code": self.payment_rail_code,
            "orchestrator_code": self.orchestrator_code,
            "provider_account_public_id": str(self.provider_account_public_id) if self.provider_account_public_id else None,
            "underlying_provider_code": self.underlying_provider_code,
            "external_attempt_reference": self.external_attempt_reference,
            "retry_of_attempt_public_id": str(self.retry_of_attempt_public_id) if self.retry_of_attempt_public_id else None,
            "timeout_at": _timestamp_text(self.timeout_at) if self.timeout_at else None,
            "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(),
            "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id),
            "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service,
            "source_component": self.source_component,
            "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class TransitionPaymentAttemptCommand:
    tenant_id: int
    organization_unit_id: int
    payment_attempt_public_id: UUID
    expected_row_version: int
    target_state: str
    reason_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    external_attempt_reference: str | None = None
    failure_code: str | None = None
    evidence_payload: Mapping[str, Any] = field(default_factory=dict)
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payment_attempt_public_id", UUID(str(self.payment_attempt_public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        for name in ("target_state", "reason_code"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().lower())
        if self.failure_code is not None:
            object.__setattr__(self, "failure_code", self.failure_code.strip().lower())
        if self.external_attempt_reference is not None:
            object.__setattr__(self, "external_attempt_reference", self.external_attempt_reference.strip())
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "evidence_payload", _json_object(self.evidence_payload, "evidence_payload"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _identity(self)
        _common(self)
        if self.expected_row_version <= 0:
            raise PaymentAttemptValidationError("invalid_expected_version", "expected row version must be positive")
        if self.target_state not in TRANSITION_STATES:
            raise PaymentAttemptValidationError("invalid_attempt_target_state", "attempt target state is invalid")
        if not _CODE.fullmatch(self.reason_code):
            raise PaymentAttemptValidationError("invalid_reason_code", "reason code is invalid")
        if self.target_state == "failed":
            if not self.failure_code or not _CODE.fullmatch(self.failure_code):
                raise PaymentAttemptValidationError("failure_code_required", "failed attempt requires a failure code")
        elif self.failure_code is not None:
            raise PaymentAttemptValidationError("unexpected_failure_code", "failure code is only valid for failed attempts")
        if self.external_attempt_reference == "":
            raise PaymentAttemptValidationError("empty_external_reference", "external attempt reference cannot be blank")
        if self.external_attempt_reference and len(self.external_attempt_reference) > 255:
            raise PaymentAttemptValidationError("external_reference_too_long", "external attempt reference exceeds storage limit")
        if self.target_state in {"succeeded", "failed", "expired"} and not self.evidence_payload:
            raise PaymentAttemptValidationError("terminal_evidence_required", "terminal attempt requires evidence")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "command": "transition_payment_attempt",
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "payment_attempt_public_id": str(self.payment_attempt_public_id),
            "expected_row_version": self.expected_row_version,
            "target_state": self.target_state,
            "reason_code": self.reason_code,
            "external_attempt_reference": self.external_attempt_reference,
            "failure_code": self.failure_code,
            "evidence_payload": self.evidence_payload,
            "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(),
            "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id),
            "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service,
            "source_component": self.source_component,
            "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())
