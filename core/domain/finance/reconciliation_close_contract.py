"""Typed M6.3 formal-close and governed-reopen commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping
from uuid import UUID

from .operational_balance_contract import _fingerprint, _timestamp_text, evidence_hash
from .reconciliation_window_contract import (
    ReconciliationWindowValidationError,
    _common,
    _raise_text,
    _raise_time,
    _uuid,
)

CONTRACT_CODE = "XBOS_M63_FORMAL_CLOSE_REOPEN_AND_CLOSED_PERIOD_GOVERNANCE"
CONTRACT_VERSION = 1
CLOSE_DISPOSITIONS = frozenset({"balanced", "explained_variance", "approved_exception"})


class ReconciliationCloseValidationError(ReconciliationWindowValidationError):
    """Raised before an invalid close transition reaches persistence."""


def _normalize_common(command) -> None:
    try:
        _common(command, evidence=True)
        _uuid(command, "reconciliation_window_public_id")
        object.__setattr__(command, "accounting_period_code", _raise_text(
            command.accounting_period_code, "accounting_period_code", 32,
        ))
        object.__setattr__(command, "transition_reason", _raise_text(
            command.transition_reason, "transition_reason", 80,
        ).lower())
    except ReconciliationCloseValidationError:
        raise
    except ReconciliationWindowValidationError as exc:
        raise ReconciliationCloseValidationError(exc.code, str(exc)) from exc
    if command.governed_revision_number <= 0:
        raise ReconciliationCloseValidationError("invalid_revision", "governed_revision_number must be positive")


def _payload(command, transition_type: str) -> dict[str, Any]:
    return {
        "schema": CONTRACT_CODE,
        "schema_version": CONTRACT_VERSION,
        "command": transition_type,
        "public_id": str(command.public_id),
        "tenant_id": command.tenant_id,
        "organization_unit_id": command.organization_unit_id,
        "reconciliation_window_public_id": str(command.reconciliation_window_public_id),
        "governed_revision_number": command.governed_revision_number,
        "accounting_period_code": command.accounting_period_code,
        "transition_reason": command.transition_reason,
        "evidence_payload": command.evidence_payload,
        "occurred_at": _timestamp_text(command.occurred_at),
        "business_date": command.business_date.isoformat(),
        "calendar_policy_version": command.calendar_policy_version,
        "correlation_id": str(command.correlation_id),
        "causation_id": str(command.causation_id) if command.causation_id else None,
        "actor_user_id": command.actor_user_id,
        "actor_service": command.actor_service,
        "source_component": command.source_component,
        "source_record_id": command.source_record_id,
        "idempotency_scope": command.idempotency_scope,
        "idempotency_key": command.idempotency_key,
        "metadata": command.metadata,
    }


@dataclass(frozen=True)
class CloseReconciliationWindowCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    reconciliation_window_public_id: UUID
    governed_revision_number: int
    accounting_period_code: str
    close_disposition: str
    transition_reason: str
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
        _normalize_common(self)
        disposition = str(self.close_disposition).strip().lower()
        if disposition not in CLOSE_DISPOSITIONS:
            raise ReconciliationCloseValidationError("invalid_close_disposition", "close_disposition is not governed")
        object.__setattr__(self, "close_disposition", disposition)

    def canonical_payload(self) -> dict[str, Any]:
        value = _payload(self, "close_reconciliation_window")
        value["close_disposition"] = self.close_disposition
        return value

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)


@dataclass(frozen=True)
class ReopenReconciliationWindowCommand:
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    reconciliation_window_public_id: UUID
    governed_revision_number: int
    accounting_period_code: str
    prior_close_public_id: UUID
    transition_reason: str
    evidence_payload: Mapping[str, Any]
    approved_by_user_id: int
    approved_at: datetime
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
        _normalize_common(self)
        try:
            _uuid(self, "prior_close_public_id")
            object.__setattr__(self, "approved_at", _raise_time(self.approved_at, "approved_at"))
        except ReconciliationWindowValidationError as exc:
            raise ReconciliationCloseValidationError(exc.code, str(exc)) from exc
        if self.approved_by_user_id <= 0:
            raise ReconciliationCloseValidationError("approval_required", "approved_by_user_id must be positive")
        if self.approved_at > self.occurred_at:
            raise ReconciliationCloseValidationError("approval_after_transition", "approval cannot follow reopen occurrence")

    def canonical_payload(self) -> dict[str, Any]:
        value = _payload(self, "reopen_reconciliation_window")
        value.update({
            "prior_close_public_id": str(self.prior_close_public_id),
            "approved_by_user_id": self.approved_by_user_id,
            "approved_at": _timestamp_text(self.approved_at),
        })
        return value

    @property
    def request_fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    @property
    def evidence_hash(self) -> str:
        return evidence_hash(self.evidence_payload)
