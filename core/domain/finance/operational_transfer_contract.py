"""Typed M6.1 operational-transfer and reconciliation-series contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping
from uuid import UUID

from .operational_balance_contract import (
    OperationalBalanceValidationError,
    _CURRENCY,
    _decimal_text,
    _fingerprint,
    _json,
    _money,
    _text,
    _time,
    _timestamp_text,
    _validate_actor,
    _validate_scope,
    evidence_hash,
)

CONTRACT_CODE = "XBOS_M61_OPERATIONAL_TRANSFERS_AND_RECONCILIATION_SERIES"
CONTRACT_VERSION = 1
TRANSFER_PROVENANCE = frozenset({"operator_authorized", "system_authorized", "external_confirmed"})


class OperationalTransferValidationError(OperationalBalanceValidationError):
    """Raised before an invalid transfer can reach canonical event authority."""


def _normalize_common(command: Any) -> None:
    try:
        _normalize_common_unchecked(command)
    except OperationalTransferValidationError:
        raise
    except OperationalBalanceValidationError as exc:
        raise OperationalTransferValidationError(exc.code, str(exc)) from exc


def _normalize_common_unchecked(command: Any) -> None:
    for name in ("public_id", "correlation_id"):
        object.__setattr__(command, name, UUID(str(getattr(command, name))))
    if command.causation_id is not None:
        object.__setattr__(command, "causation_id", UUID(str(command.causation_id)))
    _validate_scope(command.tenant_id, command.organization_unit_id, command.calendar_policy_version)
    object.__setattr__(command, "amount", _money(command.amount, "amount"))
    if command.amount <= 0:
        raise OperationalTransferValidationError("invalid_amount", "transfer amount must be positive")
    object.__setattr__(command, "currency_code", str(command.currency_code).strip().upper())
    if not _CURRENCY.fullmatch(command.currency_code):
        raise OperationalTransferValidationError("invalid_currency", "currency code is invalid")
    object.__setattr__(command, "occurred_at", _time(command.occurred_at, "occurred_at"))
    object.__setattr__(command, "value_at", _time(command.value_at, "value_at"))
    if not isinstance(command.business_date, date) or isinstance(command.business_date, datetime):
        raise OperationalTransferValidationError("invalid_business_date", "business_date must be a date")
    object.__setattr__(command, "evidence_payload", _json(command.evidence_payload, "evidence_payload", required=True))
    object.__setattr__(command, "metadata", _json(command.metadata, "metadata"))
    object.__setattr__(command, "actor_service", _validate_actor(command.actor_user_id, command.actor_service))
    for name, maximum in (("idempotency_scope", 80), ("idempotency_key", 200)):
        object.__setattr__(command, name, _text(getattr(command, name), name, maximum))
    try:
        source_record_id = int(command.source_record_id)
    except (TypeError, ValueError) as exc:
        raise OperationalTransferValidationError("invalid_source_record", "source_record_id must be positive") from exc
    if source_record_id <= 0:
        raise OperationalTransferValidationError("invalid_source_record", "source_record_id must be positive")
    object.__setattr__(command, "source_record_id", source_record_id)


def _required_text(value: Any, name: str, maximum: int) -> str:
    try:
        return _text(value, name, maximum)
    except OperationalBalanceValidationError as exc:
        raise OperationalTransferValidationError(exc.code, str(exc)) from exc


@dataclass(frozen=True)
class RecordOperationalTransferCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    source_operational_account_public_id: UUID
    destination_operational_account_public_id: UUID
    amount: Any
    currency_code: str
    occurred_at: datetime
    value_at: datetime
    business_date: date
    calendar_policy_version: int
    provenance: str
    transfer_purpose: str
    evidence_payload: Mapping[str, Any]
    source_record_id: int
    idempotency_scope: str
    idempotency_key: str
    correlation_id: UUID
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_common(self)
        for name in ("source_operational_account_public_id", "destination_operational_account_public_id"):
            object.__setattr__(self, name, UUID(str(getattr(self, name))))
        if self.source_operational_account_public_id == self.destination_operational_account_public_id:
            raise OperationalTransferValidationError("accounts_must_differ", "source and destination accounts must differ")
        object.__setattr__(self, "provenance", str(self.provenance).strip().lower())
        if self.provenance not in TRANSFER_PROVENANCE:
            raise OperationalTransferValidationError("invalid_provenance", "transfer provenance is invalid")
        object.__setattr__(self, "transfer_purpose", _required_text(self.transfer_purpose, "transfer_purpose", 80).lower())

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "record_operational_transfer",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_operational_account_public_id": str(self.source_operational_account_public_id),
            "destination_operational_account_public_id": str(self.destination_operational_account_public_id),
            "amount": _decimal_text(self.amount), "currency_code": self.currency_code,
            "occurred_at": _timestamp_text(self.occurred_at), "value_at": _timestamp_text(self.value_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "provenance": self.provenance, "transfer_purpose": self.transfer_purpose,
            "evidence_payload": self.evidence_payload, "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key,
            "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "actor_user_id": self.actor_user_id, "actor_service": self.actor_service, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)


@dataclass(frozen=True)
class ReverseOperationalTransferCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    original_transfer_public_id: UUID
    amount: Any
    currency_code: str
    occurred_at: datetime
    value_at: datetime
    business_date: date
    calendar_policy_version: int
    reversal_reason: str
    evidence_payload: Mapping[str, Any]
    source_record_id: int
    idempotency_scope: str
    idempotency_key: str
    correlation_id: UUID
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _normalize_common(self)
        object.__setattr__(self, "original_transfer_public_id", UUID(str(self.original_transfer_public_id)))
        object.__setattr__(self, "reversal_reason", _required_text(self.reversal_reason, "reversal_reason", 80).lower())

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "reverse_operational_transfer",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "original_transfer_public_id": str(self.original_transfer_public_id),
            "amount": _decimal_text(self.amount), "currency_code": self.currency_code,
            "occurred_at": _timestamp_text(self.occurred_at), "value_at": _timestamp_text(self.value_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "reversal_reason": self.reversal_reason, "evidence_payload": self.evidence_payload,
            "source_record_id": self.source_record_id, "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key, "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "actor_user_id": self.actor_user_id, "actor_service": self.actor_service, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)


@dataclass(frozen=True)
class ReconciliationSeriesQuery:
    tenant_id: int
    organization_unit_id: int
    operational_account_public_id: UUID
    through_at: datetime
    from_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_scope(self.tenant_id, self.organization_unit_id)
        object.__setattr__(self, "operational_account_public_id", UUID(str(self.operational_account_public_id)))
        object.__setattr__(self, "through_at", _time(self.through_at, "through_at"))
        if self.from_at is not None:
            object.__setattr__(self, "from_at", _time(self.from_at, "from_at"))
            if self.from_at > self.through_at:
                raise OperationalTransferValidationError("invalid_series_range", "from_at cannot follow through_at")
