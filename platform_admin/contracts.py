"""PA0-PA3 merchant lifecycle, commercial administration, usage and onboarding contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


class MerchantAdministrationState(StrEnum):
    REGISTERED = "registered"
    ONBOARDING = "onboarding"
    READY = "ready"
    OPERATIONAL = "operational"
    OFFBOARDING = "offboarding"
    CLOSED = "closed"


class SubscriptionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class OnboardingStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    READY = "ready"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class ReadinessStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True)
class PlanQuota:
    meter_code: str
    limit: Decimal


@dataclass(frozen=True)
class PlanDefinition:
    plan_code: str
    version: str
    owner_code: str
    entitlement_codes: tuple[str, ...] = ()
    quotas: tuple[PlanQuota, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegisterMerchant:
    command_key: str
    tenant_id: int
    external_reference: str | None = None


@dataclass(frozen=True)
class TransitionMerchant:
    command_key: str
    tenant_id: int
    target: MerchantAdministrationState
    expected_row_version: int
    reason: str


@dataclass(frozen=True)
class RegisterPlanVersion:
    command_key: str
    plan: PlanDefinition


@dataclass(frozen=True)
class StartSubscription:
    command_key: str
    tenant_id: int
    plan_code: str
    version: str
    starts_at: datetime
    ends_at: datetime | None = None


@dataclass(frozen=True)
class TransitionSubscription:
    command_key: str
    tenant_id: int
    target: SubscriptionStatus
    expected_row_version: int
    reason: str


@dataclass(frozen=True)
class RecordUsage:
    command_key: str
    tenant_id: int
    event_key: str
    meter_code: str
    quantity: Decimal
    period_key: str
    occurred_at: datetime
    source_reference: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StartOnboarding:
    command_key: str
    tenant_id: int
    template_code: str
    template_version: str
    plan_code: str
    plan_version: str


@dataclass(frozen=True)
class EvaluateReadiness:
    command_key: str
    tenant_id: int
    expected_row_version: int


@dataclass(frozen=True)
class CompleteOnboarding:
    command_key: str
    tenant_id: int
    expected_row_version: int


@dataclass(frozen=True)
class MerchantAdministrationRecord:
    public_id: UUID
    tenant_id: int
    state: MerchantAdministrationState
    row_version: int
    external_reference: str | None


@dataclass(frozen=True)
class PlanVersionRecord:
    public_id: UUID
    plan_code: str
    version: str
    plan_sha256: str
    entitlement_codes: tuple[str, ...]
    quotas: tuple[PlanQuota, ...]


@dataclass(frozen=True)
class SubscriptionRecord:
    public_id: UUID
    tenant_id: int
    plan_code: str
    version: str
    status: SubscriptionStatus
    row_version: int
    starts_at: datetime
    ends_at: datetime | None
    entitlement_projection: tuple[str, ...]


@dataclass(frozen=True)
class UsageRecord:
    public_id: UUID
    tenant_id: int
    event_key: str
    meter_code: str
    quantity: Decimal
    period_key: str
    occurred_at: datetime


@dataclass(frozen=True)
class QuotaStatus:
    tenant_id: int
    meter_code: str
    period_key: str
    used: Decimal
    limit: Decimal | None
    exceeded: bool


@dataclass(frozen=True)
class ReadinessCheck:
    check_code: str
    status: ReadinessStatus
    evidence_reference: str


@dataclass(frozen=True)
class OnboardingRecord:
    public_id: UUID
    tenant_id: int
    template_code: str
    template_version: str
    plan_code: str
    plan_version: str
    status: OnboardingStatus
    row_version: int
    readiness_sha256: str | None
    checks: tuple[ReadinessCheck, ...] = ()
