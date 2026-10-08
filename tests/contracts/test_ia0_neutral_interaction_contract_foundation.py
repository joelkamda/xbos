from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

import core.platform.interaction as ia0
from core.platform.interaction import (
    AIExecutionReferences,
    AcceptInteractionIntent,
    BindInteractionContext,
    CANONICAL_PRIMITIVES,
    CONSTITUTIONAL_LAWS,
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    ExternalChannelIdentity,
    ExternalChannelIdentityStatus,
    GrantInteractionCapability,
    IdentityResolutionState,
    InteractionCapabilityGrant,
    InteractionCapabilityStatus,
    InteractionContentKind,
    InteractionContentPart,
    InteractionEvent,
    InteractionHandoff,
    InteractionHandoffStatus,
    InteractionIntent,
    InteractionIntentStatus,
    InteractionMessage,
    InteractionProvenance,
    InteractionSession,
    InteractionSessionStatus,
    InteractionContextBinding,
    MessageDirection,
    OpenConversation,
    ParticipantKind,
    ProposeInteractionIntent,
    PublicAuthorityReference,
    PublicDomainCommandBridge,
    RegisterExternalChannelIdentity,
    RESERVED_MIGRATION_REVISION,
    StartInteractionSession,
    VerificationState,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = ROOT / "core/platform/interaction"
CONTRACT_SOURCE = (MODULE_DIR / "contracts.py").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)


def ref(authority: str, value: str) -> PublicAuthorityReference:
    return PublicAuthorityReference(authority, value)


def uid(value: int) -> UUID:
    return UUID(int=value)
def test_canonical_primitive_set_is_exact_and_schema_neutral():
    assert CANONICAL_PRIMITIVES == (
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
    assert len(CANONICAL_PRIMITIVES) == 10
    assert RESERVED_MIGRATION_REVISION == "ia0_neutral_interaction_authority_045"
    migration = ROOT / "alembic_neutral/versions/ia0_neutral_interaction_authority_045.py"
    if migration.exists():
        migration_source = migration.read_text(encoding="utf-8")
        assert 'revision = "ia0_neutral_interaction_authority_045"' in migration_source
        assert 'down_revision = "r63_legacy_inventory_writer_compat_044"' in migration_source
    assert "from alembic" not in CONTRACT_SOURCE


def test_tenant_required_on_all_ten_canonical_roots():
    for name in CANONICAL_PRIMITIVES:
        cls = getattr(ia0, name)
        assert is_dataclass(cls)
        assert "tenant_id" in {field.name for field in fields(cls)}


def test_contract_freezes_identity_session_and_trust_distinctions():
    assert set(IdentityResolutionState) == {
        IdentityResolutionState.UNRESOLVED,
        IdentityResolutionState.CHANNEL_IDENTIFIED,
        IdentityResolutionState.PARTY_RESOLVED,
    }
    assert set(VerificationState) == {
        VerificationState.UNVERIFIED,
        VerificationState.CHANNEL_VERIFIED,
        VerificationState.AUTHENTICATED_EXTERNAL,
    }
    assert set(InteractionSessionStatus) == {
        InteractionSessionStatus.ACTIVE,
        InteractionSessionStatus.EXPIRED,
        InteractionSessionStatus.CLOSED,
    }
    required = {
        "channel_identity_ne_party",
        "interaction_session_ne_pc5_auth_session",
        "interaction_session_ne_domain_service_session",
        "participant_ne_pc5_user",
        "anonymous_ne_uncontrolled",
        "party_resolved_ne_authenticated",
        "authenticated_external_ne_merchant_employee",
        "pc5_membership_not_required_for_guest_interaction",
    }
    assert required <= CONSTITUTIONAL_LAWS


def test_external_channel_identity_can_remain_unresolved_and_party_resolution_is_explicit():
    external = ExternalChannelIdentity(
        1, uid(1), "voice", "neutral_source", "opaque-1",
        ExternalChannelIdentityStatus.ACTIVE,
        IdentityResolutionState.UNRESOLVED,
    )
    assert external.party_reference is None
    party = ref("pc2.party", "party-9")
    resolved = ExternalChannelIdentity(
        1, uid(2), "voice", "neutral_source", "opaque-2",
        ExternalChannelIdentityStatus.ACTIVE,
        IdentityResolutionState.PARTY_RESOLVED,
        party_reference=party,
        resolution_provenance=ref("evidence", "proof-1"),
    )
    assert resolved.party_reference == party
    with pytest.raises(ValueError, match="party_reference_required_when_resolved"):
        ExternalChannelIdentity(
            1, uid(3), "voice", "neutral_source", "opaque-3",
            ExternalChannelIdentityStatus.ACTIVE,
            IdentityResolutionState.PARTY_RESOLVED,
        )


def test_participant_types_keep_ai_party_and_operational_identity_distinct():
    assert set(ParticipantKind) == {
        ParticipantKind.EXTERNAL_CHANNEL_IDENTITY,
        ParticipantKind.PARTY_REFERENCE,
        ParticipantKind.PC5_IDENTITY_REFERENCE,
        ParticipantKind.SERVICE_IDENTITY_REFERENCE,
        ParticipantKind.AI_PARTICIPANT,
        ParticipantKind.SYSTEM_PARTICIPANT,
    }
    conversation = Conversation(1, uid(10), ConversationStatus.OPEN, NOW, uid(100))
    ai = ConversationParticipant(
        1, uid(11), conversation.public_id, ParticipantKind.AI_PARTICIPANT,
        ref("ai.agent", "agent-runner-1"), NOW,
    )
    party_actor = ConversationParticipant(
        1, uid(12), conversation.public_id, ParticipantKind.PARTY_REFERENCE,
        ref("pc2.party", "party-1"), NOW,
    )
    assert ai.kind is not party_actor.kind
    assert {"ai_ne_party", "ai_ne_pc5_user", "ai_ne_domain_authority"} <= CONSTITUTIONAL_LAWS


def test_interaction_session_is_external_trust_not_authentication_or_domain_service_session():
    session = InteractionSession(
        tenant_id=1,
        public_id=uid(20),
        conversation_public_id=uid(10),
        participant_public_id=uid(11),
        status=InteractionSessionStatus.ACTIVE,
        identity_resolution_state=IdentityResolutionState.CHANNEL_IDENTIFIED,
        verification_state=VerificationState.CHANNEL_VERIFIED,
        started_at=NOW,
        correlation_id=uid(100),
    )
    assert session.authentication_reference is None
    with pytest.raises(ValueError, match="authenticated_external_requires_auth_reference"):
        InteractionSession(
            1, uid(21), uid(10), uid(11),
            InteractionSessionStatus.ACTIVE,
            IdentityResolutionState.PARTY_RESOLVED,
            VerificationState.AUTHENTICATED_EXTERNAL,
            NOW, uid(100),
        )


def test_kernel_contract_has_no_channel_or_industry_specific_schema_and_no_private_imports():
    lowered = CONTRACT_SOURCE.lower()
    assert "whatsapp" not in lowered
    assert "restaurant" not in lowered
    assert "sqlalchemy" not in lowered
    assert "sql_repository" not in lowered
    assert "shared_operations" not in lowered
    assert "core.domain.finance" not in lowered
    assert "core.platform.party" not in lowered
    assert "core.platform.security_authority" not in lowered
    assert not (MODULE_DIR / "repository.py").exists()
    sql_repository = MODULE_DIR / "sql_repository.py"
    if sql_repository.exists():
        repository_source = sql_repository.read_text(encoding="utf-8").lower()
        assert "shared_operations.so6" not in repository_source
        assert "shared_operations.so7" not in repository_source
        assert "shared_operations.so8" not in repository_source
        assert "core.domain.finance" not in repository_source
        assert "restaurant." not in repository_source
    assert not (MODULE_DIR / "service.py").exists()


def test_message_is_semantic_and_references_so8_so7_without_copying_authority():
    content = (
        InteractionContentPart(InteractionContentKind.TEXT, text="hello"),
        InteractionContentPart(
            InteractionContentKind.IMAGE_REFERENCE,
            reference=ref("so7.document_version", "doc-version-1"),
            media_type="image/jpeg",
            sha256="a" * 64,
        ),
    )
    provenance = InteractionProvenance(
        proposer_participant_public_id=uid(11),
        ai_execution=AIExecutionReferences(
            model_run_reference="model-run-1",
            agent_run_reference="agent-run-1",
            tool_invocation_reference="tool-call-1",
            tool_result_reference="tool-result-1",
        ),
    )
    message = InteractionMessage(
        1, uid(30), uid(10), MessageDirection.INBOUND, NOW, uid(100), content,
        interaction_session_public_id=uid(20),
        participant_public_id=uid(11),
        transport_reference=ref("so8.inbound_delivery", "delivery-1"),
        artifact_references=(ref("so7.document_version", "doc-version-1"),),
        provenance=provenance,
    )
    assert message.transport_reference.authority == "so8.inbound_delivery"
    assert message.artifact_references[0].authority == "so7.document_version"
    assert message.provenance.ai_execution.tool_result_reference == "tool-result-1"
    assert "so7_artifact_reference_only" in CONSTITUTIONAL_LAWS
    assert "so8_transport_reference_only" in CONSTITUTIONAL_LAWS


def test_interaction_event_is_frozen_append_only_chronology_contract():
    event = InteractionEvent(
        tenant_id=1,
        public_id=uid(40),
        conversation_public_id=uid(10),
        event_type="message_received",
        source_reference=ref("ia0.interaction_message", "30"),
        correlation_id=uid(100),
        occurred_at=NOW,
        message_public_id=uid(30),
    )
    with pytest.raises(FrozenInstanceError):
        event.event_type = "changed"
    assert "interaction_event_append_only" in CONSTITUTIONAL_LAWS
def test_intent_lifecycle_and_public_domain_command_bridge_do_not_claim_domain_truth():
    assert set(InteractionIntentStatus) == {
        InteractionIntentStatus.PROPOSED,
        InteractionIntentStatus.VALIDATED,
        InteractionIntentStatus.ACCEPTED,
        InteractionIntentStatus.REJECTED,
        InteractionIntentStatus.EXECUTED,
        InteractionIntentStatus.FAILED,
    }
    bridge = PublicDomainCommandBridge(
        target_authority="domain.order",
        public_command="AddItem",
        intent_code="order.add_item",
        request_reference="intent-50",
        correlation_id=uid(100),
        causation_id=uid(30),
    )
    accepted = InteractionIntent(
        1, uid(50), uid(10), "order.add_item",
        InteractionIntentStatus.ACCEPTED, NOW, uid(100),
        interaction_session_public_id=uid(20),
        source_message_public_id=uid(30),
        domain_bridge=bridge,
    )
    assert accepted.result_reference is None
    with pytest.raises(ValueError, match="executed_intent_requires_result_reference"):
        InteractionIntent(
            1, uid(51), uid(10), "order.add_item",
            InteractionIntentStatus.EXECUTED, NOW, uid(100),
            domain_bridge=bridge,
        )
    executed = InteractionIntent(
        1, uid(52), uid(10), "order.add_item",
        InteractionIntentStatus.EXECUTED, NOW, uid(100),
        domain_bridge=bridge,
        result_reference=ref("domain.order", "order-9"),
    )
    assert executed.result_reference.reference == "order-9"
    assert "intent_public_domain_command_only" in CONSTITUTIONAL_LAWS


def test_handoff_capability_and_context_are_reference_only_neutral_contracts():
    handoff = InteractionHandoff(
        1, uid(60), uid(10), InteractionHandoffStatus.ACCEPTED, NOW, uid(100),
        interaction_session_public_id=uid(20),
        intent_public_id=uid(50),
        workflow_reference=ref("so6.workflow", "workflow-1"),
        task_reference=ref("so6.task", "task-1"),
        accepted_at=NOW,
    )
    assert handoff.workflow_reference.authority == "so6.workflow"
    assert "so6_handoff_reference_only" in CONSTITUTIONAL_LAWS

    grant = InteractionCapabilityGrant(
        1, uid(61), uid(11), "order.request_add_item", "interaction",
        ref("policy", "issuer-1"), InteractionCapabilityStatus.ACTIVE,
        NOW, ref("evidence", "grant-proof"),
        expires_at=NOW + timedelta(hours=1),
    )
    assert grant.capability_code == "order.request_add_item"
    binding = InteractionContextBinding(
        1, uid(62), uid(20),
        ref("catalog.public_projection", "catalog-v3"),
        "customer_browse",
        ref("ia0.context_issuer", "server"),
        NOW,
        participant_public_id=uid(11),
        source_version="3",
        source_hash="b" * 64,
        correlation_id=uid(100),
    )
    assert binding.source_reference.authority == "catalog.public_projection"


def test_idempotency_is_contractual_command_pattern_not_public_canonical_primitive():
    assert not hasattr(ia0, "InteractionIdempotencyRecord")
    assert "InteractionIdempotencyRecord" not in CANONICAL_PRIMITIVES
    command = RegisterExternalChannelIdentity(
        "register-1", 1, "voice", "neutral_source", "opaque-9", NOW
    )
    payload = command.canonical_payload()
    assert payload["command_key"] == "register-1"
    assert payload["tenant_id"] == 1
    assert "idempotency_is_internal_command_ledger_pattern" in CONSTITUTIONAL_LAWS


def test_public_command_and_read_contracts_cover_a1_surface():
    command_names = {command.__name__ for command in ia0.PUBLIC_COMMAND_TYPES}
    assert {
        "RegisterExternalChannelIdentity",
        "ResolveExternalIdentityToParty",
        "OpenConversation",
        "StartInteractionSession",
        "RecordInboundInteractionMessage",
        "CreateOutboundInteractionMessage",
        "ProposeInteractionIntent",
        "AcceptInteractionIntent",
        "RecordIntentExecutionResult",
        "CreateInteractionHandoff",
        "GrantInteractionCapability",
        "BindInteractionContext",
    } <= command_names
    assert {
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
    } == set(ia0.PUBLIC_READ_CONTRACTS)


def test_ai_constitution_is_first_class_but_never_business_authority():
    assert "ai_first_class_participant" in CONSTITUTIONAL_LAWS
    assert {
        "observe_scoped_context",
        "classify",
        "extract",
        "summarize",
        "propose_intent",
        "propose_command_parameters",
        "generate_response_proposal",
        "request_domain_action",
        "request_human_review",
    } <= ia0.AI_ALLOWED_ACTIONS
    assert {
        "self_grant_capability",
        "fuzzy_create_party_identity",
        "declare_authentication_success",
        "declare_payment_success",
        "write_finance",
        "write_inventory",
        "write_domain_tables",
        "bypass_public_domain_contracts",
    } <= ia0.AI_FORBIDDEN_ACTIONS


def _case(target_authority: str, public_command: str, intent_code: str):
    conversation = Conversation(1, uid(70), ConversationStatus.OPEN, NOW, uid(700))
    participant = ConversationParticipant(
        1, uid(71), conversation.public_id,
        ParticipantKind.EXTERNAL_CHANNEL_IDENTITY,
        ref("ia0.external_channel_identity", "external-1"), NOW,
    )
    session = InteractionSession(
        1, uid(72), conversation.public_id, participant.public_id,
        InteractionSessionStatus.ACTIVE,
        IdentityResolutionState.UNRESOLVED,
        VerificationState.UNVERIFIED,
        NOW, uid(700),
    )
    message = InteractionMessage(
        1, uid(73), conversation.public_id, MessageDirection.INBOUND,
        NOW, uid(700),
        (InteractionContentPart(InteractionContentKind.TEXT, text="request"),),
        interaction_session_public_id=session.public_id,
        participant_public_id=participant.public_id,
    )
    bridge = PublicDomainCommandBridge(
        target_authority, public_command, intent_code,
        request_reference="intent-request", correlation_id=uid(700),
        causation_id=message.public_id,
    )
    intent = InteractionIntent(
        1, uid(74), conversation.public_id, intent_code,
        InteractionIntentStatus.ACCEPTED, NOW, uid(700),
        interaction_session_public_id=session.public_id,
        source_message_public_id=message.public_id,
        domain_bridge=bridge,
    )
    return conversation, participant, session, message, intent


def test_two_materially_different_uses_share_same_neutral_contract_model():
    case_a = _case("restaurant.order", "AddLine", "order.add_item")
    case_b = _case("professional_service.request", "RequestService", "service.request")
    assert tuple(type(item) for item in case_a) == tuple(type(item) for item in case_b)
    assert case_a[-1].domain_bridge.target_authority != case_b[-1].domain_bridge.target_authority
    assert case_a[2].verification_state is case_b[2].verification_state
