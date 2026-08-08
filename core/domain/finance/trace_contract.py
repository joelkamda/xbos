"""Typed, deterministic read model for one canonical financial-event trace."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID


TRACE_CONTRACT = "XBOS_M26_FINANCIAL_TRACE_EXPLANATION"
TRACE_CONTRACT_VERSION = 1


class FinancialTraceError(RuntimeError):
    """Base failure carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class FinancialTraceValidationError(FinancialTraceError):
    """Raised before an invalid or unscoped trace query reaches persistence."""


class FinancialTraceNotFound(FinancialTraceError):
    """Raised without revealing whether the event exists in another tenant."""


class FinancialTraceIntegrityError(FinancialTraceError):
    """Raised when supposedly authoritative persisted truth is contradictory."""


@dataclass(frozen=True)
class FinancialEventTraceQuery:
    tenant_id: int
    event_public_id: UUID

    def __post_init__(self) -> None:
        try:
            selected_tenant = int(self.tenant_id)
        except (TypeError, ValueError) as exc:
            raise FinancialTraceValidationError(
                "invalid_tenant_scope", "tenant_id must be a positive integer"
            ) from exc
        if selected_tenant <= 0:
            raise FinancialTraceValidationError(
                "invalid_tenant_scope", "tenant_id must be a positive integer"
            )
        try:
            selected_event = UUID(str(self.event_public_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise FinancialTraceValidationError(
                "invalid_event_identity", "event_public_id must be a UUID"
            ) from exc
        object.__setattr__(self, "tenant_id", selected_tenant)
        object.__setattr__(self, "event_public_id", selected_event)


def _decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def json_value(value: Any) -> Any:
    """Convert database-native values to deterministic JSON-safe values."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise FinancialTraceIntegrityError(
                "naive_persisted_timestamp",
                "persisted financial timestamps must be timezone-aware",
            )
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise FinancialTraceIntegrityError(
        "unsupported_persisted_value",
        f"trace contains an unsupported persisted value of type {type(value).__name__}",
    )


def canonical_trace_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class FinancialEventTrace:
    query: FinancialEventTraceQuery
    event: Mapping[str, Any]
    source: Mapping[str, Any]
    idempotency: Mapping[str, Any] | None
    outbox: Mapping[str, Any] | None
    posting: Mapping[str, Any] | None
    correction_lineage: tuple[Mapping[str, Any], ...]
    correlation_peers: tuple[Mapping[str, Any], ...]
    integrity: Mapping[str, Any]
    explanation: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return json_value(
            {
                "schema": TRACE_CONTRACT,
                "schema_version": TRACE_CONTRACT_VERSION,
                "query": {
                    "tenant_id": self.query.tenant_id,
                    "event_public_id": self.query.event_public_id,
                },
                "event": self.event,
                "source": self.source,
                "idempotency": self.idempotency,
                "outbox": self.outbox,
                "posting": self.posting,
                "correction_lineage": self.correction_lineage,
                "correlation_peers": self.correlation_peers,
                "integrity": self.integrity,
                "explanation": self.explanation,
            }
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_trace_bytes(self.as_dict())).hexdigest()

    def envelope(self) -> dict[str, Any]:
        return {**self.as_dict(), "trace_fingerprint": self.fingerprint}
