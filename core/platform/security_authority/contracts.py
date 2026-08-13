"""Immutable PC5 identity, authorization, approval, and audit contracts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ActorType(StrEnum):
    HUMAN = "human"
    SERVICE = "service"
    DEVICE = "device"
    SYSTEM = "system"


class ScopeType(StrEnum):
    PLATFORM = "platform"
    TENANT = "tenant"
    LEGAL_ENTITY = "legal_entity"
    ORGANIZATION_UNIT = "organization_unit"
    LOCATION = "location"


class Lifecycle(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    RETIRED = "retired"


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_STEP_UP = "require_step_up"


@dataclass(frozen=True)
class Identity:
    id: int
    public_id: UUID
    login_name: str
    status: Lifecycle
    party_id: int | None = None


@dataclass(frozen=True)
class Membership:
    id: int
    identity_id: int
    tenant_id: int
    status: Lifecycle
    valid_from: datetime
    valid_to: datetime | None = None
    party_id: int | None = None


@dataclass(frozen=True)
class SessionContext:
    id: int
    public_id: UUID
    identity_id: int
    tenant_id: int | None
    actor_type: ActorType
    assurance_level: int
    authenticated_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    device_identity_id: int | None = None


@dataclass(frozen=True)
class StructuralScope:
    scope_type: ScopeType
    scope_id: int | None


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    owner_module: str
    resource: str
    action: str
    risk_class: str = "ordinary"
    allowed_scopes: tuple[ScopeType, ...] = (ScopeType.TENANT,)
    required_assurance: int = 1
    approval_profile: str | None = None


@dataclass(frozen=True)
class RoleAssignment:
    identity_id: int
    tenant_id: int | None
    role_code: str
    scope: StructuralScope
    valid_from: datetime
    valid_to: datetime | None = None
    actor_type: ActorType = ActorType.HUMAN


@dataclass(frozen=True)
class AuthorizationRequest:
    session_id: UUID
    permission_code: str
    tenant_id: int | None
    target_scope: StructuralScope
    resource_type: str
    resource_id: str
    occurred_at: datetime
    module_available: bool = True
    module_enabled: bool = True
    entitled: bool = True
    feature_active: bool = True
    approval_id: UUID | None = None
    delegation_id: UUID | None = None
    correlation_id: str | None = None
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuthorizationDecision:
    decision: Decision
    permission_code: str
    reason: str
    identity_id: int | None
    tenant_id: int | None
    required_assurance: int = 0
    approval_profile: str | None = None
    evidence_reference: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    public_id: UUID
    tenant_id: int
    requester_identity_id: int
    permission_code: str
    action_fingerprint: str
    scope: StructuralScope
    required_approvals: int
    expires_at: datetime


@dataclass(frozen=True)
class ApprovalDecision:
    approval_id: UUID
    approver_identity_id: int
    approved: bool
    decided_at: datetime
    reason: str


@dataclass(frozen=True)
class SupportAccessGrant:
    public_id: UUID
    operator_identity_id: int
    tenant_id: int
    permission_code: str
    scope: StructuralScope
    effective_from: datetime
    expires_at: datetime
    reason: str
    approval_id: UUID
    break_glass: bool = False


@dataclass(frozen=True)
class AuditEnvelope:
    public_id: UUID
    tenant_id: int | None
    actor_id: int | None
    actor_type: ActorType
    action_code: str
    target_type: str
    target_id: str
    outcome: str
    occurred_at: datetime
    source_module: str
    correlation_id: str
    session_id: UUID | None = None
    authorization_reference: str | None = None
    approval_id: UUID | None = None
    scope: StructuralScope | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None
    prior_evidence_id: UUID | None = None
    delegation_id: UUID | None = None


@dataclass(frozen=True)
class AuditQuery:
    requester_session_id: UUID
    tenant_id: int | None
    start: datetime
    end: datetime
    actor_id: int | None = None
    action_code: str | None = None
    target_type: str | None = None
    correlation_id: str | None = None
    scope: StructuralScope | None = None


@dataclass(frozen=True)
class ServiceIdentity:
    id: int
    public_id: UUID
    service_code: str
    owner_module: str
    tenant_id: int | None
    status: Lifecycle
    credential_reference: str


@dataclass(frozen=True)
class DeviceIdentity:
    id: int
    public_id: UUID
    device_code: str
    tenant_id: int
    status: Lifecycle
    location_id: int | None
    organization_unit_id: int | None
    assurance_level: int
