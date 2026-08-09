"""Typed provider-neutral payment request and intent commands for M4.1."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID


CONTRACT_CODE = "XBOS_M41_TYPED_PAYMENT_REQUEST_AND_INTENT_COMMANDS"
CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_METHOD = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_QUANTUM = Decimal("0.00000001")
_LIMIT = Decimal("10000000000000000")
_POLICY_KEYS = frozenset({"allowed_methods", "allow_mixed_tender", "max_tenders"})


class PaymentCommandError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PaymentCommandValidationError(PaymentCommandError):
    pass


class PaymentCommandIdempotencyConflict(PaymentCommandError):
    pass


def _money(value: Any, field_name: str) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentCommandValidationError("invalid_money", f"{field_name} must be decimal") from exc
    if (
        not selected.is_finite()
        or selected <= 0
        or selected >= _LIMIT
        or selected.as_tuple().exponent < -8
    ):
        raise PaymentCommandValidationError(
            "invalid_money",
            f"{field_name} must be finite, positive, below NUMERIC(24,8) limit, and use at most eight decimals",
        )
    return selected.quantize(_QUANTUM)


def _timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PaymentCommandValidationError("timezone_required", f"{field_name} must be timezone-aware")
    return value


def _json_object(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PaymentCommandValidationError("invalid_json_object", f"{field_name} must be an object")
    try:
        decoded = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise PaymentCommandValidationError("invalid_json_value", f"{field_name} is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise PaymentCommandValidationError("invalid_json_object", f"{field_name} must be an object")
    return decoded


def _decimal_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_identity(command) -> None:
    for name in ("source_component", "source_record_id", "idempotency_scope", "idempotency_key"):
        object.__setattr__(command, name, str(getattr(command, name)).strip())
    object.__setattr__(
        command,
        "actor_service",
        str(command.actor_service).strip() if command.actor_service else None,
    )


def _validate_common(command) -> None:
    if command.tenant_id <= 0 or command.organization_unit_id <= 0:
        raise PaymentCommandValidationError("invalid_scope", "tenant and organization must be positive")
    if not _CURRENCY.fullmatch(command.currency_code):
        raise PaymentCommandValidationError("invalid_currency", "currency_code must be three uppercase letters")
    if command.calendar_policy_version <= 0:
        raise PaymentCommandValidationError("invalid_calendar_version", "calendar policy version must be positive")
    if command.actor_user_id is None and not command.actor_service:
        raise PaymentCommandValidationError("actor_required", "a user or service actor is required")
    if not all(
        (command.source_component, command.source_record_id, command.idempotency_scope, command.idempotency_key)
    ):
        raise PaymentCommandValidationError("missing_command_identity", "source and idempotency identities are required")
    if command.expires_at is not None and command.expires_at <= command.occurred_at:
        raise PaymentCommandValidationError("invalid_expiry", "expires_at must follow occurred_at")


def normalize_method_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = _json_object(value, "payment_method_policy")
    unknown = set(policy) - _POLICY_KEYS
    if unknown:
        raise PaymentCommandValidationError(
            "provider_coupling_forbidden",
            f"payment method policy contains unsupported or provider-specific keys: {sorted(unknown)}",
        )
    methods = policy.get("allowed_methods")
    if not isinstance(methods, list) or not methods:
        raise PaymentCommandValidationError("methods_required", "allowed_methods must be a non-empty list")
    normalized = [str(method).strip().lower() for method in methods]
    if any(not _METHOD.fullmatch(method) for method in normalized):
        raise PaymentCommandValidationError("invalid_payment_method", "allowed method code is invalid")
    if len(normalized) != len(set(normalized)):
        raise PaymentCommandValidationError("duplicate_payment_method", "allowed methods must be unique")
    mixed = policy.get("allow_mixed_tender", False)
    maximum = policy.get("max_tenders", 1)
    if not isinstance(mixed, bool):
        raise PaymentCommandValidationError("invalid_mixed_tender_policy", "allow_mixed_tender must be boolean")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 16:
        raise PaymentCommandValidationError("invalid_max_tenders", "max_tenders must be an integer from 1 through 16")
    if not mixed and maximum != 1:
        raise PaymentCommandValidationError(
            "inconsistent_mixed_tender_policy", "max_tenders must be one when mixed tender is disabled"
        )
    return {
        "allowed_methods": normalized,
        "allow_mixed_tender": mixed,
        "max_tenders": maximum,
    }


@dataclass(frozen=True)
class CreatePaymentRequestCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    purpose_code: str
    requested_amount: Decimal
    currency_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    payer_party_id: UUID | None = None
    expires_at: datetime | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        if self.payer_party_id is not None:
            object.__setattr__(self, "payer_party_id", UUID(str(self.payer_party_id)))
        object.__setattr__(self, "purpose_code", str(self.purpose_code).strip().lower())
        object.__setattr__(self, "requested_amount", _money(self.requested_amount, "requested_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _normalize_identity(self)
        _validate_common(self)
        if not _CODE.fullmatch(self.purpose_code):
            raise PaymentCommandValidationError("invalid_purpose_code", "purpose_code is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "command": "create_payment_request",
            "public_id": str(self.public_id),
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "payer_party_id": str(self.payer_party_id) if self.payer_party_id else None,
            "purpose_code": self.purpose_code,
            "requested_amount": _decimal_text(self.requested_amount),
            "currency_code": self.currency_code,
            "expires_at": _timestamp_text(self.expires_at) if self.expires_at else None,
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
class CreatePaymentIntentCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    requested_amount: Decimal
    currency_code: str
    payment_method_policy: Mapping[str, Any]
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    payment_request_public_id: UUID | None = None
    financial_obligation_public_id: UUID | None = None
    expires_at: datetime | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        for name in ("payment_request_public_id", "financial_obligation_public_id"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, UUID(str(getattr(self, name))))
        object.__setattr__(self, "requested_amount", _money(self.requested_amount, "requested_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "payment_method_policy", normalize_method_policy(self.payment_method_policy))
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        _normalize_identity(self)
        _validate_common(self)
        if self.payment_request_public_id and self.financial_obligation_public_id:
            raise PaymentCommandValidationError(
                "ambiguous_intent_origin", "intent may reference a payment request or obligation, not both"
            )

    @property
    def intent_origin(self) -> str:
        if self.payment_request_public_id:
            return "payment_request"
        if self.financial_obligation_public_id:
            return "financial_obligation"
        return "standalone"

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "command": "create_payment_intent",
            "public_id": str(self.public_id),
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "payment_request_public_id": str(self.payment_request_public_id) if self.payment_request_public_id else None,
            "financial_obligation_public_id": str(self.financial_obligation_public_id) if self.financial_obligation_public_id else None,
            "intent_origin": self.intent_origin,
            "requested_amount": _decimal_text(self.requested_amount),
            "currency_code": self.currency_code,
            "payment_method_policy": self.payment_method_policy,
            "expires_at": _timestamp_text(self.expires_at) if self.expires_at else None,
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
