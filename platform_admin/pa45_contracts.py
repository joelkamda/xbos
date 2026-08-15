"""PA4-PA5 support, recovery, delegated administration and health contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class SupportAccessMode(StrEnum):
    DELEGATED = "delegated"
    BREAK_GLASS = "break_glass"


class SupportSessionState(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    REVOKED = "revoked"


class RecoveryCaseState(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class RecoveryActionOutcome(StrEnum):
    RECORDED = "recorded"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OpenSupportSession:
    command_key: str
    tenant_id: int
    actor_identity_id: UUID
    access_mode: SupportAccessMode
    scopes: tuple[str, ...]
    reason: str
    starts_at: datetime
    expires_at: datetime
    authorization_reference: str
    step_up_reference: str | None = None
    break_glass_evidence_reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionSupportSession:
    command_key: str
    tenant_id: int
    support_session_id: UUID
    target: SupportSessionState
    expected_row_version: int
    reason: str


@dataclass(frozen=True)
class RecordSupportAction:
    command_key: str
    tenant_id: int
    support_session_id: UUID
    action_code: str
    target_reference: str
    evidence_reference: str
    occurred_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SupportSessionRecord:
    public_id: UUID
    tenant_id: int
    actor_identity_id: UUID
    access_mode: SupportAccessMode
    scopes: tuple[str, ...]
    reason: str
    state: SupportSessionState
    row_version: int
    starts_at: datetime
    expires_at: datetime
    authorization_reference: str
    step_up_reference: str | None
    break_glass_evidence_reference: str | None


@dataclass(frozen=True)
class SupportActionRecord:
    public_id: UUID
    tenant_id: int
    support_session_id: UUID
    action_code: str
    target_reference: str
    evidence_reference: str
    occurred_at: datetime


@dataclass(frozen=True)
class OpenRecoveryCase:
    command_key: str
    tenant_id: int
    case_key: str
    problem_code: str
    subject_reference: str
    reason: str
    opened_by_identity_id: UUID
    evidence_reference: str


@dataclass(frozen=True)
class RecordRecoveryAction:
    command_key: str
    tenant_id: int
    recovery_case_id: UUID
    action_code: str
    outcome: RecoveryActionOutcome
    evidence_reference: str
    occurred_at: datetime
    support_session_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionRecoveryCase:
    command_key: str
    tenant_id: int
    recovery_case_id: UUID
    target: RecoveryCaseState
    expected_row_version: int
    reason: str
    evidence_reference: str


@dataclass(frozen=True)
class RecoveryCaseRecord:
    public_id: UUID
    tenant_id: int
    case_key: str
    problem_code: str
    subject_reference: str
    reason: str
    opened_by_identity_id: UUID
    evidence_reference: str
    state: RecoveryCaseState
    row_version: int


@dataclass(frozen=True)
class RecoveryActionRecord:
    public_id: UUID
    tenant_id: int
    recovery_case_id: UUID
    support_session_id: UUID | None
    action_code: str
    outcome: RecoveryActionOutcome
    evidence_reference: str
    occurred_at: datetime


@dataclass(frozen=True)
class HealthCheck:
    check_code: str
    status: HealthStatus
    evidence_reference: str
    observed_at: datetime


@dataclass(frozen=True)
class CaptureMerchantHealth:
    command_key: str
    tenant_id: int


@dataclass(frozen=True)
class CapturePlatformHealth:
    command_key: str


@dataclass(frozen=True)
class HealthSnapshotRecord:
    public_id: UUID
    scope_type: str
    tenant_id: int | None
    status: HealthStatus
    snapshot_sha256: str
    checks: tuple[HealthCheck, ...]
    recorded_at: datetime
