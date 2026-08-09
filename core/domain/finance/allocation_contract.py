"""Typed, framework-independent contracts for M3.2 allocation authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

CONTRACT_CODE = "XBOS_M32_ALLOCATION_REVERSAL_ENGINE"
CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_LIMIT = Decimal("10000000000000000")
_SCALE = Decimal("0.00000001")


class AllocationContractError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AllocationValidationError(AllocationContractError):
    pass


def _money(value: Any, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AllocationValidationError("invalid_money", f"{name} must be decimal") from exc
    if not amount.is_finite() or amount <= 0 or amount >= _LIMIT or amount.as_tuple().exponent < -8:
        raise AllocationValidationError("invalid_money", f"{name} must be positive NUMERIC(24,8)")
    return amount.quantize(_SCALE)


def _stamp(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AllocationValidationError("timezone_required", f"{name} must be timezone-aware")
    return value


def _metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AllocationValidationError("invalid_metadata", "metadata must be an object")
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise AllocationValidationError("invalid_metadata", "metadata must be JSON") from exc


def _decimal_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class _BaseCommand:
    public_id: UUID
    tenant_id: int
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

    def _normalize(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        object.__setattr__(self, "occurred_at", _stamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "source_component", str(self.source_component).strip())
        object.__setattr__(self, "source_record_id", str(self.source_record_id).strip())
        object.__setattr__(self, "idempotency_scope", str(self.idempotency_scope).strip())
        object.__setattr__(self, "idempotency_key", str(self.idempotency_key).strip())
        object.__setattr__(self, "actor_service", str(self.actor_service).strip() if self.actor_service else None)
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        if self.tenant_id <= 0 or self.calendar_policy_version <= 0:
            raise AllocationValidationError("invalid_scope", "tenant and calendar policy version must be positive")
        if not all((self.source_component, self.source_record_id, self.idempotency_scope, self.idempotency_key)):
            raise AllocationValidationError("missing_identity", "source and idempotency identities are required")
        if self.actor_user_id is None and not self.actor_service:
            raise AllocationValidationError("actor_required", "a governed actor is required")

    def _common(self, command: str) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": command,
            "public_id": str(self.public_id), "tenant_id": self.tenant_id,
            "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
            "correlation_id": str(self.correlation_id), "source_component": self.source_component,
            "source_record_id": self.source_record_id, "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key, "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service, "metadata": self.metadata,
        }

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class CreateValueSourceCommand(_BaseCommand):
    organization_unit_id: int = 0
    owner_party_id: UUID = UUID(int=0)
    source_type: str = ""
    source_amount: Decimal = Decimal("0")
    currency_code: str = ""
    payment_settlement_public_id: UUID | None = None

    def __post_init__(self) -> None:
        self._normalize()
        object.__setattr__(self, "owner_party_id", UUID(str(self.owner_party_id)))
        if self.payment_settlement_public_id is not None:
            object.__setattr__(self, "payment_settlement_public_id", UUID(str(self.payment_settlement_public_id)))
        object.__setattr__(self, "source_type", str(self.source_type).strip().lower())
        object.__setattr__(self, "source_amount", _money(self.source_amount, "source_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        if self.organization_unit_id <= 0 or not _CODE.fullmatch(self.source_type) or not _CURRENCY.fullmatch(self.currency_code):
            raise AllocationValidationError("invalid_value_source", "organization, source type, or currency is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return {**self._common("create_value_source"), "organization_unit_id": self.organization_unit_id,
                "owner_party_id": str(self.owner_party_id), "source_type": self.source_type,
                "source_amount": _decimal_text(self.source_amount), "currency_code": self.currency_code,
                "payment_settlement_public_id": str(self.payment_settlement_public_id) if self.payment_settlement_public_id else None}


@dataclass(frozen=True)
class AllocateValueCommand(_BaseCommand):
    organization_unit_id: int = 0
    value_source_public_id: UUID = UUID(int=0)
    obligation_public_id: UUID = UUID(int=0)
    allocation_amount: Decimal = Decimal("0")
    currency_code: str = ""
    cross_organization_policy_code: str | None = None
    cross_organization_policy_version: int | None = None

    def __post_init__(self) -> None:
        self._normalize()
        object.__setattr__(self, "value_source_public_id", UUID(str(self.value_source_public_id)))
        object.__setattr__(self, "obligation_public_id", UUID(str(self.obligation_public_id)))
        object.__setattr__(self, "allocation_amount", _money(self.allocation_amount, "allocation_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        code = str(self.cross_organization_policy_code).strip().lower() if self.cross_organization_policy_code else None
        object.__setattr__(self, "cross_organization_policy_code", code)
        if self.organization_unit_id <= 0 or not _CURRENCY.fullmatch(self.currency_code):
            raise AllocationValidationError("invalid_allocation", "organization or currency is invalid")
        paired = code is not None and self.cross_organization_policy_version is not None
        if (code is None) != (self.cross_organization_policy_version is None) or (paired and (not _CODE.fullmatch(code) or self.cross_organization_policy_version <= 0)):
            raise AllocationValidationError("invalid_cross_organization_policy", "policy code and positive version must be paired")

    def canonical_payload(self) -> dict[str, Any]:
        return {**self._common("allocate_value"), "organization_unit_id": self.organization_unit_id,
                "value_source_public_id": str(self.value_source_public_id), "obligation_public_id": str(self.obligation_public_id),
                "allocation_amount": _decimal_text(self.allocation_amount), "currency_code": self.currency_code,
                "cross_organization_policy_code": self.cross_organization_policy_code,
                "cross_organization_policy_version": self.cross_organization_policy_version}


@dataclass(frozen=True)
class ReverseAllocationCommand(_BaseCommand):
    organization_unit_id: int = 0
    payment_allocation_public_id: UUID = UUID(int=0)
    reversal_amount: Decimal = Decimal("0")
    currency_code: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        self._normalize()
        object.__setattr__(self, "payment_allocation_public_id", UUID(str(self.payment_allocation_public_id)))
        object.__setattr__(self, "reversal_amount", _money(self.reversal_amount, "reversal_amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "reason_code", str(self.reason_code).strip().lower())
        if self.organization_unit_id <= 0 or not _CURRENCY.fullmatch(self.currency_code) or not _CODE.fullmatch(self.reason_code):
            raise AllocationValidationError("invalid_reversal", "organization, currency, or reason is invalid")

    def canonical_payload(self) -> dict[str, Any]:
        return {**self._common("reverse_allocation"), "organization_unit_id": self.organization_unit_id,
                "payment_allocation_public_id": str(self.payment_allocation_public_id),
                "reversal_amount": _decimal_text(self.reversal_amount), "currency_code": self.currency_code,
                "reason_code": self.reason_code}
