"""Schema-neutral IA0 neutral interaction authority contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


RESERVED_MIGRATION_REVISION = "ia0_neutral_interaction_authority_045"

CANONICAL_PRIMITIVES = (
    "ExternalChannelIdentity",
    "Conversation",
    "ConversationParticipant",
    "InteractionSession",
    "InteractionMessage",
    "InteractionIntent",
    "InteractionHandoff",
    "InteractionEvent",
    "InteractionCapabilityGrant",
    "InteractionContextBinding",
)

AUTHORITY_BOUNDARIES = {
    "party": "PC2",
    "authentication": "PC5",
    "employee_membership": "PC5",
    "workflow_task": "SO6",
    "document_file": "SO7",
    "transport_delivery": "SO8",
    "payment_economic_truth": "NEUTRAL_FINANCE",
    "provider_execution": "XAFPAY_GATEWAY",
    "domain_business_truth": "DOMAIN_OWNER",
    "frontend_business_truth": "NONE",
}

AI_ALLOWED_ACTIONS = frozenset(
    {
        "observe_scoped_context",
        "classify",
        "extract",
        "summarize",
        "propose_intent",
        "propose_command_parameters",
        "generate_response_proposal",
        "request_domain_action",
        "request_human_review",
    }
)

AI_FORBIDDEN_ACTIONS = frozenset(
    {
        "self_grant_capability",
        "fuzzy_create_party_identity",
        "declare_authentication_success",
        "declare_payment_success",
        "write_finance",
        "write_inventory",
        "write_domain_tables",
        "bypass_public_domain_contracts",
    }
)


class ExternalChannelIdentityStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ConversationStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ParticipantKind(StrEnum):
    EXTERNAL_CHANNEL_IDENTITY = "external_channel_identity"
    PARTY_REFERENCE = "party_reference"
    PC5_IDENTITY_REFERENCE = "pc5_identity_reference"
    SERVICE_IDENTITY_REFERENCE = "service_identity_reference"
    AI_PARTICIPANT = "ai_participant"
    SYSTEM_PARTICIPANT = "system_participant"


class InteractionSessionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CLOSED = "closed"


class IdentityResolutionState(StrEnum):
    UNRESOLVED = "unresolved"
    CHANNEL_IDENTIFIED = "channel_identified"
    PARTY_RESOLVED = "party_resolved"


class VerificationState(StrEnum):
    UNVERIFIED = "unverified"
    CHANNEL_VERIFIED = "channel_verified"
    AUTHENTICATED_EXTERNAL = "authenticated_external"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"


class InteractionContentKind(StrEnum):
    TEXT = "text"
    STRUCTURED_DATA = "structured_data"
    DOCUMENT_REFERENCE = "document_reference"
    IMAGE_REFERENCE = "image_reference"
    AUDIO_REFERENCE = "audio_reference"
    VIDEO_REFERENCE = "video_reference"
    LOCATION_REFERENCE = "location_reference"
    DOMAIN_OBJECT_REFERENCE = "domain_object_reference"


class InteractionIntentStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class InteractionHandoffStatus(StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CLOSED = "closed"


class InteractionCapabilityStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


def _require_tenant(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or tenant_id <= 0:
        raise ValueError("tenant_id_required")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}_required")


def _validate_sha256(value: str | None) -> None:
    if value is None:
        return
    lowered = value.lower()
    if len(lowered) != 64 or any(ch not in "0123456789abcdef" for ch in lowered):
        raise ValueError("invalid_sha256")


@dataclass(frozen=True)
class PublicAuthorityReference:
    authority: str
    reference: str

    def __post_init__(self) -> None:
        _require_text(self.authority, "authority")
        _require_text(self.reference, "reference")


@dataclass(frozen=True)
class AIExecutionReferences:
    model_run_reference: str | None = None
    agent_run_reference: str | None = None
    tool_invocation_reference: str | None = None
    tool_result_reference: str | None = None


@dataclass(frozen=True)
class InteractionProvenance:
    proposer_participant_public_id: UUID | None = None
    source_reference: PublicAuthorityReference | None = None
    ai_execution: AIExecutionReferences | None = None


@dataclass(frozen=True)
class InteractionContentPart:
    kind: InteractionContentKind
    text: str | None = None
    reference: PublicAuthorityReference | None = None
    media_type: str | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        if self.text is None and self.reference is None:
            raise ValueError("interaction_content_value_required")
        if self.kind is InteractionContentKind.TEXT and not self.text:
            raise ValueError("text_content_required")
        if self.kind in {
            InteractionContentKind.DOCUMENT_REFERENCE,
            InteractionContentKind.IMAGE_REFERENCE,
            InteractionContentKind.AUDIO_REFERENCE,
            InteractionContentKind.VIDEO_REFERENCE,
        } and self.reference is None:
            raise ValueError("durable_media_reference_required")
        _validate_sha256(self.sha256)


@dataclass(frozen=True)
class PublicDomainCommandBridge:
    target_authority: str
    public_command: str
    intent_code: str
    request_reference: str | None = None
    result_reference: PublicAuthorityReference | None = None
    correlation_id: UUID | None = None
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_text(self.target_authority, "target_authority")
        _require_text(self.public_command, "public_command")
        _require_text(self.intent_code, "intent_code")


@dataclass(frozen=True)
class ExternalChannelIdentity:
    tenant_id: int
    public_id: UUID
    channel_kind: str
    source_code: str
    opaque_subject: str
    status: ExternalChannelIdentityStatus
    resolution_state: IdentityResolutionState
    party_reference: PublicAuthorityReference | None = None
    resolution_provenance: PublicAuthorityReference | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        _require_text(self.channel_kind, "channel_kind")
        _require_text(self.source_code, "source_code")
        _require_text(self.opaque_subject, "opaque_subject")
        if self.resolution_state is IdentityResolutionState.PARTY_RESOLVED and self.party_reference is None:
            raise ValueError("party_reference_required_when_resolved")
        if self.resolution_state is not IdentityResolutionState.PARTY_RESOLVED and self.party_reference is not None:
            raise ValueError("party_reference_requires_resolved_state")


@dataclass(frozen=True)
class Conversation:
    tenant_id: int
    public_id: UUID
    status: ConversationStatus
    opened_at: datetime
    correlation_id: UUID
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        if self.status is ConversationStatus.CLOSED and self.closed_at is None:
            raise ValueError("closed_conversation_requires_closed_at")
        if self.status is ConversationStatus.OPEN and self.closed_at is not None:
            raise ValueError("open_conversation_cannot_have_closed_at")


@dataclass(frozen=True)
class ConversationParticipant:
    tenant_id: int
    public_id: UUID
    conversation_public_id: UUID
    kind: ParticipantKind
    actor_reference: PublicAuthorityReference
    joined_at: datetime
    left_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        if self.left_at is not None and self.left_at < self.joined_at:
            raise ValueError("participant_left_before_joined")


@dataclass(frozen=True)
class InteractionSession:
    tenant_id: int
    public_id: UUID
    conversation_public_id: UUID
    participant_public_id: UUID
    status: InteractionSessionStatus
    identity_resolution_state: IdentityResolutionState
    verification_state: VerificationState
    started_at: datetime
    correlation_id: UUID
    expires_at: datetime | None = None
    closed_at: datetime | None = None
    authentication_reference: PublicAuthorityReference | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        if self.status is InteractionSessionStatus.CLOSED and self.closed_at is None:
            raise ValueError("closed_session_requires_closed_at")
        if self.status is InteractionSessionStatus.ACTIVE and self.closed_at is not None:
            raise ValueError("active_session_cannot_have_closed_at")
        if self.verification_state is VerificationState.AUTHENTICATED_EXTERNAL and self.authentication_reference is None:
            raise ValueError("authenticated_external_requires_auth_reference")


@dataclass(frozen=True)
class InteractionMessage:
    tenant_id: int
    public_id: UUID
    conversation_public_id: UUID
    direction: MessageDirection
    occurred_at: datetime
    correlation_id: UUID
    content: tuple[InteractionContentPart, ...]
    interaction_session_public_id: UUID | None = None
    participant_public_id: UUID | None = None
    transport_reference: PublicAuthorityReference | None = None
    artifact_references: tuple[PublicAuthorityReference, ...] = ()
    provenance: InteractionProvenance | None = None
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        if not self.content:
            raise ValueError("interaction_message_content_required")


@dataclass(frozen=True)
class InteractionIntent:
    tenant_id: int
    public_id: UUID
    conversation_public_id: UUID
    intent_code: str
    status: InteractionIntentStatus
    occurred_at: datetime
    correlation_id: UUID
    interaction_session_public_id: UUID | None = None
    source_message_public_id: UUID | None = None
    proposal_provenance: InteractionProvenance | None = None
    validation_outcome: str | None = None
    domain_bridge: PublicDomainCommandBridge | None = None
    result_reference: PublicAuthorityReference | None = None
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        _require_text(self.intent_code, "intent_code")
        if self.status in {
            InteractionIntentStatus.ACCEPTED,
            InteractionIntentStatus.EXECUTED,
            InteractionIntentStatus.FAILED,
        } and self.domain_bridge is None:
            raise ValueError("accepted_or_terminal_intent_requires_public_domain_bridge")
        if self.status is InteractionIntentStatus.EXECUTED and self.result_reference is None:
            raise ValueError("executed_intent_requires_result_reference")


@dataclass(frozen=True)
class InteractionHandoff:
    tenant_id: int
    public_id: UUID
    conversation_public_id: UUID
    status: InteractionHandoffStatus
    requested_at: datetime
    correlation_id: UUID
    interaction_session_public_id: UUID | None = None
    intent_public_id: UUID | None = None
    workflow_reference: PublicAuthorityReference | None = None
    task_reference: PublicAuthorityReference | None = None
    accepted_at: datetime | None = None
    closed_at: datetime | None = None
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        if self.status in {InteractionHandoffStatus.ACCEPTED, InteractionHandoffStatus.CLOSED} and self.workflow_reference is None:
            raise ValueError("accepted_handoff_requires_workflow_reference")


@dataclass(frozen=True)
class InteractionEvent:
    tenant_id: int
    public_id: UUID
    conversation_public_id: UUID
    event_type: str
    source_reference: PublicAuthorityReference
    correlation_id: UUID
    occurred_at: datetime
    interaction_session_public_id: UUID | None = None
    participant_public_id: UUID | None = None
    message_public_id: UUID | None = None
    intent_public_id: UUID | None = None
    handoff_public_id: UUID | None = None
    causation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        _require_text(self.event_type, "event_type")


@dataclass(frozen=True)
class InteractionCapabilityGrant:
    tenant_id: int
    public_id: UUID
    subject_participant_public_id: UUID
    capability_code: str
    scope: str
    issuer_reference: PublicAuthorityReference
    status: InteractionCapabilityStatus
    effective_from: datetime
    provenance: PublicAuthorityReference
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        _require_text(self.capability_code, "capability_code")
        _require_text(self.scope, "scope")
        if self.expires_at is not None and self.expires_at <= self.effective_from:
            raise ValueError("capability_expiry_must_follow_effective_from")
        if self.status is InteractionCapabilityStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked_capability_requires_revoked_at")


@dataclass(frozen=True)
class InteractionContextBinding:
    tenant_id: int
    public_id: UUID
    interaction_session_public_id: UUID
    source_reference: PublicAuthorityReference
    purpose_code: str
    provenance: PublicAuthorityReference
    effective_from: datetime
    participant_public_id: UUID | None = None
    source_version: str | None = None
    source_hash: str | None = None
    expires_at: datetime | None = None
    ended_at: datetime | None = None
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)
        _require_text(self.purpose_code, "purpose_code")
        _validate_sha256(self.source_hash)
        if self.expires_at is not None and self.expires_at <= self.effective_from:
            raise ValueError("context_expiry_must_follow_effective_from")
        if self.ended_at is not None and self.ended_at < self.effective_from:
            raise ValueError("context_ended_before_effective_from")


@dataclass(frozen=True)
class ExternalTrustProjection:
    tenant_id: int
    interaction_session_public_id: UUID
    participant_public_id: UUID
    identity_resolution_state: IdentityResolutionState
    verification_state: VerificationState
    capability_codes: tuple[str, ...]
    authentication_reference: PublicAuthorityReference | None = None

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)


@dataclass(frozen=True)
class InteractionTimelineProjection:
    tenant_id: int
    conversation_public_id: UUID
    events: tuple[InteractionEvent, ...]

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id)


@dataclass(frozen=True)
class InteractionCommand:
    command_key: str
    tenant_id: int

    def __post_init__(self) -> None:
        _require_text(self.command_key, "command_key")
        _require_tenant(self.tenant_id)

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegisterExternalChannelIdentity(InteractionCommand):
    channel_kind: str
    source_code: str
    opaque_subject: str
    occurred_at: datetime


@dataclass(frozen=True)
class ResolveExternalIdentityToParty(InteractionCommand):
    external_channel_identity_public_id: UUID
    party_reference: PublicAuthorityReference
    resolution_provenance: PublicAuthorityReference
    occurred_at: datetime


@dataclass(frozen=True)
class OpenConversation(InteractionCommand):
    correlation_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class CloseConversation(InteractionCommand):
    conversation_public_id: UUID
    occurred_at: datetime
    reason_code: str


@dataclass(frozen=True)
class JoinConversation(InteractionCommand):
    conversation_public_id: UUID
    kind: ParticipantKind
    actor_reference: PublicAuthorityReference
    occurred_at: datetime


@dataclass(frozen=True)
class LeaveConversation(InteractionCommand):
    participant_public_id: UUID
    occurred_at: datetime
    reason_code: str


@dataclass(frozen=True)
class StartInteractionSession(InteractionCommand):
    conversation_public_id: UUID
    participant_public_id: UUID
    identity_resolution_state: IdentityResolutionState
    verification_state: VerificationState
    correlation_id: UUID
    occurred_at: datetime
    expires_at: datetime | None = None
    authentication_reference: PublicAuthorityReference | None = None


@dataclass(frozen=True)
class ResumeInteractionSession(InteractionCommand):
    interaction_session_public_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class CloseInteractionSession(InteractionCommand):
    interaction_session_public_id: UUID
    occurred_at: datetime
    reason_code: str


@dataclass(frozen=True)
class RecordInboundInteractionMessage(InteractionCommand):
    conversation_public_id: UUID
    transport_reference: PublicAuthorityReference
    content: tuple[InteractionContentPart, ...]
    occurred_at: datetime
    correlation_id: UUID
    interaction_session_public_id: UUID | None = None
    participant_public_id: UUID | None = None
    provenance: InteractionProvenance | None = None
    causation_id: UUID | None = None


@dataclass(frozen=True)
class CreateOutboundInteractionMessage(InteractionCommand):
    conversation_public_id: UUID
    content: tuple[InteractionContentPart, ...]
    occurred_at: datetime
    correlation_id: UUID
    interaction_session_public_id: UUID | None = None
    participant_public_id: UUID | None = None
    provenance: InteractionProvenance | None = None
    causation_id: UUID | None = None


@dataclass(frozen=True)
class ProposeInteractionIntent(InteractionCommand):
    conversation_public_id: UUID
    intent_code: str
    occurred_at: datetime
    correlation_id: UUID
    interaction_session_public_id: UUID | None = None
    source_message_public_id: UUID | None = None
    proposal_provenance: InteractionProvenance | None = None
    causation_id: UUID | None = None


@dataclass(frozen=True)
class ValidateInteractionIntent(InteractionCommand):
    intent_public_id: UUID
    validation_outcome: str
    occurred_at: datetime


@dataclass(frozen=True)
class AcceptInteractionIntent(InteractionCommand):
    intent_public_id: UUID
    domain_bridge: PublicDomainCommandBridge
    occurred_at: datetime


@dataclass(frozen=True)
class RejectInteractionIntent(InteractionCommand):
    intent_public_id: UUID
    reason_code: str
    occurred_at: datetime


@dataclass(frozen=True)
class RecordIntentExecutionResult(InteractionCommand):
    intent_public_id: UUID
    result_reference: PublicAuthorityReference
    succeeded: bool
    occurred_at: datetime


@dataclass(frozen=True)
class CreateInteractionHandoff(InteractionCommand):
    conversation_public_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    interaction_session_public_id: UUID | None = None
    intent_public_id: UUID | None = None
    causation_id: UUID | None = None


@dataclass(frozen=True)
class LinkInteractionHandoffWorkflow(InteractionCommand):
    handoff_public_id: UUID
    workflow_reference: PublicAuthorityReference
    task_reference: PublicAuthorityReference | None
    occurred_at: datetime


@dataclass(frozen=True)
class CloseInteractionHandoff(InteractionCommand):
    handoff_public_id: UUID
    occurred_at: datetime
    reason_code: str


@dataclass(frozen=True)
class GrantInteractionCapability(InteractionCommand):
    subject_participant_public_id: UUID
    capability_code: str
    scope: str
    issuer_reference: PublicAuthorityReference
    effective_from: datetime
    provenance: PublicAuthorityReference
    expires_at: datetime | None = None


@dataclass(frozen=True)
class RevokeInteractionCapability(InteractionCommand):
    capability_grant_public_id: UUID
    occurred_at: datetime
    reason_code: str


@dataclass(frozen=True)
class BindInteractionContext(InteractionCommand):
    interaction_session_public_id: UUID
    source_reference: PublicAuthorityReference
    purpose_code: str
    provenance: PublicAuthorityReference
    effective_from: datetime
    participant_public_id: UUID | None = None
    source_version: str | None = None
    source_hash: str | None = None
    expires_at: datetime | None = None
    correlation_id: UUID | None = None


@dataclass(frozen=True)
class EndInteractionContextBinding(InteractionCommand):
    context_binding_public_id: UUID
    occurred_at: datetime
    reason_code: str


PUBLIC_COMMAND_TYPES = (
    RegisterExternalChannelIdentity,
    ResolveExternalIdentityToParty,
    OpenConversation,
    CloseConversation,
    JoinConversation,
    LeaveConversation,
    StartInteractionSession,
    ResumeInteractionSession,
    CloseInteractionSession,
    RecordInboundInteractionMessage,
    CreateOutboundInteractionMessage,
    ProposeInteractionIntent,
    ValidateInteractionIntent,
    AcceptInteractionIntent,
    RejectInteractionIntent,
    RecordIntentExecutionResult,
    CreateInteractionHandoff,
    LinkInteractionHandoffWorkflow,
    CloseInteractionHandoff,
    GrantInteractionCapability,
    RevokeInteractionCapability,
    BindInteractionContext,
    EndInteractionContextBinding,
)

PUBLIC_READ_CONTRACTS = (
    "external_channel_identity",
    "conversation",
    "participants",
    "interaction_session",
    "external_trust_projection",
    "messages",
    "intents",
    "handoff",
    "interaction_timeline",
    "capability_grants",
    "context_bindings",
)

CONSTITUTIONAL_LAWS = frozenset(
    {
        "channel_identity_ne_party",
        "participant_ne_party",
        "participant_ne_pc5_user",
        "interaction_session_ne_pc5_auth_session",
        "interaction_session_ne_domain_service_session",
        "anonymous_ne_uncontrolled",
        "party_resolved_ne_authenticated",
        "authenticated_external_ne_merchant_employee",
        "pc5_membership_not_required_for_guest_interaction",
        "ai_first_class_participant",
        "ai_ne_party",
        "ai_ne_pc5_user",
        "ai_ne_domain_authority",
        "so7_artifact_reference_only",
        "so8_transport_reference_only",
        "so6_handoff_reference_only",
        "intent_public_domain_command_only",
        "interaction_event_append_only",
        "channel_specific_kernel_schema_forbidden",
        "industry_specific_kernel_contract_forbidden",
        "idempotency_is_internal_command_ledger_pattern",
    }
)

__all__ = [
    "RESERVED_MIGRATION_REVISION",
    "CANONICAL_PRIMITIVES",
    "AUTHORITY_BOUNDARIES",
    "AI_ALLOWED_ACTIONS",
    "AI_FORBIDDEN_ACTIONS",
    "ExternalChannelIdentityStatus",
    "ConversationStatus",
    "ParticipantKind",
    "InteractionSessionStatus",
    "IdentityResolutionState",
    "VerificationState",
    "MessageDirection",
    "InteractionContentKind",
    "InteractionIntentStatus",
    "InteractionHandoffStatus",
    "InteractionCapabilityStatus",
    "PublicAuthorityReference",
    "AIExecutionReferences",
    "InteractionProvenance",
    "InteractionContentPart",
    "PublicDomainCommandBridge",
    "ExternalChannelIdentity",
    "Conversation",
    "ConversationParticipant",
    "InteractionSession",
    "InteractionMessage",
    "InteractionIntent",
    "InteractionHandoff",
    "InteractionEvent",
    "InteractionCapabilityGrant",
    "InteractionContextBinding",
    "ExternalTrustProjection",
    "InteractionTimelineProjection",
    "InteractionCommand",
    "RegisterExternalChannelIdentity",
    "ResolveExternalIdentityToParty",
    "OpenConversation",
    "CloseConversation",
    "JoinConversation",
    "LeaveConversation",
    "StartInteractionSession",
    "ResumeInteractionSession",
    "CloseInteractionSession",
    "RecordInboundInteractionMessage",
    "CreateOutboundInteractionMessage",
    "ProposeInteractionIntent",
    "ValidateInteractionIntent",
    "AcceptInteractionIntent",
    "RejectInteractionIntent",
    "RecordIntentExecutionResult",
    "CreateInteractionHandoff",
    "LinkInteractionHandoffWorkflow",
    "CloseInteractionHandoff",
    "GrantInteractionCapability",
    "RevokeInteractionCapability",
    "BindInteractionContext",
    "EndInteractionContextBinding",
    "PUBLIC_COMMAND_TYPES",
    "PUBLIC_READ_CONTRACTS",
    "CONSTITUTIONAL_LAWS",
]
