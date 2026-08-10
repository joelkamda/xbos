"""Typed M5.4 refund, correction, loss, and disposition contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .obligation_contract import TransitionObligationCommand
from .provider_financial_contract import CreateProviderSettlementComponentCommand


CONTRACT_CODE = "XBOS_M54_REFUNDS_CORRECTIONS_AND_LOSS_EVENTS"
CONTRACT_VERSION = 1
DOCUMENT_TYPES = frozenset({"credit_note", "correction_note", "refund_notice", "cancellation_notice", "void_notice", "reversal_notice", "chargeback_notice", "writeoff_notice"})
_HASH = re.compile(r"^[0-9a-f]{64}$")


class CorrectionLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code


def _money(value: Any) -> Decimal:
    try: selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc: raise CorrectionLifecycleError("invalid_amount", "amount must be a finite decimal") from exc
    if not selected.is_finite() or selected <= 0: raise CorrectionLifecycleError("invalid_amount", "amount must be positive")
    return selected


def _uuid(value: Any, name: str) -> UUID:
    try: selected = UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc: raise CorrectionLifecycleError("identity_required", f"{name} must be a valid UUID") from exc
    if selected.int == 0: raise CorrectionLifecycleError("identity_required", f"{name} cannot be nil")
    return selected


@dataclass(frozen=True)
class CorrectionDocumentReference:
    document_type: str
    document_number: str
    evidence_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_type", str(self.document_type).strip().lower())
        object.__setattr__(self, "document_number", str(self.document_number).strip())
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash).strip())
        if self.document_type not in DOCUMENT_TYPES: raise CorrectionLifecycleError("document_type_invalid", "correction document type is not approved")
        if not self.document_number or len(self.document_number) > 80: raise CorrectionLifecycleError("document_number_required", "bounded correction document number is required")
        if not _HASH.fullmatch(self.evidence_hash): raise CorrectionLifecycleError("evidence_hash_invalid", "correction evidence hash must be lowercase sha256")


@dataclass(frozen=True)
class CorrectionContext:
    event_public_id: UUID
    tenant_id: int
    organization_unit_id: int
    source_record_id: int
    amount: Decimal
    currency_code: str
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    idempotency_scope: str
    actor_service: str
    document: CorrectionDocumentReference
    actor_user_id: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_public_id", _uuid(self.event_public_id, "event_public_id")); object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "amount", _money(self.amount)); object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper()); object.__setattr__(self, "metadata", dict(self.metadata))
        if min(int(self.tenant_id), int(self.organization_unit_id), int(self.source_record_id), int(self.calendar_policy_version)) <= 0: raise CorrectionLifecycleError("scope_required", "positive tenant, organization, source, and calendar policy are required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None: raise CorrectionLifecycleError("timezone_required", "occurred_at must be timezone-aware")
        if not self.currency_code or not str(self.idempotency_scope).strip() or not str(self.actor_service).strip(): raise CorrectionLifecycleError("command_identity_required", "currency, idempotency scope, and actor service are required")


@dataclass(frozen=True)
class ClassifyLifecycleDispositionCommand:
    requested_action: str
    financial_event_exists: bool
    finalized_payment_exists: bool
    irreversible_external_effect_exists: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_action", str(self.requested_action).strip().lower())
        if self.requested_action not in {"cancel", "void", "reverse"}: raise CorrectionLifecycleError("disposition_invalid", "requested action must be cancel, void, or reverse")
        if self.requested_action == "cancel" and (self.financial_event_exists or self.finalized_payment_exists): raise CorrectionLifecycleError("cancellation_too_late", "posted or settled truth must be corrected, not cancelled")
        if self.requested_action == "void" and (self.financial_event_exists or self.finalized_payment_exists or self.irreversible_external_effect_exists): raise CorrectionLifecycleError("void_too_late", "final or externally irreversible truth cannot be voided")
        if self.requested_action == "reverse" and not self.financial_event_exists: raise CorrectionLifecycleError("reversal_original_required", "reversal requires an existing financial event")


@dataclass(frozen=True)
class RecognizeRefundCommand:
    context: CorrectionContext
    original_settlement_public_id: UUID
    refund_settlement_public_id: UUID
    refund_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_settlement_public_id", _uuid(self.original_settlement_public_id, "original_settlement_public_id")); object.__setattr__(self, "refund_settlement_public_id", _uuid(self.refund_settlement_public_id, "refund_settlement_public_id"))
        object.__setattr__(self, "refund_reason", str(self.refund_reason).strip().lower())
        if self.context.document.document_type not in {"credit_note", "refund_notice"}: raise CorrectionLifecycleError("refund_document_required", "refund requires a credit note or refund notice")
        if not self.refund_reason: raise CorrectionLifecycleError("refund_reason_required", "refund reason is required")


@dataclass(frozen=True)
class RecognizeCommercialReturnCommand:
    context: CorrectionContext
    original_event_public_id: UUID
    return_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_event_public_id", _uuid(self.original_event_public_id, "original_event_public_id")); object.__setattr__(self, "return_reason", str(self.return_reason).strip().lower())
        if self.context.document.document_type not in {"credit_note", "correction_note"}: raise CorrectionLifecycleError("return_document_required", "commercial return requires a credit or correction note")
        if not self.return_reason: raise CorrectionLifecycleError("return_reason_required", "return reason is required")


@dataclass(frozen=True)
class ReverseFinancialFactCommand:
    context: CorrectionContext
    original_event_public_id: UUID
    reversal_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "original_event_public_id", _uuid(self.original_event_public_id, "original_event_public_id")); object.__setattr__(self, "reversal_reason", str(self.reversal_reason).strip().lower())
        if self.context.document.document_type not in {"reversal_notice", "correction_note"}: raise CorrectionLifecycleError("reversal_document_required", "reversal requires a reversal or correction notice")
        if not self.reversal_reason: raise CorrectionLifecycleError("reversal_reason_required", "reversal reason is required")


@dataclass(frozen=True)
class WriteOffObligationCommand:
    context: CorrectionContext
    obligation_public_id: UUID
    obligation_role: str
    writeoff_reason: str
    transition: TransitionObligationCommand

    def __post_init__(self) -> None:
        object.__setattr__(self, "obligation_public_id", _uuid(self.obligation_public_id, "obligation_public_id")); object.__setattr__(self, "obligation_role", str(self.obligation_role).strip().lower()); object.__setattr__(self, "writeoff_reason", str(self.writeoff_reason).strip().lower())
        if self.obligation_role not in {"receivable", "payable"}: raise CorrectionLifecycleError("obligation_role_invalid", "write-off role must be receivable or payable")
        if self.context.document.document_type != "writeoff_notice": raise CorrectionLifecycleError("writeoff_document_required", "write-off requires a writeoff notice")
        if self.transition.tenant_id != self.context.tenant_id or self.transition.obligation_public_id != self.obligation_public_id or self.transition.target_state != "written_off": raise CorrectionLifecycleError("writeoff_transition_mismatch", "write-off transition must target the same tenant obligation")
        if not self.writeoff_reason: raise CorrectionLifecycleError("writeoff_reason_required", "write-off reason is required")


@dataclass(frozen=True)
class RecognizeChargebackCommand:
    component: CreateProviderSettlementComponentCommand
    document: CorrectionDocumentReference

    def __post_init__(self) -> None:
        if self.component.component_type != "chargeback_loss": raise CorrectionLifecycleError("chargeback_component_required", "chargeback must delegate a chargeback_loss provider component")
        if self.document.document_type != "chargeback_notice": raise CorrectionLifecycleError("chargeback_document_required", "chargeback requires a chargeback notice")
