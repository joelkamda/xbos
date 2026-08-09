"""Pure typed contracts and validation for M3.1 financial obligations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID


CONTRACT_CODE = "XBOS_M31_TYPED_OBLIGATION_LIFECYCLE_AND_BALANCES"
CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MAX_SCALE = Decimal("0.00000001")
_NUMERIC_24_8_LIMIT = Decimal("10000000000000000")


class ObligationContractError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ObligationValidationError(ObligationContractError):
    pass


class ObligationIdempotencyConflict(ObligationContractError):
    pass


def _decimal(value: Any, field_name: str, *, positive: bool = True) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ObligationValidationError("invalid_money", f"{field_name} must be decimal") from exc
    if (
        not selected.is_finite()
        or (positive and selected <= 0)
        or abs(selected) >= _NUMERIC_24_8_LIMIT
        or selected.as_tuple().exponent < -8
    ):
        raise ObligationValidationError(
            "invalid_money", f"{field_name} must be finite, positive, and use at most eight decimals"
        )
    return selected.quantize(_MAX_SCALE)


def _json_object(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ObligationValidationError("invalid_json_object", f"{field_name} must be an object")
    try:
        decoded = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ObligationValidationError("invalid_json_value", f"{field_name} is not valid JSON") from exc
    return decoded


def _timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ObligationValidationError("timezone_required", f"{field_name} must be timezone-aware")
    return value


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_decimal(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ObligationLineCommand:
    line_number: int
    line_type: str
    description: str
    quantity: Decimal
    unit_amount: Decimal
    line_amount: Decimal
    source_record_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_type", str(self.line_type).strip().lower())
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "source_record_id", str(self.source_record_id).strip())
        object.__setattr__(self, "quantity", _decimal(self.quantity, "quantity"))
        object.__setattr__(self, "unit_amount", _decimal(self.unit_amount, "unit_amount", positive=False))
        object.__setattr__(self, "line_amount", _decimal(self.line_amount, "line_amount"))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "line.metadata"))
        if self.line_number <= 0:
            raise ObligationValidationError("invalid_line_number", "line_number must be positive")
        if not _CODE.fullmatch(self.line_type):
            raise ObligationValidationError("invalid_line_type", "line_type is invalid")
        if self.unit_amount < 0:
            raise ObligationValidationError("invalid_money", "unit_amount cannot be negative")
        if not self.description or not self.source_record_id:
            raise ObligationValidationError("missing_line_identity", "line description and source are required")
        if self.quantity * self.unit_amount != self.line_amount:
            raise ObligationValidationError("line_arithmetic_mismatch", "line_amount must equal quantity times unit_amount")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "line_number": self.line_number,
            "line_type": self.line_type,
            "description": self.description,
            "quantity": _canonical_decimal(self.quantity),
            "unit_amount": _canonical_decimal(self.unit_amount),
            "line_amount": _canonical_decimal(self.line_amount),
            "source_record_id": self.source_record_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class CreateObligationCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    debtor_party_id: UUID
    creditor_party_id: UUID
    obligation_type: str
    original_amount: Decimal
    currency_code: str
    due_at: datetime
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    lines: tuple[ObligationLineCommand, ...]
    actor_user_id: int | None = None
    actor_service: str | None = None
    commercial_transaction_public_id: UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("public_id", "debtor_party_id", "creditor_party_id", "correlation_id"):
            object.__setattr__(self, name, UUID(str(getattr(self, name))))
        if self.commercial_transaction_public_id is not None:
            object.__setattr__(self, "commercial_transaction_public_id", UUID(str(self.commercial_transaction_public_id)))
        object.__setattr__(self, "obligation_type", str(self.obligation_type).strip().lower())
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "source_component", str(self.source_component).strip())
        object.__setattr__(self, "source_record_id", str(self.source_record_id).strip())
        object.__setattr__(self, "idempotency_scope", str(self.idempotency_scope).strip())
        object.__setattr__(self, "idempotency_key", str(self.idempotency_key).strip())
        object.__setattr__(self, "actor_service", str(self.actor_service).strip() if self.actor_service else None)
        object.__setattr__(self, "original_amount", _decimal(self.original_amount, "original_amount"))
        object.__setattr__(self, "due_at", _timestamp(self.due_at, "due_at"))
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))
        validate_create_obligation(self)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "command": "create_obligation",
            "public_id": str(self.public_id),
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "debtor_party_id": str(self.debtor_party_id),
            "creditor_party_id": str(self.creditor_party_id),
            "commercial_transaction_public_id": str(self.commercial_transaction_public_id) if self.commercial_transaction_public_id else None,
            "obligation_type": self.obligation_type,
            "original_amount": _canonical_decimal(self.original_amount),
            "currency_code": self.currency_code,
            "due_at": _canonical_timestamp(self.due_at),
            "occurred_at": _canonical_timestamp(self.occurred_at),
            "business_date": self.business_date.isoformat(),
            "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id),
            "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service,
            "source_component": self.source_component,
            "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "lines": [line.canonical_payload() for line in self.lines],
            "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class TransitionObligationCommand:
    tenant_id: int
    obligation_public_id: UUID
    target_state: str
    expected_row_version: int
    reason_code: str
    idempotency_scope: str
    idempotency_key: str
    actor_user_id: int | None = None
    actor_service: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_public_id", UUID(str(self.obligation_public_id)))
        for name in ("target_state", "reason_code"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().lower())
        for name in ("idempotency_scope", "idempotency_key"):
            object.__setattr__(self, name, str(getattr(self, name)).strip())
        object.__setattr__(self, "actor_service", str(self.actor_service).strip() if self.actor_service else None)
        if self.tenant_id <= 0 or self.expected_row_version <= 0:
            raise ObligationValidationError("invalid_transition_identity", "tenant and expected version must be positive")
        if self.target_state not in {"cancelled", "written_off"}:
            raise ObligationValidationError("invalid_manual_state", "manual transitions may only cancel or write off")
        if not _CODE.fullmatch(self.reason_code):
            raise ObligationValidationError("invalid_reason_code", "reason_code is invalid")
        if not self.idempotency_scope or not self.idempotency_key:
            raise ObligationValidationError("missing_idempotency", "idempotency scope and key are required")
        if self.actor_user_id is None and not self.actor_service:
            raise ObligationValidationError("actor_required", "a user or service actor is required")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "command": "transition_obligation",
            "tenant_id": self.tenant_id,
            "obligation_public_id": str(self.obligation_public_id),
            "target_state": self.target_state,
            "expected_row_version": self.expected_row_version,
            "reason_code": self.reason_code,
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


def validate_create_obligation(command: CreateObligationCommand) -> None:
    if command.tenant_id <= 0 or command.organization_unit_id <= 0:
        raise ObligationValidationError("invalid_scope", "tenant and organization must be positive")
    if command.debtor_party_id == command.creditor_party_id:
        raise ObligationValidationError("same_party", "debtor and creditor must differ")
    if not _CODE.fullmatch(command.obligation_type):
        raise ObligationValidationError("invalid_obligation_type", "obligation_type is invalid")
    if not _CURRENCY.fullmatch(command.currency_code):
        raise ObligationValidationError("invalid_currency", "currency_code must be three uppercase letters")
    if command.due_at < command.occurred_at:
        raise ObligationValidationError("invalid_due_at", "due_at cannot precede occurred_at")
    if command.calendar_policy_version <= 0:
        raise ObligationValidationError("invalid_calendar_version", "calendar policy version must be positive")
    if command.actor_user_id is None and not command.actor_service:
        raise ObligationValidationError("actor_required", "a user or service actor is required")
    if not all((command.source_component, command.source_record_id, command.idempotency_scope, command.idempotency_key)):
        raise ObligationValidationError("missing_command_identity", "source and idempotency identities are required")
    if not command.lines:
        raise ObligationValidationError("lines_required", "at least one obligation line is required")
    numbers = [line.line_number for line in command.lines]
    if len(numbers) != len(set(numbers)):
        raise ObligationValidationError("duplicate_line_number", "line numbers must be unique")
    if sum((line.line_amount for line in command.lines), Decimal("0")) != command.original_amount:
        raise ObligationValidationError("line_total_mismatch", "line total must exactly equal original_amount")
