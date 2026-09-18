from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from core.platform.interaction import (
    AIExecutionReferences,
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    ExternalChannelIdentity,
    ExternalChannelIdentityStatus,
    IA0RepositoryError,
    IdentityResolutionState,
    InteractionCapabilityGrant,
    InteractionCapabilityStatus,
    InteractionContentKind,
    InteractionContentPart,
    InteractionContextBinding,
    InteractionEvent,
    InteractionHandoff,
    InteractionHandoffStatus,
    InteractionIntent,
    InteractionIntentStatus,
    InteractionMessage,
    InteractionProvenance,
    InteractionSession,
    InteractionSessionStatus,
    MessageDirection,
    ParticipantKind,
    PublicAuthorityReference,
    PublicDomainCommandBridge,
    SQLInteractionRepository,
    VerificationState,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 18, 7, 0, tzinfo=timezone.utc)
TENANT_A = 9901
TENANT_B = 9902
EXPECTED_TABLES = {
    "ia0_commands",
    "ia0_external_channel_identities",
    "ia0_conversations",
    "ia0_conversation_participants",
    "ia0_interaction_sessions",
    "ia0_interaction_messages",
    "ia0_interaction_intents",
    "ia0_interaction_handoffs",
    "ia0_interaction_events",
    "ia0_interaction_capability_grants",
    "ia0_interaction_context_bindings",
}


def uid(value: int) -> UUID:
    return UUID(int=value)


def ref(authority: str, value: str) -> PublicAuthorityReference:
    return PublicAuthorityReference(authority, value)


@pytest.fixture
def db():
    url = make_url(os.environ["DATABASE_URL"])
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert url.database == "xbos_ia0_a2_acceptance"
    engine = create_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(
        text(
            "INSERT INTO tenants(id,code,name,country_code,currency,locale,timezone) "
            "VALUES(:a,'IA0A','IA0 Acceptance A','CM','XAF','en-CM','Africa/Douala'),"
            "(:b,'IA0B','IA0 Acceptance B','CM','XAF','en-CM','Africa/Douala') "
            "ON CONFLICT(id) DO NOTHING"
        ),
        {"a": TENANT_A, "b": TENANT_B},
    )
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def external(tenant: int = TENANT_A, public: int = 1) -> ExternalChannelIdentity:
    return ExternalChannelIdentity(
        tenant,
        uid(public),
        "web",
        "neutral_channel",
        f"opaque-{tenant}-{public}",
        ExternalChannelIdentityStatus.ACTIVE,
        IdentityResolutionState.UNRESOLVED,
    )


def conversation(tenant: int = TENANT_A, public: int = 10) -> Conversation:
    return Conversation(
        tenant,
        uid(public),
        ConversationStatus.OPEN,
        NOW,
        uid(public + 1000),
    )


def participant(
    conv: Conversation,
    public: int = 11,
    kind: ParticipantKind = ParticipantKind.EXTERNAL_CHANNEL_IDENTITY,
    actor_authority: str = "ia0.external_channel_identity",
    actor_reference: str = "external-1",
) -> ConversationParticipant:
    return ConversationParticipant(
        conv.tenant_id,
        uid(public),
        conv.public_id,
        kind,
        ref(actor_authority, actor_reference),
        NOW,
    )


def session(
    conv: Conversation,
    part: ConversationParticipant,
    public: int = 12,
) -> InteractionSession:
    return InteractionSession(
        conv.tenant_id,
        uid(public),
        conv.public_id,
        part.public_id,
        InteractionSessionStatus.ACTIVE,
        IdentityResolutionState.UNRESOLVED,
        VerificationState.UNVERIFIED,
        NOW,
        conv.correlation_id,
        expires_at=NOW + timedelta(hours=2),
    )


def message(
    conv: Conversation,
    sess: InteractionSession,
    part: ConversationParticipant,
    public: int = 13,
    transport_reference: str = "inbound-1",
) -> InteractionMessage:
    provenance = InteractionProvenance(
        proposer_participant_public_id=part.public_id,
        source_reference=ref("channel.ingress", transport_reference),
        ai_execution=AIExecutionReferences(
            model_run_reference="model-run-1",
            agent_run_reference="agent-run-1",
            tool_invocation_reference="tool-call-1",
            tool_result_reference="tool-result-1",
        ),
    )
    return InteractionMessage(
        conv.tenant_id,
        uid(public),
        conv.public_id,
        MessageDirection.INBOUND,
        NOW,
        conv.correlation_id,
        (
            InteractionContentPart(
                InteractionContentKind.TEXT,
                text="Please add two items",
            ),
            InteractionContentPart(
                InteractionContentKind.IMAGE_REFERENCE,
                reference=ref("so7.document_version", "document-version-1"),
                media_type="image/jpeg",
                sha256="a" * 64,
            ),
        ),
        interaction_session_public_id=sess.public_id,
        participant_public_id=part.public_id,
        transport_reference=ref("so8.inbound_delivery", transport_reference),
        artifact_references=(ref("so7.document_version", "document-version-1"),),
        provenance=provenance,
        causation_id=uid(9001),
    )


def accepted_intent(
    conv: Conversation,
    sess: InteractionSession,
    msg: InteractionMessage,
    public: int = 14,
    target_authority: str = "restaurant.order",
    public_command: str = "AddLine",
    intent_code: str = "order.add_item",
) -> InteractionIntent:
    bridge = PublicDomainCommandBridge(
        target_authority=target_authority,
        public_command=public_command,
        intent_code=intent_code,
        request_reference=f"intent-{public}",
        correlation_id=conv.correlation_id,
        causation_id=msg.public_id,
    )
    return InteractionIntent(
        conv.tenant_id,
        uid(public),
        conv.public_id,
        intent_code,
        InteractionIntentStatus.ACCEPTED,
        NOW,
        conv.correlation_id,
        interaction_session_public_id=sess.public_id,
        source_message_public_id=msg.public_id,
        proposal_provenance=msg.provenance,
        validation_outcome="validated",
        domain_bridge=bridge,
        causation_id=msg.public_id,
    )


def accepted_handoff(
    conv: Conversation,
    sess: InteractionSession,
    intent: InteractionIntent,
    public: int = 15,
) -> InteractionHandoff:
    return InteractionHandoff(
        conv.tenant_id,
        uid(public),
        conv.public_id,
        InteractionHandoffStatus.ACCEPTED,
        NOW,
        conv.correlation_id,
        interaction_session_public_id=sess.public_id,
        intent_public_id=intent.public_id,
        workflow_reference=ref("so6.workflow", "workflow-public-1"),
        task_reference=ref("so6.task", "task-public-1"),
        accepted_at=NOW + timedelta(seconds=1),
        causation_id=intent.public_id,
    )


def interaction_event(
    conv: Conversation,
    sess: InteractionSession,
    part: ConversationParticipant,
    msg: InteractionMessage,
    intent: InteractionIntent,
    handoff: InteractionHandoff,
    public: int = 16,
) -> InteractionEvent:
    return InteractionEvent(
        conv.tenant_id,
        uid(public),
        conv.public_id,
        "handoff_accepted",
        ref("ia0.interaction_handoff", str(handoff.public_id)),
        conv.correlation_id,
        NOW + timedelta(seconds=2),
        interaction_session_public_id=sess.public_id,
        participant_public_id=part.public_id,
        message_public_id=msg.public_id,
        intent_public_id=intent.public_id,
        handoff_public_id=handoff.public_id,
        causation_id=handoff.public_id,
    )


def capability(
    conv: Conversation,
    part: ConversationParticipant,
    public: int = 17,
) -> InteractionCapabilityGrant:
    return InteractionCapabilityGrant(
        conv.tenant_id,
        uid(public),
        part.public_id,
        "order.request_add_item",
        "interaction",
        ref("policy", "external-capability-policy"),
        InteractionCapabilityStatus.ACTIVE,
        NOW,
        ref("evidence", "capability-grant-proof"),
        expires_at=NOW + timedelta(hours=1),
    )


def context_binding(
    conv: Conversation,
    sess: InteractionSession,
    part: ConversationParticipant,
    public: int = 18,
) -> InteractionContextBinding:
    return InteractionContextBinding(
        conv.tenant_id,
        uid(public),
        sess.public_id,
        ref("catalog.public_projection", "catalog-v3"),
        "customer_browse",
        ref("ia0.context_issuer", "server"),
        NOW,
        participant_public_id=part.public_id,
        source_version="3",
        source_hash="b" * 64,
        expires_at=NOW + timedelta(hours=1),
        correlation_id=conv.correlation_id,
    )


def persist_graph(
    db: Session,
    *,
    tenant: int = TENANT_A,
    base: int = 100,
    target_authority: str = "restaurant.order",
    public_command: str = "AddLine",
    intent_code: str = "order.add_item",
):
    repo = SQLInteractionRepository(db)
    ext = external(tenant, base)
    repo.create_external_identity(ext, f"external-{base}", "a" * 64)
    conv = conversation(tenant, base + 1)
    repo.insert_conversation(conv)
    part = participant(
        conv,
        base + 2,
        actor_reference=str(ext.public_id),
    )
    repo.insert_participant(part)
    sess = session(conv, part, base + 3)
    repo.insert_session(sess)
    msg = message(
        conv,
        sess,
        part,
        base + 4,
        transport_reference=f"transport-{tenant}-{base}",
    )
    repo.insert_message(msg)
    intent = accepted_intent(
        conv,
        sess,
        msg,
        base + 5,
        target_authority=target_authority,
        public_command=public_command,
        intent_code=intent_code,
    )
    repo.insert_intent(intent)
    handoff = accepted_handoff(conv, sess, intent, base + 6)
    repo.insert_handoff(handoff)
    event = interaction_event(
        conv, sess, part, msg, intent, handoff, base + 7
    )
    repo.append_event(event)
    cap = capability(conv, part, base + 8)
    repo.insert_capability(cap)
    ctx = context_binding(conv, sess, part, base + 9)
    repo.insert_context_binding(ctx)
    return repo, ext, conv, part, sess, msg, intent, handoff, event, cap, ctx


def test_schema_head_and_exact_table_set(db: Session):
    head = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    tables = set(
        db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name LIKE 'ia0_%'"
            )
        ).scalars()
    )
    assert head == "ia0_neutral_interaction_authority_045"
    assert tables == EXPECTED_TABLES
    assert "ia0_artifacts" not in tables
    assert "ia0_interaction_idempotency_records" not in tables


def test_command_ledger_identical_replay_altered_conflict_and_stable_external_identity(db: Session):
    repo = SQLInteractionRepository(db)
    value = external()
    created = repo.create_external_identity(value, "register-ext-1", "a" * 64)
    assert created == value
    assert repo.create_external_identity(value, "register-ext-1", "a" * 64) == value
    with pytest.raises(IA0RepositoryError, match="different fingerprint or type"):
        repo.create_external_identity(value, "register-ext-1", "b" * 64)

    same_natural_identity = replace(value, public_id=uid(999))
    replayed = repo.create_external_identity(
        same_natural_identity, "register-ext-2", "c" * 64
    )
    assert replayed == value
    assert (
        db.execute(
            text(
                "SELECT count(*) FROM ia0_external_channel_identities "
                "WHERE tenant_id=:t"
            ),
            {"t": TENANT_A},
        ).scalar_one()
        == 1
    )


def test_explicit_party_resolution_roundtrip_preserves_authority_pair(db: Session):
    repo = SQLInteractionRepository(db)
    value = external()
    repo.create_external_identity(value, "register-ext", "a" * 64)
    resolved = repo.resolve_external_identity(
        TENANT_A,
        value.public_id,
        ref("pc2.party", "party-public-1"),
        ref("evidence", "resolution-proof-1"),
    )
    assert resolved.resolution_state is IdentityResolutionState.PARTY_RESOLVED
    assert resolved.party_reference == ref("pc2.party", "party-public-1")
    assert resolved.resolution_provenance == ref("evidence", "resolution-proof-1")
    assert (
        db.execute(text("SELECT count(*) FROM parties WHERE tenant_id=:t"), {"t": TENANT_A}).scalar_one()
        == 0
    )


def test_conversation_and_session_lifecycle_persistence(db: Session):
    repo = SQLInteractionRepository(db)
    conv = conversation()
    repo.insert_conversation(conv)
    part = participant(conv)
    repo.insert_participant(part)
    sess = session(conv, part)
    repo.insert_session(sess)

    closed_session = repo.close_session(
        TENANT_A, sess.public_id, NOW + timedelta(minutes=15)
    )
    assert closed_session.status is InteractionSessionStatus.CLOSED
    assert closed_session.closed_at == NOW + timedelta(minutes=15)

    closed_conv = repo.close_conversation(
        TENANT_A, conv.public_id, NOW + timedelta(minutes=20)
    )
    assert closed_conv.status is ConversationStatus.CLOSED
    assert closed_conv.closed_at == NOW + timedelta(minutes=20)


def test_message_content_so7_so8_ai_provenance_and_correlation_roundtrip(db: Session):
    repo, _, conv, part, sess, msg, *_ = persist_graph(db, base=200)
    loaded = repo.message(TENANT_A, msg.public_id)
    assert loaded == msg
    assert loaded.transport_reference == ref(
        "so8.inbound_delivery", "transport-9901-200"
    )
    assert loaded.artifact_references == (
        ref("so7.document_version", "document-version-1"),
    )
    assert loaded.provenance.ai_execution.model_run_reference == "model-run-1"
    assert loaded.provenance.ai_execution.agent_run_reference == "agent-run-1"
    assert loaded.provenance.ai_execution.tool_invocation_reference == "tool-call-1"
    assert loaded.provenance.ai_execution.tool_result_reference == "tool-result-1"
    assert loaded.correlation_id == conv.correlation_id
    assert loaded.causation_id == uid(9001)


def test_inbound_transport_duplicate_collapses_and_changed_semantics_conflict(db: Session):
    repo = SQLInteractionRepository(db)
    conv = conversation(public=300)
    repo.insert_conversation(conv)
    part = participant(conv, public=301)
    repo.insert_participant(part)
    sess = session(conv, part, public=302)
    repo.insert_session(sess)
    original = message(
        conv, sess, part, public=303, transport_reference="same-transport"
    )
    assert repo.insert_message(original) == original
    duplicate = replace(original, public_id=uid(304))
    assert repo.insert_message(duplicate) == original
    changed = replace(
        duplicate,
        content=(InteractionContentPart(InteractionContentKind.TEXT, text="changed"),),
    )
    with pytest.raises(IA0RepositoryError, match="different semantic message"):
        repo.insert_message(changed)


def test_intent_lifecycle_domain_bridge_and_result_reference_roundtrip(db: Session):
    repo = SQLInteractionRepository(db)
    conv = conversation(public=400)
    repo.insert_conversation(conv)
    part = participant(conv, public=401)
    repo.insert_participant(part)
    sess = session(conv, part, public=402)
    repo.insert_session(sess)
    msg = message(conv, sess, part, public=403, transport_reference="intent-transport")
    repo.insert_message(msg)
    intent = accepted_intent(conv, sess, msg, public=404)
    assert repo.insert_intent(intent) == intent
    executed = replace(
        intent,
        status=InteractionIntentStatus.EXECUTED,
        result_reference=ref("restaurant.order", "order-public-1"),
    )
    loaded = repo.replace_intent(executed)
    assert loaded.status is InteractionIntentStatus.EXECUTED
    assert loaded.domain_bridge.target_authority == "restaurant.order"
    assert loaded.domain_bridge.public_command == "AddLine"
    assert loaded.result_reference == ref("restaurant.order", "order-public-1")


def test_handoff_event_capability_and_context_roundtrip(db: Session):
    repo, _, conv, part, sess, msg, intent, handoff, event, cap, ctx = persist_graph(
        db, base=500
    )
    assert repo.handoff(TENANT_A, handoff.public_id) == handoff
    assert repo.event(TENANT_A, event.public_id) == event
    assert repo.capability(TENANT_A, cap.public_id) == cap
    assert repo.context_binding(TENANT_A, ctx.public_id) == ctx
    assert repo.handoff(TENANT_A, handoff.public_id).workflow_reference == ref(
        "so6.workflow", "workflow-public-1"
    )
    assert repo.context_binding(TENANT_A, ctx.public_id).source_reference == ref(
        "catalog.public_projection", "catalog-v3"
    )


def test_message_and_event_are_database_enforced_append_only(db: Session):
    repo, _, _, _, _, msg, _, _, event, _, _ = persist_graph(db, base=600)
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(
                text(
                    "UPDATE ia0_interaction_messages SET direction='system' "
                    "WHERE tenant_id=:t AND public_id=:p"
                ),
                {"t": TENANT_A, "p": str(msg.public_id)},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(
                text(
                    "DELETE FROM ia0_interaction_messages "
                    "WHERE tenant_id=:t AND public_id=:p"
                ),
                {"t": TENANT_A, "p": str(msg.public_id)},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(
                text(
                    "UPDATE ia0_interaction_events SET event_type='changed' "
                    "WHERE tenant_id=:t AND public_id=:p"
                ),
                {"t": TENANT_A, "p": str(event.public_id)},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(
                text(
                    "DELETE FROM ia0_interaction_events "
                    "WHERE tenant_id=:t AND public_id=:p"
                ),
                {"t": TENANT_A, "p": str(event.public_id)},
            )


def test_all_cross_tenant_repository_relation_attempts_fail_closed(db: Session):
    repo_a, _, conv_a, part_a, sess_a, msg_a, intent_a, handoff_a, *_ = persist_graph(
        db, tenant=TENANT_A, base=700
    )
    repo_b = SQLInteractionRepository(db)
    conv_b = conversation(TENANT_B, public=800)
    repo_b.insert_conversation(conv_b)

    with pytest.raises(IA0RepositoryError):
        repo_b.insert_participant(
            ConversationParticipant(
                TENANT_B,
                uid(801),
                conv_a.public_id,
                ParticipantKind.EXTERNAL_CHANNEL_IDENTITY,
                ref("ia0.external_channel_identity", "cross"),
                NOW,
            )
        )

    part_b = participant(
        conv_b,
        public=802,
        actor_reference="tenant-b-external",
    )
    repo_b.insert_participant(part_b)

    with pytest.raises(IA0RepositoryError):
        repo_b.insert_session(
            InteractionSession(
                TENANT_B,
                uid(803),
                conv_a.public_id,
                part_b.public_id,
                InteractionSessionStatus.ACTIVE,
                IdentityResolutionState.UNRESOLVED,
                VerificationState.UNVERIFIED,
                NOW,
                conv_b.correlation_id,
            )
        )

    sess_b = session(conv_b, part_b, public=804)
    repo_b.insert_session(sess_b)

    with pytest.raises(IA0RepositoryError):
        repo_b.insert_message(
            InteractionMessage(
                TENANT_B,
                uid(805),
                conv_b.public_id,
                MessageDirection.INBOUND,
                NOW,
                conv_b.correlation_id,
                (InteractionContentPart(InteractionContentKind.TEXT, text="cross"),),
                interaction_session_public_id=sess_a.public_id,
                participant_public_id=part_b.public_id,
                transport_reference=ref("so8.inbound_delivery", "cross-msg"),
            )
        )

    with pytest.raises(IA0RepositoryError):
        repo_b.insert_intent(
            InteractionIntent(
                TENANT_B,
                uid(806),
                conv_b.public_id,
                "service.request",
                InteractionIntentStatus.PROPOSED,
                NOW,
                conv_b.correlation_id,
                interaction_session_public_id=sess_b.public_id,
                source_message_public_id=msg_a.public_id,
            )
        )


    with pytest.raises(IA0RepositoryError):
        repo_b.insert_handoff(
            InteractionHandoff(
                TENANT_B,
                uid(807),
                conv_b.public_id,
                InteractionHandoffStatus.REQUESTED,
                NOW,
                conv_b.correlation_id,
                interaction_session_public_id=sess_b.public_id,
                intent_public_id=intent_a.public_id,
            )
        )

    with pytest.raises(IA0RepositoryError):
        repo_b.append_event(
            InteractionEvent(
                TENANT_B,
                uid(808),
                conv_b.public_id,
                "cross_tenant_reference",
                ref("ia0.test", "cross"),
                conv_b.correlation_id,
                NOW,
                interaction_session_public_id=sess_b.public_id,
                participant_public_id=part_b.public_id,
                message_public_id=msg_a.public_id,
            )
        )

    with pytest.raises(IA0RepositoryError):
        repo_b.insert_capability(
            InteractionCapabilityGrant(
                TENANT_B,
                uid(809),
                part_a.public_id,
                "service.request",
                "interaction",
                ref("policy", "issuer"),
                InteractionCapabilityStatus.ACTIVE,
                NOW,
                ref("evidence", "grant"),
            )
        )

    with pytest.raises(IA0RepositoryError):
        repo_b.insert_context_binding(
            InteractionContextBinding(
                TENANT_B,
                uid(810),
                sess_a.public_id,
                ref("service.public_projection", "service-1"),
                "service_request",
                ref("ia0.context_issuer", "server"),
                NOW,
                participant_public_id=part_b.public_id,
            )
        )


def test_database_composite_fk_blocks_cross_tenant_internal_link_even_via_raw_sql(db: Session):
    repo = SQLInteractionRepository(db)
    conv_a = conversation(TENANT_A, public=900)
    repo.insert_conversation(conv_a)
    internal_id = db.execute(
        text(
            "SELECT id FROM ia0_conversations "
            "WHERE tenant_id=:t AND public_id=:p"
        ),
        {"t": TENANT_A, "p": str(conv_a.public_id)},
    ).scalar_one()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO ia0_conversation_participants("
                    "public_id,tenant_id,conversation_id,participant_kind,"
                    "actor_authority,actor_reference,joined_at"
                    ") VALUES(:p,:t,:c,'system_participant','system','cross',:at)"
                ),
                {
                    "p": str(uid(901)),
                    "t": TENANT_B,
                    "c": internal_id,
                    "at": NOW,
                },
            )


def test_two_use_persistence_uses_same_tables_repository_and_contracts(db: Session):
    case_a = persist_graph(
        db,
        tenant=TENANT_A,
        base=1000,
        target_authority="restaurant.order",
        public_command="AddLine",
        intent_code="order.add_item",
    )
    case_b = persist_graph(
        db,
        tenant=TENANT_A,
        base=1100,
        target_authority="professional_service.request",
        public_command="RequestService",
        intent_code="service.request",
    )
    repo = case_a[0]
    assert type(case_a[2]) is type(case_b[2])
    assert type(case_a[4]) is type(case_b[4])
    assert type(case_a[5]) is type(case_b[5])
    assert type(case_a[6]) is type(case_b[6])
    assert repo.intent(TENANT_A, case_a[6].public_id).domain_bridge.target_authority == "restaurant.order"
    assert repo.intent(TENANT_A, case_b[6].public_id).domain_bridge.target_authority == "professional_service.request"
    columns = set(
        db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name LIKE 'ia0_%'"
            )
        ).scalars()
    )
    assert not any(
        token in column.lower()
        for column in columns
        for token in ("restaurant", "whatsapp", "provider_specific")
    )


def test_public_authority_reference_requires_authority_and_reference_pair(db: Session):
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO ia0_external_channel_identities("
                    "public_id,tenant_id,channel_kind,source_code,opaque_subject,"
                    "lifecycle_status,resolution_state,party_reference"
                    ") VALUES(:p,:t,'web','neutral','opaque-pair','active',"
                    "'party_resolved','party-only')"
                ),
                {"p": str(uid(1200)), "t": TENANT_A},
            )


def test_a2_persistence_has_no_domain_effects(db: Session):
    watched = (
        "r1_restaurant_orders",
        "canonical_payment_attempts",
        "so6_workflows",
        "so8_delivery_jobs",
        "parties",
        "authentication_sessions",
    )
    before = {
        table: db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in watched
    }
    persist_graph(db, base=1300)
    after = {
        table: db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in watched
    }
    assert after == before


def test_contract_source_is_not_changed_by_a2():
    import subprocess

    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--name-only",
            "d6e4f95510cc778a07f39cc0430121536af4128d",
            "--",
            "core/platform/interaction/contracts.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""
