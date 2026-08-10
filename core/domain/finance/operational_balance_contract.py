"""Typed M6.0 operational-account and balance commands."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

CONTRACT_CODE = "XBOS_M60_OPERATIONAL_BALANCE_AUTHORITY"
CONTRACT_VERSION = 1
ACCOUNT_CLASSES = frozenset({"treasury", "control_account", "commercial_settlement"})
ACCOUNT_TYPES = frozenset({"cash", "mobile_money", "bank", "card", "gateway", "receivable", "payable", "clearing", "other"})
AGGREGATION_ROLES = frozenset({"leaf", "parent_aggregate", "presentation_only"})
ANCHOR_PROVENANCE = frozenset({"opening_import", "operator_confirmed", "external_confirmed"})
ACTUAL_PROVENANCE = frozenset({"operator_counted", "external_statement", "provider_confirmed"})
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3,12}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_LIMIT = Decimal("10000000000000000")


class OperationalBalanceValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class OperationalBalanceIdempotencyConflict(OperationalBalanceValidationError):
    pass


def _time(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OperationalBalanceValidationError("timezone_required", f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _money(value: Any, name: str) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OperationalBalanceValidationError("invalid_amount", f"{name} is invalid") from exc
    if not selected.is_finite() or abs(selected) >= _LIMIT or selected.as_tuple().exponent < -8:
        raise OperationalBalanceValidationError("invalid_amount", f"{name} must fit NUMERIC(24,8)")
    return selected.quantize(Decimal("0.00000001"))


def _json(value: Mapping[str, Any], name: str, *, required: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperationalBalanceValidationError("invalid_json_object", f"{name} must be an object")
    try:
        selected = json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise OperationalBalanceValidationError("invalid_json_value", f"{name} is invalid") from exc
    if required and not selected:
        raise OperationalBalanceValidationError("evidence_required", f"{name} is required")
    return selected


def _text(value: Any, name: str, maximum: int) -> str:
    selected = str(value).strip()
    if not selected:
        raise OperationalBalanceValidationError("command_identity_required", f"{name} is required")
    if len(selected) > maximum:
        raise OperationalBalanceValidationError("command_identity_too_long", f"{name} exceeds storage limit")
    return selected


def _decimal_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def evidence_hash(payload: Mapping[str, Any]) -> str:
    return _fingerprint(payload)


def _validate_scope(tenant_id: int, organization_unit_id: int, calendar_policy_version: int | None = None) -> None:
    if tenant_id <= 0 or organization_unit_id <= 0 or (calendar_policy_version is not None and calendar_policy_version <= 0):
        raise OperationalBalanceValidationError("invalid_scope", "tenant, organization, and calendar scope must be positive")


def _validate_actor(actor_user_id: int | None, actor_service: str | None) -> str | None:
    service = str(actor_service).strip() if actor_service else None
    if actor_user_id is None and not service:
        raise OperationalBalanceValidationError("actor_required", "actor is required")
    if actor_user_id is not None and actor_user_id <= 0:
        raise OperationalBalanceValidationError("invalid_actor", "actor user must be positive")
    if service and len(service) > 120:
        raise OperationalBalanceValidationError("invalid_actor", "actor service exceeds storage limit")
    return service


@dataclass(frozen=True)
class CreateOperationalAccountCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    account_class: str
    account_type: str
    code: str
    display_name: str
    currency_code: str
    aggregation_role: str
    opened_at: datetime
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    parent_account_public_id: UUID | None = None
    channel_code: str | None = None
    external_account_mask: str | None = None
    reconciliation_enabled: bool = True
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        if self.parent_account_public_id is not None:
            object.__setattr__(self, "parent_account_public_id", UUID(str(self.parent_account_public_id)))
        _validate_scope(self.tenant_id, self.organization_unit_id)
        for name in ("account_class", "account_type", "code", "aggregation_role"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().lower())
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "display_name", str(self.display_name).strip())
        object.__setattr__(self, "channel_code", str(self.channel_code).strip().lower() if self.channel_code else None)
        object.__setattr__(self, "external_account_mask", str(self.external_account_mask).strip() if self.external_account_mask else None)
        object.__setattr__(self, "opened_at", _time(self.opened_at, "opened_at"))
        object.__setattr__(self, "actor_service", _validate_actor(self.actor_user_id, self.actor_service))
        object.__setattr__(self, "metadata", _json(self.metadata, "metadata"))
        for name, maximum in (("source_component", 120), ("source_record_id", 191), ("idempotency_scope", 80), ("idempotency_key", 200)):
            object.__setattr__(self, name, _text(getattr(self, name), name, maximum))
        if self.account_class not in ACCOUNT_CLASSES or self.account_type not in ACCOUNT_TYPES:
            raise OperationalBalanceValidationError("invalid_account_kind", "account class or type is invalid")
        if self.aggregation_role not in AGGREGATION_ROLES:
            raise OperationalBalanceValidationError("invalid_aggregation_role", "aggregation role is invalid")
        if not _CODE.fullmatch(self.code) or not self.display_name or len(self.display_name) > 160:
            raise OperationalBalanceValidationError("invalid_account_identity", "account code or display name is invalid")
        if not _CURRENCY.fullmatch(self.currency_code):
            raise OperationalBalanceValidationError("invalid_currency", "currency code is invalid")
        if self.public_id == self.parent_account_public_id:
            raise OperationalBalanceValidationError("invalid_parent", "account cannot parent itself")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "create_operational_account",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "parent_account_public_id": str(self.parent_account_public_id) if self.parent_account_public_id else None,
            "account_class": self.account_class, "account_type": self.account_type, "code": self.code,
            "display_name": self.display_name, "currency_code": self.currency_code, "channel_code": self.channel_code,
            "external_account_mask": self.external_account_mask, "aggregation_role": self.aggregation_role,
            "reconciliation_enabled": self.reconciliation_enabled, "opened_at": _timestamp_text(self.opened_at),
            "correlation_id": str(self.correlation_id), "actor_user_id": self.actor_user_id, "actor_service": self.actor_service,
            "source_component": self.source_component, "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class RecordBalanceAnchorCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    operational_account_public_id: UUID
    anchor_balance: Any
    currency_code: str
    anchor_at: datetime
    provenance: str
    evidence_payload: Mapping[str, Any]
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
        _normalize_balance_command(self, "anchor_balance", "anchor_at")
        if self.provenance not in ANCHOR_PROVENANCE:
            raise OperationalBalanceValidationError("invalid_provenance", "anchor provenance is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return _balance_payload(self, "record_balance_anchor", "anchor_balance", "anchor_at")

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)


@dataclass(frozen=True)
class RecordActualBalanceCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    operational_account_public_id: UUID
    actual_balance: Any
    currency_code: str
    observed_at: datetime
    provenance: str
    evidence_payload: Mapping[str, Any]
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
        _normalize_balance_command(self, "actual_balance", "observed_at")
        if self.provenance not in ACTUAL_PROVENANCE:
            raise OperationalBalanceValidationError("invalid_provenance", "actual-balance provenance is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return _balance_payload(self, "record_actual_balance", "actual_balance", "observed_at")

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)


def _normalize_balance_command(command: Any, amount_field: str, time_field: str) -> None:
    for name in ("public_id", "operational_account_public_id", "correlation_id"):
        object.__setattr__(command, name, UUID(str(getattr(command, name))))
    _validate_scope(command.tenant_id, command.organization_unit_id, command.calendar_policy_version)
    object.__setattr__(command, amount_field, _money(getattr(command, amount_field), amount_field))
    object.__setattr__(command, "currency_code", str(command.currency_code).strip().upper())
    object.__setattr__(command, time_field, _time(getattr(command, time_field), time_field))
    object.__setattr__(command, "occurred_at", _time(command.occurred_at, "occurred_at"))
    object.__setattr__(command, "provenance", str(command.provenance).strip().lower())
    object.__setattr__(command, "evidence_payload", _json(command.evidence_payload, "evidence_payload", required=True))
    object.__setattr__(command, "metadata", _json(command.metadata, "metadata"))
    object.__setattr__(command, "actor_service", _validate_actor(command.actor_user_id, command.actor_service))
    for name, maximum in (("source_component", 120), ("source_record_id", 191), ("idempotency_scope", 80), ("idempotency_key", 200)):
        object.__setattr__(command, name, _text(getattr(command, name), name, maximum))
    if not _CURRENCY.fullmatch(command.currency_code):
        raise OperationalBalanceValidationError("invalid_currency", "currency code is invalid")
    if not isinstance(command.business_date, date) or isinstance(command.business_date, datetime):
        raise OperationalBalanceValidationError("invalid_business_date", "business_date must be a date")


def _balance_payload(command: Any, command_name: str, amount_field: str, time_field: str) -> dict[str, Any]:
    return {
        "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": command_name,
        "public_id": str(command.public_id), "tenant_id": command.tenant_id,
        "organization_unit_id": command.organization_unit_id,
        "operational_account_public_id": str(command.operational_account_public_id),
        amount_field: _decimal_text(getattr(command, amount_field)), "currency_code": command.currency_code,
        time_field: _timestamp_text(getattr(command, time_field)), "provenance": command.provenance,
        "evidence_payload": command.evidence_payload, "occurred_at": _timestamp_text(command.occurred_at),
        "business_date": command.business_date.isoformat(), "calendar_policy_version": command.calendar_policy_version,
        "correlation_id": str(command.correlation_id), "actor_user_id": command.actor_user_id,
        "actor_service": command.actor_service, "source_component": command.source_component,
        "source_record_id": command.source_record_id, "idempotency_scope": command.idempotency_scope,
        "idempotency_key": command.idempotency_key, "metadata": command.metadata,
    }


@dataclass(frozen=True)
class OperationalBalanceQuery:
    tenant_id: int
    organization_unit_id: int
    operational_account_public_id: UUID
    as_of: datetime

    def __post_init__(self) -> None:
        _validate_scope(self.tenant_id, self.organization_unit_id)
        object.__setattr__(self, "operational_account_public_id", UUID(str(self.operational_account_public_id)))
        object.__setattr__(self, "as_of", _time(self.as_of, "as_of"))
