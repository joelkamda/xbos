"""Side-effect-free WND-to-neutral-finance boundary introduced by M7.0."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol
from uuid import UUID

from .legacy_authority_contract import LegacyAuthorityError


class LegacySourceFamily(str, Enum):
    COMMERCIAL = "commercial"
    PAYMENT = "payment"
    RECEIVABLE = "receivable"
    ADJUSTMENT = "adjustment"
    INVENTORY = "inventory"
    DOCUMENT = "document"
    RECONCILIATION = "reconciliation"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise LegacyAuthorityError("unsupported_source_value", type(value).__name__)


@dataclass(frozen=True)
class LegacyFinancialEnvelope:
    tenant_id: int
    organization_unit_id: int
    source_family: LegacySourceFamily
    source_record_type: str
    source_record_id: str
    source_updated_at: datetime
    business_date: date
    payload: Mapping[str, Any]
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.tenant_id <= 0 or self.organization_unit_id <= 0:
            raise LegacyAuthorityError("invalid_scope", "tenant and organization must be positive")
        if not self.source_record_type.strip() or not self.source_record_id.strip():
            raise LegacyAuthorityError("invalid_source_identity", self.source_record_type)

    @property
    def source_identity(self) -> str:
        return f"{self.source_record_type}:{self.source_record_id}"

    @property
    def payload_fingerprint(self) -> str:
        value = {
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_family": self.source_family.value,
            "source_identity": self.source_identity,
            "source_updated_at": self.source_updated_at,
            "business_date": self.business_date,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
        }
        return hashlib.sha256(json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AdapterAssessment:
    source_identity: str
    payload_fingerprint: str
    mapping_package: str
    canonical_targets: tuple[str, ...]
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        if self.execution_allowed:
            raise LegacyAuthorityError("m70_execution_forbidden", self.source_identity)


class WndFinanceAdapterBoundary(Protocol):
    """M7.0 permits deterministic assessment only; execution arrives later."""

    def assess(self, envelope: LegacyFinancialEnvelope) -> AdapterAssessment: ...
