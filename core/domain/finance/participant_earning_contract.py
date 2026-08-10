"""Typed M5.3 tip and commission recognition contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .obligation_contract import CreateObligationCommand


CONTRACT_CODE = "XBOS_M53_TIPS_AND_COMMISSIONS"
CONTRACT_VERSION = 1
TIP_POLICIES = frozenset({"staff_beneficiary", "tenant_income"})
COMMISSION_BASIS_TYPES = frozenset({"fixed", "percentage"})


class ParticipantEarningError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _money(value: Any, name: str, *, allow_zero: bool = False) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ParticipantEarningError("invalid_amount", f"{name} must be a finite decimal") from exc
    if not selected.is_finite() or selected < 0 or (not allow_zero and selected == 0):
        raise ParticipantEarningError("invalid_amount", f"{name} must be positive")
    return selected


def _identity(value: Any, name: str) -> UUID:
    try:
        selected = UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ParticipantEarningError("identity_required", f"{name} must be a valid UUID") from exc
    if selected.int == 0:
        raise ParticipantEarningError("identity_required", f"{name} cannot be nil")
    return selected


@dataclass(frozen=True)
class EarningContext:
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
    actor_user_id: int | None = None
    evidence_hash: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_public_id", _identity(self.event_public_id, "event_public_id"))
        object.__setattr__(self, "correlation_id", _identity(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "amount", _money(self.amount, "amount"))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "metadata", dict(self.metadata))
        if min(int(self.tenant_id), int(self.organization_unit_id), int(self.source_record_id), int(self.calendar_policy_version)) <= 0:
            raise ParticipantEarningError("scope_required", "positive tenant, organization, source, and calendar policy are required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ParticipantEarningError("timezone_required", "occurred_at must be timezone-aware")
        if not self.currency_code or not str(self.idempotency_scope).strip() or not str(self.actor_service).strip():
            raise ParticipantEarningError("command_identity_required", "currency, idempotency scope, and actor service are required")


def _validate_payable(context: EarningContext, payable: CreateObligationCommand, beneficiary: UUID, earning_type: str) -> None:
    if payable.tenant_id != context.tenant_id or payable.organization_unit_id != context.organization_unit_id:
        raise ParticipantEarningError("payable_scope_mismatch", "earning and payable scopes must match")
    if payable.currency_code != context.currency_code or payable.original_amount != context.amount:
        raise ParticipantEarningError("payable_amount_mismatch", "earning and payable currency and amount must match")
    if payable.creditor_party_id != beneficiary or payable.obligation_type != "expense_payable":
        raise ParticipantEarningError("beneficiary_payable_mismatch", "expense payable creditor must be the earning beneficiary")
    if payable.occurred_at != context.occurred_at or payable.business_date != context.business_date:
        raise ParticipantEarningError("payable_time_mismatch", "earning and payable recognition dates must match")
    metadata = payable.metadata
    if metadata.get("earning_type") != earning_type or str(metadata.get("beneficiary_party_id")) != str(beneficiary):
        raise ParticipantEarningError("payable_metadata_mismatch", "payable must preserve earning type and beneficiary identity")


@dataclass(frozen=True)
class RecognizeTipCommand:
    context: EarningContext
    tip_policy: str
    beneficiary_party_id: UUID | None = None
    payable: CreateObligationCommand | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tip_policy", str(self.tip_policy).strip().lower())
        if self.tip_policy not in TIP_POLICIES:
            raise ParticipantEarningError("tip_policy_invalid", "tip policy must be staff_beneficiary or tenant_income")
        if self.tip_policy == "staff_beneficiary":
            beneficiary = _identity(self.beneficiary_party_id, "beneficiary_party_id")
            object.__setattr__(self, "beneficiary_party_id", beneficiary)
            if self.payable is None:
                raise ParticipantEarningError("tip_payable_required", "staff-beneficiary tip requires a governed payable")
            _validate_payable(self.context, self.payable, beneficiary, "tip")
        elif self.beneficiary_party_id is not None or self.payable is not None:
            raise ParticipantEarningError("tenant_income_payable_forbidden", "tenant-income tip cannot create a participant payable")


@dataclass(frozen=True)
class CommissionBasis:
    basis_type: str
    basis_amount: Decimal
    rate_percent: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "basis_type", str(self.basis_type).strip().lower())
        object.__setattr__(self, "basis_amount", _money(self.basis_amount, "basis_amount"))
        object.__setattr__(self, "rate_percent", _money(self.rate_percent, "rate_percent", allow_zero=True))
        if self.basis_type not in COMMISSION_BASIS_TYPES:
            raise ParticipantEarningError("commission_basis_invalid", "commission basis must be fixed or percentage")
        if self.basis_type == "percentage" and not (Decimal("0") < self.rate_percent <= Decimal("100")):
            raise ParticipantEarningError("commission_rate_invalid", "percentage commission rate must be greater than zero and at most 100")
        if self.basis_type == "fixed" and self.rate_percent != 0:
            raise ParticipantEarningError("commission_rate_invalid", "fixed commission cannot carry a percentage rate")


@dataclass(frozen=True)
class RecognizeCommissionCommand:
    context: EarningContext
    beneficiary_party_id: UUID
    commission_basis: CommissionBasis
    payable: CreateObligationCommand
    commission_code: str

    def __post_init__(self) -> None:
        beneficiary = _identity(self.beneficiary_party_id, "beneficiary_party_id")
        object.__setattr__(self, "beneficiary_party_id", beneficiary)
        object.__setattr__(self, "commission_code", str(self.commission_code).strip().lower())
        if not self.commission_code:
            raise ParticipantEarningError("commission_code_required", "commission code is required")
        if self.commission_basis.basis_type == "percentage":
            expected = self.commission_basis.basis_amount * self.commission_basis.rate_percent / Decimal("100")
            if expected != self.context.amount:
                raise ParticipantEarningError("commission_calculation_mismatch", "commission amount does not equal basis times rate")
        elif self.commission_basis.basis_amount != self.context.amount:
            raise ParticipantEarningError("commission_calculation_mismatch", "fixed commission basis must equal commission amount")
        _validate_payable(self.context, self.payable, beneficiary, "commission")
