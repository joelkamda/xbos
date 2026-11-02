"""Canonical TEST-only CC receipt to IA0 writer, not a public route.

Caller MUST independently authenticate the service identity and verify receipt
provenance from CC through a trusted channel, and own transaction commit/rollback.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from core.platform.interaction.contracts import (
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    ExternalChannelIdentity,
    ExternalChannelIdentityStatus,
    IdentityResolutionState,
    InteractionContextBinding,
    InteractionSession,
    InteractionSessionStatus,
    ParticipantKind,
    PublicAuthorityReference,
    VerificationState,
)
from core.platform.interaction.sql_repository import SQLInteractionRepository

from .swes_r48_cc_event_validation import PURPOSE, TENANT, CCEventRejected

SOURCE = "xafpay.customer_channel.signed_twilio"
RECEIPT_AUTHORITY = "xafpay.cc.hosted_pg17_signed_twilio_receipt"

@dataclass(frozen=True, slots=True)
class VerifiedCCEvent:
    tenant_id: int
    location_id: int
    event_id: str
    fingerprint: str
    sender_hmac: str
    receipt_reference: str
    correlation_ref: UUID
    received_at: datetime
    expires_at: datetime

def persist_verified_event(session, event: VerifiedCCEvent, *,
                           authorize_service, verify_cc_receipt):
    """Atomic caller-owned transaction; independent trust gates are mandatory.

    Function does not create or infer service credentials or grant permissions.
    Same event/fingerprint returns the original session, conflicting replay fails.
    """
    if not callable(authorize_service) or not callable(verify_cc_receipt):
        raise CCEventRejected("TRUST_VERIFIERS_REQUIRED")
    if not isinstance(event, VerifiedCCEvent):
        raise CCEventRejected("EVENT_INVALID")
    now = datetime.now(timezone.utc)
    digests = (event.event_id, event.fingerprint, event.sender_hmac, event.receipt_reference)
    if (event.tenant_id != TENANT or event.location_id != 5
        or event.received_at.tzinfo is None or event.expires_at.tzinfo is None
        or not (event.received_at <= now < event.expires_at)
        or any(not isinstance(v, str) or len(v) != 64
               or any(ch not in "0123456789abcdef" for ch in v) for v in digests)):
        raise CCEventRejected("EVENT_SCOPE_OR_EXPIRY_INVALID")
    # Both verifiers must perform trusted, source-independent checks, not
    # simply accept headers or JSON booleans. No side effects precede them.
    if authorize_service(event) is not True:
        raise CCEventRejected("SERVICE_AUTH_FORBIDDEN")
    if verify_cc_receipt(event) is not True:
        raise CCEventRejected("RECEIPT_NOT_VERIFIED")
    repo = SQLInteractionRepository(session)
    key = "swes-r48-cc-event:" + event.event_id
    claim = repo.reserve_command(TENANT, key, event.fingerprint, "signed_twilio_ia0_session")
    if claim.result_public_id is not None:
        previous = repo.session(TENANT, UUID(str(claim.result_public_id)))
        if previous is None:
            raise CCEventRejected("REPLAY_SESSION_NOT_FOUND")
        return previous
    provenance = PublicAuthorityReference(RECEIPT_AUTHORITY, event.receipt_reference)
    external = repo.create_external_identity(
        ExternalChannelIdentity(
            tenant_id=TENANT, public_id=uuid4(), channel_kind="twilio_whatsapp",
            source_code=SOURCE, opaque_subject=event.sender_hmac,
            status=ExternalChannelIdentityStatus.ACTIVE,
            resolution_state=IdentityResolutionState.CHANNEL_IDENTIFIED,
            resolution_provenance=provenance,
        ),
        "swes-r48-cc-subject:" + event.sender_hmac,
        event.sender_hmac,
    )
    conversation = repo.insert_conversation(Conversation(
        tenant_id=TENANT, public_id=uuid4(), status=ConversationStatus.OPEN,
        opened_at=event.received_at, correlation_id=event.correlation_ref,
    ))
    participant = repo.insert_participant(ConversationParticipant(
        tenant_id=TENANT, public_id=uuid4(), conversation_public_id=conversation.public_id,
        kind=ParticipantKind.EXTERNAL_CHANNEL_IDENTITY,
        actor_reference=PublicAuthorityReference(
            "ia0.external_channel_identity", str(external.public_id)),
        joined_at=event.received_at,
    ))
    interaction = repo.insert_session(InteractionSession(
        tenant_id=TENANT, public_id=uuid4(),
        conversation_public_id=conversation.public_id,
        participant_public_id=participant.public_id,
        status=InteractionSessionStatus.ACTIVE,
        identity_resolution_state=IdentityResolutionState.CHANNEL_IDENTIFIED,
        verification_state=VerificationState.CHANNEL_VERIFIED,
        started_at=event.received_at, expires_at=event.expires_at,
        correlation_id=event.correlation_ref, authentication_reference=None,
    ))
    repo.insert_context_binding(InteractionContextBinding(
        tenant_id=TENANT, public_id=uuid4(),
        interaction_session_public_id=interaction.public_id,
        participant_public_id=participant.public_id,
        source_reference=PublicAuthorityReference(SOURCE, event.event_id),
        purpose_code=PURPOSE, provenance=provenance,
        effective_from=event.received_at, expires_at=event.expires_at,
        source_version="v1", source_hash=event.fingerprint,
        correlation_id=event.correlation_ref,
    ))
    repo.complete_command(TENANT, key, "interaction_session", interaction.public_id)
    return interaction
