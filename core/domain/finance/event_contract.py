"""Pure typed contract for one canonical financial-event command."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID


ENGINE_CONTRACT = "XBOS_M21_CANONICAL_EVENT_ENGINE"
ENGINE_CONTRACT_VERSION = 1
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class FinancialEventContractError(RuntimeError):
    """Base class for neutral event-engine contract failures."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class FinancialEventValidationError(FinancialEventContractError):
    """Raised before an invalid command can write a financial fact."""


class FinancialEventIdempotencyConflict(FinancialEventContractError):
    """Raised when one idempotency identity is reused for different content."""


def _clean_json_object(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinancialEventValidationError(
            "invalid_json_object", f"{field_name} must be a JSON object"
        )
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise FinancialEventValidationError(
            "invalid_json_value", f"{field_name} is not valid JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise FinancialEventValidationError(
            "invalid_json_object", f"{field_name} must be a JSON object"
        )
    return decoded


def _decimal(value: Any) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FinancialEventValidationError(
            "invalid_amount", "amount must be a finite decimal"
        ) from exc
    if not selected.is_finite():
        raise FinancialEventValidationError(
            "invalid_amount", "amount must be a finite decimal"
        )
    return selected


def canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FinancialEventValidationError(
            "timezone_required", "occurred_at must be timezone-aware"
        )
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class CanonicalFinancialEventCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    event_type_code: str
    event_version: int
    amount: Decimal
    currency_code: str
    economic_role: str
    source_record_id: int
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    idempotency_scope: str
    idempotency_key: str
    correlation_id: UUID
    classification_snapshot: Mapping[str, Any] = field(default_factory=dict)
    posting_context: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_operational_account_id: int | None = None
    target_operational_account_id: int | None = None
    original_event_id: int | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    causation_id: UUID | None = None
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        if self.causation_id is not None:
            object.__setattr__(self, "causation_id", UUID(str(self.causation_id)))
        object.__setattr__(self, "amount", _decimal(self.amount))
        object.__setattr__(
            self, "event_type_code", str(self.event_type_code).strip().upper()
        )
        object.__setattr__(
            self, "currency_code", str(self.currency_code).strip().upper()
        )
        object.__setattr__(self, "economic_role", str(self.economic_role).strip())
        object.__setattr__(
            self, "idempotency_scope", str(self.idempotency_scope).strip()
        )
        object.__setattr__(
            self, "idempotency_key", str(self.idempotency_key).strip()
        )
        if self.actor_service is not None:
            object.__setattr__(
                self, "actor_service", str(self.actor_service).strip()
            )
        if self.evidence_hash is not None:
            object.__setattr__(
                self, "evidence_hash", str(self.evidence_hash).strip()
            )
        object.__setattr__(
            self,
            "classification_snapshot",
            _clean_json_object(self.classification_snapshot, "classification_snapshot"),
        )
        object.__setattr__(
            self,
            "posting_context",
            _clean_json_object(self.posting_context, "posting_context"),
        )
        object.__setattr__(
            self, "metadata", _clean_json_object(self.metadata, "metadata")
        )

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": ENGINE_CONTRACT,
            "schema_version": ENGINE_CONTRACT_VERSION,
            "public_id": str(self.public_id),
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "event_type_code": self.event_type_code,
            "event_version": self.event_version,
            "amount": canonical_decimal(self.amount),
            "currency_code": self.currency_code,
            "economic_role": self.economic_role,
            "source_operational_account_id": self.source_operational_account_id,
            "target_operational_account_id": self.target_operational_account_id,
            "source_record_id": self.source_record_id,
            "original_event_id": self.original_event_id,
            "occurred_at": canonical_timestamp(self.occurred_at),
            "business_date": self.business_date.isoformat(),
            "calendar_policy_version": self.calendar_policy_version,
            "actor_user_id": self.actor_user_id,
            "actor_service": self.actor_service,
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "classification_snapshot": self.classification_snapshot,
            "posting_context": self.posting_context,
            "evidence_hash": self.evidence_hash,
            "metadata": self.metadata,
        }


def canonical_command_fingerprint(command: CanonicalFinancialEventCommand) -> str:
    return hashlib.sha256(canonical_json_bytes(command.canonical_payload())).hexdigest()


@dataclass(frozen=True)
class CatalogEventPolicy:
    event_type_code: str
    event_version: int
    amount_policy: str
    allowed_economic_roles: tuple[str, ...]
    requires_original_event: bool
    source_record_kinds: tuple[str, ...]
    required_classification_roles: tuple[str, ...]
    operational_account_policy: Mapping[str, Any]
    definition_hash: str | None = None

    @classmethod
    def from_event_definition(cls, event: Mapping[str, Any]) -> "CatalogEventPolicy":
        return cls(
            event_type_code=str(event["event_type_code"]),
            event_version=int(event["event_version"]),
            amount_policy=str(event["amount_policy"]),
            allowed_economic_roles=tuple(event["allowed_economic_roles"]),
            requires_original_event=bool(event["requires_original_event"]),
            source_record_kinds=tuple(event["source_record_kinds"]),
            required_classification_roles=tuple(
                event["required_classification_roles"]
            ),
            operational_account_policy=dict(event["operational_account_policy"]),
        )

    @classmethod
    def from_database_row(cls, row: Mapping[str, Any]) -> "CatalogEventPolicy":
        policy = row["account_role_policy"]
        return cls(
            event_type_code=row["event_type_code"],
            event_version=row["event_version"],
            amount_policy=row["amount_policy"],
            allowed_economic_roles=tuple(policy["allowed_economic_roles"]),
            requires_original_event=bool(policy["requires_original_event"]),
            source_record_kinds=tuple(policy["source_record_kinds"]),
            required_classification_roles=tuple(
                policy["required_classification_roles"]
            ),
            operational_account_policy=policy["operational_account_policy"],
            definition_hash=row["definition_hash"],
        )


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise FinancialEventValidationError(code, message)


def validate_command_structure(command: CanonicalFinancialEventCommand) -> None:
    for field_name in (
        "tenant_id",
        "organization_unit_id",
        "event_version",
        "source_record_id",
        "calendar_policy_version",
    ):
        _require(
            int(getattr(command, field_name)) > 0,
            "positive_identifier_required",
            f"{field_name} must be positive",
        )
    for field_name in (
        "source_operational_account_id",
        "target_operational_account_id",
        "original_event_id",
        "actor_user_id",
    ):
        value = getattr(command, field_name)
        _require(
            value is None or int(value) > 0,
            "positive_identifier_required",
            f"{field_name} must be positive when supplied",
        )

    _require(bool(command.event_type_code), "event_type_required", "event type required")
    _require(
        len(command.event_type_code) <= 80,
        "event_type_too_long",
        "event type exceeds 80 characters",
    )
    _require(bool(command.currency_code), "currency_required", "currency required")
    _require(
        len(command.currency_code) <= 12,
        "currency_code_too_long",
        "currency code exceeds 12 characters",
    )
    _require(bool(command.economic_role), "economic_role_required", "economic role required")
    _require(
        len(command.economic_role) <= 32,
        "economic_role_too_long",
        "economic role exceeds 32 characters",
    )
    _require(
        bool(command.idempotency_scope),
        "idempotency_scope_required",
        "idempotency scope required",
    )
    _require(
        len(command.idempotency_scope) <= 80,
        "idempotency_scope_too_long",
        "idempotency scope exceeds 80 characters",
    )
    _require(
        bool(command.idempotency_key),
        "idempotency_key_required",
        "idempotency key required",
    )
    _require(
        len(command.idempotency_key) <= 200,
        "idempotency_key_too_long",
        "idempotency key exceeds 200 characters",
    )
    _require(
        command.actor_user_id is not None or bool(command.actor_service),
        "actor_required",
        "actor user or service is required",
    )
    _require(
        command.actor_service is None or len(command.actor_service) <= 120,
        "actor_service_too_long",
        "actor service exceeds 120 characters",
    )
    _require(
        isinstance(command.occurred_at, datetime),
        "invalid_occurred_at",
        "occurred_at must be a datetime",
    )
    canonical_timestamp(command.occurred_at)
    _require(
        isinstance(command.business_date, date)
        and not isinstance(command.business_date, datetime),
        "invalid_business_date",
        "business_date must be a date",
    )
    normalized_amount = command.amount.normalize()
    _, digits, exponent = normalized_amount.as_tuple()
    storage_scale = max(-exponent, 0)
    integer_digits = max(len(digits) + exponent, 0)
    _require(
        storage_scale <= 8 and integer_digits <= 16,
        "amount_storage_overflow",
        "amount exceeds NUMERIC(24,8) storage capacity",
    )
    _require(
        "_kernel" not in command.metadata,
        "reserved_metadata_key",
        "metadata key '_kernel' is reserved",
    )
    _require(
        command.evidence_hash is None
        or bool(_HASH_PATTERN.fullmatch(command.evidence_hash)),
        "invalid_evidence_hash",
        "evidence_hash must be lowercase SHA-256",
    )


def _validate_account_presence(
    command: CanonicalFinancialEventCommand,
    policy: Mapping[str, Any],
) -> None:
    mode = policy.get("mode", "fixed")
    source = command.source_operational_account_id
    target = command.target_operational_account_id

    if mode == "none":
        _require(
            source is None and target is None,
            "accounts_forbidden",
            "event policy forbids operational accounts",
        )
        return
    if mode == "inverse_original":
        return
    if mode == "by_economic_role":
        selected = policy["mappings"].get(command.economic_role)
        _require(
            isinstance(selected, Mapping),
            "economic_role_account_policy_missing",
            "no operational account policy exists for the economic role",
        )
        _validate_account_presence(command, selected)
        return
    if mode == "classification_dependent":
        _require(
            not policy.get("at_least_one_of_source_or_target")
            or source is not None
            or target is not None,
            "operational_account_required",
            "at least one operational account is required",
        )
        return
    if mode != "fixed":
        raise FinancialEventValidationError(
            "unsupported_account_policy", f"unsupported account policy mode {mode!r}"
        )

    for side, value in (("source", source), ("target", target)):
        requirement = policy.get(side, "optional")
        if requirement == "required":
            _require(
                value is not None,
                "operational_account_required",
                f"{side} operational account is required",
            )
        elif requirement == "forbidden":
            _require(
                value is None,
                "operational_account_forbidden",
                f"{side} operational account is forbidden",
            )
    _require(
        not policy.get("different_accounts")
        or source is None
        or target is None
        or source != target,
        "accounts_must_differ",
        "source and target operational accounts must differ",
    )


def validate_command_against_policy(
    command: CanonicalFinancialEventCommand,
    policy: CatalogEventPolicy,
) -> None:
    _require(
        (command.event_type_code, command.event_version)
        == (policy.event_type_code, policy.event_version),
        "catalog_identity_mismatch",
        "command event identity does not match catalog policy",
    )
    if policy.amount_policy == "positive":
        _require(command.amount > 0, "amount_policy_violation", "amount must be positive")
    elif policy.amount_policy == "nonzero":
        _require(command.amount != 0, "amount_policy_violation", "amount must be nonzero")
    elif policy.amount_policy != "zero_allowed":
        raise FinancialEventValidationError(
            "unsupported_amount_policy", "catalog amount policy is unsupported"
        )

    _require(
        command.economic_role in policy.allowed_economic_roles,
        "economic_role_not_allowed",
        "economic role is not allowed for the event type",
    )
    if policy.requires_original_event:
        _require(
            command.original_event_id is not None,
            "original_event_required",
            "event policy requires an original event",
        )
    else:
        _require(
            command.original_event_id is None,
            "original_event_forbidden",
            "event policy does not permit an original event",
        )

    missing_roles = sorted(
        set(policy.required_classification_roles)
        - set(command.classification_snapshot)
    )
    _require(
        not missing_roles,
        "classification_roles_missing",
        f"missing classification roles: {', '.join(missing_roles)}",
    )
    _validate_account_presence(command, policy.operational_account_policy)
