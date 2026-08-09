"""Typed M3.3 receipt, deposit, unapplied-value, and overpayment commands."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .allocation_contract import CreateValueSourceCommand

CONTRACT_CODE = "XBOS_M33_UNAPPLIED_VALUE_AND_OVERPAYMENT_WORKFLOWS"
CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_LIMIT = Decimal("10000000000000000")
_SCALE = Decimal("0.00000001")


class ValueApplicationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueApplicationError("invalid_money", "application amount must be decimal") from exc
    if not amount.is_finite() or amount <= 0 or amount >= _LIMIT or amount.as_tuple().exponent < -8:
        raise ValueApplicationError("invalid_money", "application amount must be positive NUMERIC(24,8)")
    return amount.quantize(_SCALE)


def _json(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueApplicationError("invalid_metadata", "metadata must be an object")
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueApplicationError("invalid_metadata", "metadata must be JSON") from exc


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _fingerprint(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class ValueApplicationInstruction:
    allocation_public_id: UUID
    obligation_public_id: UUID
    source_record_id: str
    idempotency_key: str
    exact_amount: Decimal | None = None
    cross_organization_policy_code: str | None = None
    cross_organization_policy_version: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allocation_public_id", UUID(str(self.allocation_public_id)))
        object.__setattr__(self, "obligation_public_id", UUID(str(self.obligation_public_id)))
        object.__setattr__(self, "source_record_id", str(self.source_record_id).strip())
        object.__setattr__(self, "idempotency_key", str(self.idempotency_key).strip())
        if self.exact_amount is not None:
            object.__setattr__(self, "exact_amount", _money(self.exact_amount))
        code = str(self.cross_organization_policy_code).strip().lower() if self.cross_organization_policy_code else None
        object.__setattr__(self, "cross_organization_policy_code", code)
        object.__setattr__(self, "metadata", _json(self.metadata))
        if not self.source_record_id or not self.idempotency_key:
            raise ValueApplicationError("missing_instruction_identity", "instruction source and idempotency keys are required")
        if (code is None) != (self.cross_organization_policy_version is None):
            raise ValueApplicationError("invalid_cross_organization_policy", "policy code and version must be paired")
        if code is not None and (not _CODE.fullmatch(code) or self.cross_organization_policy_version <= 0):
            raise ValueApplicationError("invalid_cross_organization_policy", "policy identity is invalid")

    @property
    def mode(self) -> str:
        return "exact" if self.exact_amount is not None else "up_to_outstanding"

    def canonical_payload(self):
        return {"allocation_public_id": str(self.allocation_public_id),
                "obligation_public_id": str(self.obligation_public_id), "mode": self.mode,
                "exact_amount": _decimal_text(self.exact_amount), "source_record_id": self.source_record_id,
                "idempotency_key": self.idempotency_key,
                "cross_organization_policy_code": self.cross_organization_policy_code,
                "cross_organization_policy_version": self.cross_organization_policy_version,
                "metadata": self.metadata}


@dataclass(frozen=True)
class ApplyUnappliedValueCommand:
    tenant_id: int
    value_source_public_id: UUID
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    idempotency_scope: str
    applications: tuple[ValueApplicationInstruction, ...]
    actor_user_id: int | None = None
    actor_service: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "value_source_public_id", UUID(str(self.value_source_public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        object.__setattr__(self, "applications", tuple(self.applications))
        object.__setattr__(self, "source_component", str(self.source_component).strip())
        object.__setattr__(self, "idempotency_scope", str(self.idempotency_scope).strip())
        object.__setattr__(self, "actor_service", str(self.actor_service).strip() if self.actor_service else None)
        if self.tenant_id <= 0 or self.calendar_policy_version <= 0:
            raise ValueApplicationError("invalid_scope", "tenant and calendar policy version must be positive")
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueApplicationError("timezone_required", "occurred_at must be timezone-aware")
        if not self.source_component or not self.idempotency_scope or not self.applications:
            raise ValueApplicationError("applications_required", "source context and at least one application are required")
        if self.actor_user_id is None and not self.actor_service:
            raise ValueApplicationError("actor_required", "a governed actor is required")
        ids = [item.allocation_public_id for item in self.applications]
        keys = [item.idempotency_key for item in self.applications]
        obligations = [item.obligation_public_id for item in self.applications]
        if (len(ids) != len(set(ids)) or len(keys) != len(set(keys))
                or len(obligations) != len(set(obligations))):
            raise ValueApplicationError("duplicate_application_identity", "application identities must be unique")

    def canonical_payload(self):
        return {"schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "command": "apply_unapplied_value",
                "tenant_id": self.tenant_id, "value_source_public_id": str(self.value_source_public_id),
                "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "business_date": self.business_date.isoformat(), "calendar_policy_version": self.calendar_policy_version,
                "correlation_id": str(self.correlation_id), "source_component": self.source_component,
                "idempotency_scope": self.idempotency_scope, "actor_user_id": self.actor_user_id,
                "actor_service": self.actor_service,
                "applications": [item.canonical_payload() for item in self.applications]}

    @property
    def request_fingerprint(self):
        return _fingerprint(self.canonical_payload())


@dataclass(frozen=True)
class ReceiveAndApplyValueCommand:
    value_source: CreateValueSourceCommand
    application_batch: ApplyUnappliedValueCommand | None = None

    def __post_init__(self) -> None:
        if self.application_batch is not None:
            if self.application_batch.tenant_id != self.value_source.tenant_id:
                raise ValueApplicationError("tenant_mismatch", "receipt and application tenant must match")
            if self.application_batch.value_source_public_id != self.value_source.public_id:
                raise ValueApplicationError("source_mismatch", "application batch must name the received source")

    @property
    def request_fingerprint(self):
        return _fingerprint({"schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
                             "command": "receive_and_apply_value",
                             "value_source": self.value_source.canonical_payload(),
                             "application_batch": self.application_batch.canonical_payload() if self.application_batch else None})
