"""Typed shared M6.4 reconciliation-control commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .operational_balance_contract import _fingerprint, _timestamp_text, evidence_hash

CONTRACT_CODE = "XBOS_M64_BANK_AR_AP_RECONCILIATION_EVIDENCE_AND_REPORTS"
CONTRACT_VERSION = 1
CONTROL_TYPES = frozenset({"bank", "accounts_receivable", "accounts_payable"})
EVIDENCE_TYPES = frozenset({
    "bank_statement", "external_ending_balance", "customer_control_statement",
    "supplier_statement", "remittance_advice", "control_worksheet", "other_control_evidence",
})


class ReconciliationControlError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _text(value, field_name, maximum):
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ReconciliationControlError("invalid_text", f"{field_name} is required and must fit {maximum} characters")
    return normalized


def _uuid(value, field_name):
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ReconciliationControlError("invalid_uuid", f"{field_name} must be a UUID") from exc


def _time(value, field_name):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReconciliationControlError("invalid_time", f"{field_name} must be timezone-aware")
    return value


def _amount(value, field_name, *, nonzero=False):
    try:
        normalized = Decimal(str(value)).quantize(Decimal("0.00000001"))
    except (InvalidOperation, ValueError) as exc:
        raise ReconciliationControlError("invalid_amount", f"{field_name} must be an exact decimal") from exc
    if nonzero and normalized == 0:
        raise ReconciliationControlError("invalid_amount", f"{field_name} cannot be zero")
    return normalized


def _json(value, field_name, *, required=False):
    if not isinstance(value, Mapping) or (required and not value):
        raise ReconciliationControlError("invalid_metadata", f"{field_name} must be a non-empty object" if required else f"{field_name} must be an object")
    return dict(value)


@dataclass(frozen=True)
class ReconciliationExplanation:
    public_id: UUID
    item_type: str
    amount: Decimal
    explanation: str
    canonical_reference_type: str | None = None
    canonical_reference_public_id: UUID | None = None
    evidence_reference: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "public_id", _uuid(self.public_id, "public_id"))
        object.__setattr__(self, "item_type", _text(self.item_type, "item_type", 40).lower())
        object.__setattr__(self, "amount", _amount(self.amount, "amount", nonzero=True))
        object.__setattr__(self, "explanation", _text(self.explanation, "explanation", 300))
        if self.canonical_reference_type is not None:
            object.__setattr__(self, "canonical_reference_type", _text(self.canonical_reference_type, "canonical_reference_type", 40).lower())
        if self.canonical_reference_public_id is not None:
            object.__setattr__(self, "canonical_reference_public_id", _uuid(self.canonical_reference_public_id, "canonical_reference_public_id"))
        if (self.canonical_reference_type is None) != (self.canonical_reference_public_id is None):
            raise ReconciliationControlError("incomplete_canonical_reference", "canonical reference type and identity must be supplied together")
        if self.evidence_reference is not None:
            object.__setattr__(self, "evidence_reference", _text(self.evidence_reference, "evidence_reference", 191))
        object.__setattr__(self, "metadata", _json(self.metadata, "metadata"))

    def canonical_payload(self):
        return {"public_id": str(self.public_id), "item_type": self.item_type, "amount": str(self.amount),
                "explanation": self.explanation, "canonical_reference_type": self.canonical_reference_type,
                "canonical_reference_public_id": str(self.canonical_reference_public_id) if self.canonical_reference_public_id else None,
                "evidence_reference": self.evidence_reference, "metadata": self.metadata}


@dataclass(frozen=True)
class ReconciliationEvidenceReference:
    public_id: UUID
    evidence_type: str
    external_reference: str
    evidence_source: str
    observed_at: datetime
    evidence_payload: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "public_id", _uuid(self.public_id, "public_id"))
        kind = _text(self.evidence_type, "evidence_type", 48).lower()
        if kind not in EVIDENCE_TYPES:
            raise ReconciliationControlError("invalid_evidence_type", "evidence_type is not governed")
        object.__setattr__(self, "evidence_type", kind)
        object.__setattr__(self, "external_reference", _text(self.external_reference, "external_reference", 191))
        object.__setattr__(self, "evidence_source", _text(self.evidence_source, "evidence_source", 120))
        object.__setattr__(self, "observed_at", _time(self.observed_at, "observed_at"))
        object.__setattr__(self, "evidence_payload", _json(self.evidence_payload, "evidence_payload", required=True))
        object.__setattr__(self, "metadata", _json(self.metadata, "metadata"))

    @property
    def evidence_hash(self):
        return evidence_hash(self.evidence_payload)

    def canonical_payload(self):
        return {"public_id": str(self.public_id), "evidence_type": self.evidence_type,
                "external_reference": self.external_reference, "evidence_source": self.evidence_source,
                "observed_at": _timestamp_text(self.observed_at), "evidence_hash": self.evidence_hash,
                "metadata": self.metadata}


@dataclass(frozen=True)
class RecordReconciliationControlCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    control_type: str
    currency_code: str
    period_start: datetime
    period_end: datetime
    as_of: datetime
    control_position: Decimal
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    source_component: str
    source_record_id: str
    idempotency_scope: str
    idempotency_key: str
    operational_account_public_id: UUID | None = None
    party_id: UUID | None = None
    reconciliation_window_public_id: UUID | None = None
    accounting_period_code: str | None = None
    explanations: tuple[ReconciliationExplanation, ...] = ()
    evidence: tuple[ReconciliationEvidenceReference, ...] = ()
    causation_id: UUID | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "public_id", _uuid(self.public_id, "public_id"))
        if self.tenant_id <= 0 or self.organization_unit_id <= 0:
            raise ReconciliationControlError("invalid_scope", "tenant and organization must be positive")
        kind = _text(self.control_type, "control_type", 24).lower()
        if kind not in CONTROL_TYPES:
            raise ReconciliationControlError("invalid_control_type", "control_type is not governed")
        object.__setattr__(self, "control_type", kind)
        currency = _text(self.currency_code, "currency_code", 12).upper()
        object.__setattr__(self, "currency_code", currency)
        for name in ("period_start", "period_end", "as_of", "occurred_at"):
            object.__setattr__(self, name, _time(getattr(self, name), name))
        if not self.period_start < self.period_end or not self.period_start <= self.as_of <= self.period_end:
            raise ReconciliationControlError("invalid_period", "period and as-of bounds are invalid")
        object.__setattr__(self, "control_position", _amount(self.control_position, "control_position"))
        if not isinstance(self.business_date, date) or self.calendar_policy_version <= 0:
            raise ReconciliationControlError("invalid_calendar", "business date and calendar policy are required")
        object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        if self.causation_id is not None:
            object.__setattr__(self, "causation_id", _uuid(self.causation_id, "causation_id"))
        for name, maximum in (("source_component",120),("source_record_id",191),("idempotency_scope",80),("idempotency_key",200)):
            object.__setattr__(self, name, _text(getattr(self, name), name, maximum))
        if self.actor_user_id is None and not str(self.actor_service or "").strip():
            raise ReconciliationControlError("actor_required", "actor user or service is required")
        if self.actor_service is not None:
            object.__setattr__(self, "actor_service", _text(self.actor_service, "actor_service", 120))
        object.__setattr__(self, "explanations", tuple(self.explanations))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if not self.evidence:
            raise ReconciliationControlError("evidence_required", "at least one independent evidence reference is required")
        if len({item.public_id for item in self.explanations}) != len(self.explanations):
            raise ReconciliationControlError("duplicate_explanation", "explanation identities must be unique")
        if len({item.public_id for item in self.evidence}) != len(self.evidence):
            raise ReconciliationControlError("duplicate_evidence", "evidence identities must be unique")
        if kind == "bank":
            if not self.operational_account_public_id or not self.reconciliation_window_public_id or self.party_id is not None:
                raise ReconciliationControlError("invalid_bank_scope", "bank control requires account and window only")
            object.__setattr__(self, "operational_account_public_id", _uuid(self.operational_account_public_id, "operational_account_public_id"))
            object.__setattr__(self, "reconciliation_window_public_id", _uuid(self.reconciliation_window_public_id, "reconciliation_window_public_id"))
        else:
            if not self.party_id or self.operational_account_public_id is not None or self.reconciliation_window_public_id is not None:
                raise ReconciliationControlError("invalid_party_scope", "A/R and A/P controls require party identity only")
            object.__setattr__(self, "party_id", _uuid(self.party_id, "party_id"))
        if self.accounting_period_code is not None:
            object.__setattr__(self, "accounting_period_code", _text(self.accounting_period_code, "accounting_period_code", 32))
        object.__setattr__(self, "metadata", _json(self.metadata, "metadata"))

    def canonical_payload(self):
        return {"schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION, "public_id": str(self.public_id),
                "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
                "control_type": self.control_type, "currency_code": self.currency_code,
                "period_start": _timestamp_text(self.period_start), "period_end": _timestamp_text(self.period_end),
                "as_of": _timestamp_text(self.as_of), "control_position": str(self.control_position),
                "operational_account_public_id": str(self.operational_account_public_id) if self.operational_account_public_id else None,
                "party_id": str(self.party_id) if self.party_id else None,
                "reconciliation_window_public_id": str(self.reconciliation_window_public_id) if self.reconciliation_window_public_id else None,
                "accounting_period_code": self.accounting_period_code,
                "explanations": [item.canonical_payload() for item in self.explanations],
                "evidence": [item.canonical_payload() for item in self.evidence],
                "occurred_at": _timestamp_text(self.occurred_at), "business_date": self.business_date.isoformat(),
                "calendar_policy_version": self.calendar_policy_version, "correlation_id": str(self.correlation_id),
                "causation_id": str(self.causation_id) if self.causation_id else None,
                "actor_user_id": self.actor_user_id, "actor_service": self.actor_service,
                "source_component": self.source_component, "source_record_id": self.source_record_id,
                "idempotency_scope": self.idempotency_scope, "idempotency_key": self.idempotency_key,
                "metadata": self.metadata}

    @property
    def request_fingerprint(self):
        return _fingerprint(self.canonical_payload())
