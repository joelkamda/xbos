"""Typed M6.2 reconciliation-window, calendar, and cascade contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Mapping, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .operational_balance_contract import (
    OperationalBalanceValidationError,
    _CURRENCY,
    _fingerprint,
    _json,
    _text,
    _time,
    _timestamp_text,
    _validate_actor,
    _validate_scope,
    evidence_hash,
)

CONTRACT_CODE = "XBOS_M62_RECONCILIATION_WINDOWS_CONTINUITY_AND_CASCADES"
CONTRACT_VERSION = 1
CASCADE_REASONS = frozenset({"financial_fact_appended", "balance_observation_appended", "authorized_recalculation"})


class ReconciliationWindowValidationError(OperationalBalanceValidationError):
    """Raised before invalid reconciliation control state reaches persistence."""


def _raise_normalized(action) -> None:
    try:
        action()
    except ReconciliationWindowValidationError:
        raise
    except OperationalBalanceValidationError as exc:
        raise ReconciliationWindowValidationError(exc.code, str(exc)) from exc


def _uuid(command, name: str, *, optional: bool = False) -> None:
    value = getattr(command, name)
    if optional and value is None:
        return
    try:
        object.__setattr__(command, name, UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ReconciliationWindowValidationError("invalid_identity", f"{name} must be a UUID") from exc


def _common(command, *, evidence: bool) -> None:
    for name in ("public_id", "correlation_id"):
        _uuid(command, name)
    _uuid(command, "causation_id", optional=True)
    _raise_normalized(lambda: _validate_scope(command.tenant_id, command.organization_unit_id, command.calendar_policy_version))
    object.__setattr__(command, "occurred_at", _raise_time(command.occurred_at, "occurred_at"))
    if not isinstance(command.business_date, date) or isinstance(command.business_date, datetime):
        raise ReconciliationWindowValidationError("invalid_business_date", "business_date must be a date")
    object.__setattr__(command, "actor_service", _raise_actor(command.actor_user_id, command.actor_service))
    for name, maximum in (("source_component", 120), ("source_record_id", 191), ("idempotency_scope", 80), ("idempotency_key", 200)):
        object.__setattr__(command, name, _raise_text(getattr(command, name), name, maximum))
    object.__setattr__(command, "metadata", _raise_json(command.metadata, "metadata"))
    if evidence:
        object.__setattr__(command, "evidence_payload", _raise_json(command.evidence_payload, "evidence_payload", required=True))


def _raise_time(value: Any, name: str) -> datetime:
    selected: datetime | None = None
    def apply() -> None:
        nonlocal selected
        selected = _time(value, name)
    _raise_normalized(apply)
    assert selected is not None
    return selected


def _raise_actor(user_id, service):
    selected = None
    def apply() -> None:
        nonlocal selected
        selected = _validate_actor(user_id, service)
    _raise_normalized(apply)
    return selected


def _raise_text(value, name, maximum):
    selected = None
    def apply() -> None:
        nonlocal selected
        selected = _text(value, name, maximum)
    _raise_normalized(apply)
    return selected


def _raise_json(value, name, *, required=False):
    selected = None
    def apply() -> None:
        nonlocal selected
        selected = _json(value, name, required=required)
    _raise_normalized(apply)
    return selected


def _clock(value: Any, name: str) -> time:
    if isinstance(value, str):
        try:
            value = time.fromisoformat(value)
        except ValueError as exc:
            raise ReconciliationWindowValidationError("invalid_local_time", f"{name} is invalid") from exc
    if not isinstance(value, time) or value.tzinfo is not None or value.second or value.microsecond:
        raise ReconciliationWindowValidationError("invalid_local_time", f"{name} must be a minute-precision local time")
    return value


@dataclass(frozen=True)
class ShiftDefinition:
    code: str
    starts_at: time | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _raise_text(self.code, "shift_code", 40).lower())
        object.__setattr__(self, "starts_at", _clock(self.starts_at, "starts_at"))

    def canonical_payload(self) -> dict[str, str]:
        return {"code": self.code, "starts_at": self.starts_at.isoformat(timespec="minutes")}


def _shifts(value: Sequence[ShiftDefinition | Mapping[str, Any]]) -> tuple[ShiftDefinition, ...]:
    selected = tuple(item if isinstance(item, ShiftDefinition) else ShiftDefinition(**dict(item)) for item in value)
    if not selected:
        raise ReconciliationWindowValidationError("shift_required", "at least one shift boundary is required")
    if len({item.code for item in selected}) != len(selected) or len({item.starts_at for item in selected}) != len(selected):
        raise ReconciliationWindowValidationError("duplicate_shift", "shift codes and boundaries must be unique")
    return tuple(sorted(selected, key=lambda item: item.starts_at))


@dataclass(frozen=True)
class CreateReconciliationCalendarPolicyCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    policy_code: str
    policy_version: int
    timezone_name: str
    business_day_boundary: time | str
    shifts: Sequence[ShiftDefinition | Mapping[str, Any]]
    effective_from: datetime
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _common(self, evidence=False)
        object.__setattr__(self, "policy_code", _raise_text(self.policy_code, "policy_code", 80).lower())
        if self.policy_version <= 0:
            raise ReconciliationWindowValidationError("invalid_policy_version", "policy_version must be positive")
        object.__setattr__(self, "timezone_name", _raise_text(self.timezone_name, "timezone_name", 80))
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ReconciliationWindowValidationError("invalid_timezone", "timezone_name is unknown") from exc
        object.__setattr__(self, "business_day_boundary", _clock(self.business_day_boundary, "business_day_boundary"))
        object.__setattr__(self, "shifts", _shifts(self.shifts))
        if self.business_day_boundary not in {item.starts_at for item in self.shifts}:
            raise ReconciliationWindowValidationError("boundary_shift_required", "business-day boundary must also begin a shift")
        object.__setattr__(self, "effective_from", _raise_time(self.effective_from, "effective_from"))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "create_calendar_policy",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "policy_code": self.policy_code, "policy_version": self.policy_version, "timezone_name": self.timezone_name,
            "business_day_boundary": self.business_day_boundary.isoformat(timespec="minutes"),
            "shifts": [item.canonical_payload() for item in self.shifts], "effective_from": _timestamp_text(self.effective_from),
            "occurred_at": _timestamp_text(self.occurred_at), "business_date": self.business_date.isoformat(),
            "calendar_policy_version": self.calendar_policy_version, "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None, "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service, "source_component": self.source_component, "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class CreateReconciliationSeriesCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    operational_account_public_id: UUID
    calendar_policy_public_id: UUID
    series_code: str
    currency_code: str
    starts_at: datetime
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _common(self, evidence=False)
        _uuid(self, "operational_account_public_id"); _uuid(self, "calendar_policy_public_id")
        object.__setattr__(self, "series_code", _raise_text(self.series_code, "series_code", 80).lower())
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        if not _CURRENCY.fullmatch(self.currency_code):
            raise ReconciliationWindowValidationError("invalid_currency", "currency code is invalid")
        object.__setattr__(self, "starts_at", _raise_time(self.starts_at, "starts_at"))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "create_reconciliation_series",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "operational_account_public_id": str(self.operational_account_public_id),
            "calendar_policy_public_id": str(self.calendar_policy_public_id), "series_code": self.series_code,
            "currency_code": self.currency_code, "starts_at": _timestamp_text(self.starts_at),
            "occurred_at": _timestamp_text(self.occurred_at), "business_date": self.business_date.isoformat(),
            "calendar_policy_version": self.calendar_policy_version, "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None, "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service, "source_component": self.source_component, "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class RecordReconciliationWindowCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    reconciliation_series_public_id: UUID
    window_start: datetime
    window_end: datetime
    evidence_payload: Mapping[str, Any]
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _common(self, evidence=True); _uuid(self, "reconciliation_series_public_id")
        object.__setattr__(self, "window_start", _raise_time(self.window_start, "window_start"))
        object.__setattr__(self, "window_end", _raise_time(self.window_end, "window_end"))
        if self.window_end <= self.window_start:
            raise ReconciliationWindowValidationError("invalid_window_range", "window_end must follow window_start")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "record_reconciliation_window",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "reconciliation_series_public_id": str(self.reconciliation_series_public_id),
            "window_start": _timestamp_text(self.window_start), "window_end": _timestamp_text(self.window_end),
            "evidence_payload": self.evidence_payload, "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id), "causation_id": str(self.causation_id) if self.causation_id else None,
            "actor_user_id": self.actor_user_id, "actor_service": self.actor_service,
            "source_component": self.source_component, "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)


@dataclass(frozen=True)
class CascadeReconciliationWindowsCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    reconciliation_series_public_id: UUID
    changed_from_at: datetime
    cascade_reason: str
    evidence_payload: Mapping[str, Any]
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _common(self, evidence=True); _uuid(self, "reconciliation_series_public_id")
        object.__setattr__(self, "changed_from_at", _raise_time(self.changed_from_at, "changed_from_at"))
        object.__setattr__(self, "cascade_reason", str(self.cascade_reason).strip().lower())
        if self.cascade_reason not in CASCADE_REASONS:
            raise ReconciliationWindowValidationError("invalid_cascade_reason", "cascade_reason is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "cascade_reconciliation_windows",
            "public_id": str(self.public_id), "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "reconciliation_series_public_id": str(self.reconciliation_series_public_id),
            "changed_from_at": _timestamp_text(self.changed_from_at), "cascade_reason": self.cascade_reason,
            "evidence_payload": self.evidence_payload, "occurred_at": _timestamp_text(self.occurred_at),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id), "causation_id": str(self.causation_id) if self.causation_id else None,
            "actor_user_id": self.actor_user_id, "actor_service": self.actor_service,
            "source_component": self.source_component, "source_record_id": self.source_record_id,
            "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)
