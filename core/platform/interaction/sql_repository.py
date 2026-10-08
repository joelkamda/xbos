"""SQLAlchemy persistence foundation for IA0 neutral interaction authority."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import text

from .contracts import (
    AIExecutionReferences,
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    ExternalChannelIdentity,
    ExternalChannelIdentityStatus,
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
    VerificationState,
)


class IA0RepositoryError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _primitive(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    if isinstance(value, list):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    return value


def _json(value: Any) -> str:
    return json.dumps(_primitive(value), sort_keys=True, separators=(",", ":"))


def _ref(authority: str | None, reference: str | None) -> PublicAuthorityReference | None:
    if authority is None and reference is None:
        return None
    if not authority or not reference:
        raise IA0RepositoryError("IA0_REFERENCE_PAIR_INVALID", "authority/reference must be paired")
    return PublicAuthorityReference(authority, reference)


def _content_part(value: dict[str, Any]) -> InteractionContentPart:
    ref_value = value.get("reference")
    return InteractionContentPart(
        kind=InteractionContentKind(value["kind"]),
        text=value.get("text"),
        reference=(
            PublicAuthorityReference(ref_value["authority"], ref_value["reference"])
            if ref_value
            else None
        ),
        media_type=value.get("media_type"),
        sha256=value.get("sha256"),
    )


def _ai_refs(value: dict[str, Any] | None) -> AIExecutionReferences | None:
    if not value:
        return None
    return AIExecutionReferences(
        model_run_reference=value.get("model_run_reference"),
        agent_run_reference=value.get("agent_run_reference"),
        tool_invocation_reference=value.get("tool_invocation_reference"),
        tool_result_reference=value.get("tool_result_reference"),
    )


def _provenance(value: dict[str, Any] | None) -> InteractionProvenance | None:
    if not value:
        return None
    source = value.get("source_reference")
    proposer = value.get("proposer_participant_public_id")
    return InteractionProvenance(
        proposer_participant_public_id=UUID(str(proposer)) if proposer else None,
        source_reference=(
            PublicAuthorityReference(source["authority"], source["reference"])
            if source
            else None
        ),
        ai_execution=_ai_refs(value.get("ai_execution")),
    )


def _bridge(value: dict[str, Any] | None) -> PublicDomainCommandBridge | None:
    if not value:
        return None
    result = value.get("result_reference")
    return PublicDomainCommandBridge(
        target_authority=value["target_authority"],
        public_command=value["public_command"],
        intent_code=value["intent_code"],
        request_reference=value.get("request_reference"),
        result_reference=(
            PublicAuthorityReference(result["authority"], result["reference"])
            if result
            else None
        ),
        correlation_id=UUID(str(value["correlation_id"])) if value.get("correlation_id") else None,
        causation_id=UUID(str(value["causation_id"])) if value.get("causation_id") else None,
    )


class SQLInteractionRepository:
    """IA0-owned persistence only; no cross-authority execution."""

    _TABLES = {
        "conversation": "ia0_conversations",
        "participant": "ia0_conversation_participants",
        "session": "ia0_interaction_sessions",
        "message": "ia0_interaction_messages",
        "intent": "ia0_interaction_intents",
        "handoff": "ia0_interaction_handoffs",
        "capability": "ia0_interaction_capability_grants",
        "context": "ia0_interaction_context_bindings",
    }

    def __init__(self, db_session):
        self.db_session = db_session

    def reserve_command(
        self,
        tenant_id: int,
        command_key: str,
        request_fingerprint: str,
        command_type: str,
    ):
        row = self.db_session.execute(
            text(
                "SELECT * FROM ia0_commands "
                "WHERE tenant_id=:t AND command_key=:k FOR UPDATE"
            ),
            {"t": tenant_id, "k": command_key},
        ).first()
        if row:
            if (
                row.request_fingerprint != request_fingerprint
                or row.command_type != command_type
            ):
                raise IA0RepositoryError(
                    "IA0_COMMAND_CONFLICT",
                    "command key already used with different fingerprint or type",
                )
            return row
        return self.db_session.execute(
            text(
                "INSERT INTO ia0_commands("
                "tenant_id,command_key,request_fingerprint,command_type"
                ") VALUES(:t,:k,:f,:y) RETURNING *"
            ),
            {
                "t": tenant_id,
                "k": command_key,
                "f": request_fingerprint,
                "y": command_type,
            },
        ).one()

    def complete_command(
        self,
        tenant_id: int,
        command_key: str,
        result_type: str,
        result_public_id: UUID,
    ) -> None:
        self.db_session.execute(
            text(
                "UPDATE ia0_commands SET result_type=:y,result_public_id=:p,"
                "completed_at=now() WHERE tenant_id=:t AND command_key=:k"
            ),
            {
                "y": result_type,
                "p": str(result_public_id),
                "t": tenant_id,
                "k": command_key,
            },
        )

    def _internal_id(self, kind: str, tenant_id: int, public_id: UUID | None) -> int | None:
        if public_id is None:
            return None
        table = self._TABLES[kind]
        return self.db_session.execute(
            text(f"SELECT id FROM {table} WHERE tenant_id=:t AND public_id=:p"),
            {"t": tenant_id, "p": str(public_id)},
        ).scalar()

    def _public_id(self, kind: str, tenant_id: int, internal_id: int | None) -> UUID | None:
        if internal_id is None:
            return None
        table = self._TABLES[kind]
        value = self.db_session.execute(
            text(f"SELECT public_id FROM {table} WHERE tenant_id=:t AND id=:i"),
            {"t": tenant_id, "i": internal_id},
        ).scalar()
        return UUID(str(value)) if value else None


    def create_external_identity(
        self,
        value: ExternalChannelIdentity,
        command_key: str,
        request_fingerprint: str,
    ) -> ExternalChannelIdentity:
        replay = self.reserve_command(
            value.tenant_id,
            command_key,
            request_fingerprint,
            "register_external_channel_identity",
        )
        if replay.result_public_id:
            return self.external_identity(
                value.tenant_id, UUID(str(replay.result_public_id))
            )
        existing = self.db_session.execute(
            text(
                "SELECT public_id FROM ia0_external_channel_identities "
                "WHERE tenant_id=:t AND channel_kind=:c "
                "AND source_code=:s AND opaque_subject=:o FOR UPDATE"
            ),
            {
                "t": value.tenant_id,
                "c": value.channel_kind,
                "s": value.source_code,
                "o": value.opaque_subject,
            },
        ).scalar()
        if existing:
            current = self.external_identity(value.tenant_id, UUID(str(existing)))
            if current != replace(value, public_id=current.public_id):
                raise IA0RepositoryError(
                    "IA0_EXTERNAL_IDENTITY_CONFLICT",
                    "external identity key already exists with different contract data",
                )
            self.complete_command(
                value.tenant_id, command_key, "external_channel_identity", current.public_id
            )
            return current
        party = value.party_reference
        provenance = value.resolution_provenance
        self.db_session.execute(
            text(
                "INSERT INTO ia0_external_channel_identities("
                "public_id,tenant_id,channel_kind,source_code,opaque_subject,"
                "lifecycle_status,resolution_state,party_authority,party_reference,"
                "resolution_provenance_authority,resolution_provenance_reference"
                ") VALUES(:p,:t,:c,:s,:o,:ls,:rs,:pa,:pr,:rpa,:rpr)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": value.channel_kind,
                "s": value.source_code,
                "o": value.opaque_subject,
                "ls": value.status.value,
                "rs": value.resolution_state.value,
                "pa": party.authority if party else None,
                "pr": party.reference if party else None,
                "rpa": provenance.authority if provenance else None,
                "rpr": provenance.reference if provenance else None,
            },
        )
        self.complete_command(
            value.tenant_id, command_key, "external_channel_identity", value.public_id
        )
        return self.external_identity(value.tenant_id, value.public_id)

    def external_identity(
        self, tenant_id: int, public_id: UUID
    ) -> ExternalChannelIdentity | None:
        row = self.db_session.execute(
            text(
                "SELECT * FROM ia0_external_channel_identities "
                "WHERE tenant_id=:t AND public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return ExternalChannelIdentity(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            channel_kind=row.channel_kind,
            source_code=row.source_code,
            opaque_subject=row.opaque_subject,
            status=ExternalChannelIdentityStatus(row.lifecycle_status),
            resolution_state=IdentityResolutionState(row.resolution_state),
            party_reference=_ref(row.party_authority, row.party_reference),
            resolution_provenance=_ref(
                row.resolution_provenance_authority,
                row.resolution_provenance_reference,
            ),
        )

    def resolve_external_identity(
        self,
        tenant_id: int,
        public_id: UUID,
        party_reference: PublicAuthorityReference,
        provenance: PublicAuthorityReference,
    ) -> ExternalChannelIdentity:
        updated = self.db_session.execute(
            text(
                "UPDATE ia0_external_channel_identities "
                "SET resolution_state='party_resolved',"
                "party_authority=:pa,party_reference=:pr,"
                "resolution_provenance_authority=:ea,"
                "resolution_provenance_reference=:er,"
                "row_version=row_version+1,updated_at=now() "
                "WHERE tenant_id=:t AND public_id=:p RETURNING public_id"
            ),
            {
                "pa": party_reference.authority,
                "pr": party_reference.reference,
                "ea": provenance.authority,
                "er": provenance.reference,
                "t": tenant_id,
                "p": str(public_id),
            },
        ).scalar()
        if not updated:
            raise IA0RepositoryError("IA0_EXTERNAL_IDENTITY_NOT_FOUND", "identity not found")
        return self.external_identity(tenant_id, public_id)

    def insert_conversation(self, value: Conversation) -> Conversation:
        self.db_session.execute(
            text(
                "INSERT INTO ia0_conversations("
                "public_id,tenant_id,lifecycle_status,opened_at,closed_at,correlation_id"
                ") VALUES(:p,:t,:s,:o,:c,:r)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "s": value.status.value,
                "o": value.opened_at,
                "c": value.closed_at,
                "r": str(value.correlation_id),
            },
        )
        return self.conversation(value.tenant_id, value.public_id)

    def conversation(self, tenant_id: int, public_id: UUID) -> Conversation | None:
        row = self.db_session.execute(
            text(
                "SELECT * FROM ia0_conversations "
                "WHERE tenant_id=:t AND public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return Conversation(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            status=ConversationStatus(row.lifecycle_status),
            opened_at=row.opened_at,
            correlation_id=UUID(str(row.correlation_id)),
            closed_at=row.closed_at,
        )

    def close_conversation(
        self, tenant_id: int, public_id: UUID, closed_at: datetime
    ) -> Conversation:
        updated = self.db_session.execute(
            text(
                "UPDATE ia0_conversations SET lifecycle_status='closed',"
                "closed_at=:at,row_version=row_version+1,updated_at=now() "
                "WHERE tenant_id=:t AND public_id=:p "
                "AND lifecycle_status='open' RETURNING public_id"
            ),
            {"at": closed_at, "t": tenant_id, "p": str(public_id)},
        ).scalar()
        if not updated:
            raise IA0RepositoryError("IA0_CONVERSATION_NOT_OPEN", "conversation not open")
        return self.conversation(tenant_id, public_id)

    def insert_participant(
        self, value: ConversationParticipant
    ) -> ConversationParticipant:
        conversation_id = self._internal_id(
            "conversation", value.tenant_id, value.conversation_public_id
        )
        if conversation_id is None:
            raise IA0RepositoryError("IA0_CONVERSATION_NOT_FOUND", "conversation not found")
        self.db_session.execute(
            text(
                "INSERT INTO ia0_conversation_participants("
                "public_id,tenant_id,conversation_id,participant_kind,"
                "actor_authority,actor_reference,joined_at,left_at"
                ") VALUES(:p,:t,:c,:k,:aa,:ar,:j,:l)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": conversation_id,
                "k": value.kind.value,
                "aa": value.actor_reference.authority,
                "ar": value.actor_reference.reference,
                "j": value.joined_at,
                "l": value.left_at,
            },
        )
        return self.participant(value.tenant_id, value.public_id)

    def participant(
        self, tenant_id: int, public_id: UUID
    ) -> ConversationParticipant | None:
        row = self.db_session.execute(
            text(
                "SELECT p.*,c.public_id conversation_public_id "
                "FROM ia0_conversation_participants p "
                "JOIN ia0_conversations c ON "
                "(c.tenant_id,c.id)=(p.tenant_id,p.conversation_id) "
                "WHERE p.tenant_id=:t AND p.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return ConversationParticipant(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            conversation_public_id=UUID(str(row.conversation_public_id)),
            kind=ParticipantKind(row.participant_kind),
            actor_reference=PublicAuthorityReference(
                row.actor_authority, row.actor_reference
            ),
            joined_at=row.joined_at,
            left_at=row.left_at,
        )


    def insert_session(self, value: InteractionSession) -> InteractionSession:
        conversation_id = self._internal_id(
            "conversation", value.tenant_id, value.conversation_public_id
        )
        participant_id = self._internal_id(
            "participant", value.tenant_id, value.participant_public_id
        )
        if conversation_id is None or participant_id is None:
            raise IA0RepositoryError(
                "IA0_SESSION_REFERENCE_NOT_FOUND",
                "conversation or participant not found",
            )
        auth = value.authentication_reference
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_sessions("
                "public_id,tenant_id,conversation_id,participant_id,lifecycle_status,"
                "identity_resolution_state,verification_state,started_at,expires_at,"
                "closed_at,correlation_id,authentication_authority,authentication_reference"
                ") VALUES(:p,:t,:c,:part,:s,:irs,:vs,:started,:expires,:closed,:corr,:aa,:ar)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": conversation_id,
                "part": participant_id,
                "s": value.status.value,
                "irs": value.identity_resolution_state.value,
                "vs": value.verification_state.value,
                "started": value.started_at,
                "expires": value.expires_at,
                "closed": value.closed_at,
                "corr": str(value.correlation_id),
                "aa": auth.authority if auth else None,
                "ar": auth.reference if auth else None,
            },
        )
        return self.session(value.tenant_id, value.public_id)

    def session(self, tenant_id: int, public_id: UUID) -> InteractionSession | None:
        row = self.db_session.execute(
            text(
                "SELECT s.*,c.public_id conversation_public_id,"
                "p.public_id participant_public_id "
                "FROM ia0_interaction_sessions s "
                "JOIN ia0_conversations c ON "
                "(c.tenant_id,c.id)=(s.tenant_id,s.conversation_id) "
                "JOIN ia0_conversation_participants p ON "
                "(p.tenant_id,p.id)=(s.tenant_id,s.participant_id) "
                "WHERE s.tenant_id=:t AND s.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return InteractionSession(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            conversation_public_id=UUID(str(row.conversation_public_id)),
            participant_public_id=UUID(str(row.participant_public_id)),
            status=InteractionSessionStatus(row.lifecycle_status),
            identity_resolution_state=IdentityResolutionState(
                row.identity_resolution_state
            ),
            verification_state=VerificationState(row.verification_state),
            started_at=row.started_at,
            correlation_id=UUID(str(row.correlation_id)),
            expires_at=row.expires_at,
            closed_at=row.closed_at,
            authentication_reference=_ref(
                row.authentication_authority, row.authentication_reference
            ),
        )

    def close_session(
        self, tenant_id: int, public_id: UUID, closed_at: datetime
    ) -> InteractionSession:
        updated = self.db_session.execute(
            text(
                "UPDATE ia0_interaction_sessions "
                "SET lifecycle_status='closed',closed_at=:at,"
                "row_version=row_version+1,updated_at=now() "
                "WHERE tenant_id=:t AND public_id=:p "
                "AND lifecycle_status='active' RETURNING public_id"
            ),
            {"at": closed_at, "t": tenant_id, "p": str(public_id)},
        ).scalar()
        if not updated:
            raise IA0RepositoryError("IA0_SESSION_NOT_ACTIVE", "session not active")
        return self.session(tenant_id, public_id)

    def insert_message(self, value: InteractionMessage) -> InteractionMessage:
        conversation_id = self._internal_id(
            "conversation", value.tenant_id, value.conversation_public_id
        )
        session_id = self._internal_id(
            "session", value.tenant_id, value.interaction_session_public_id
        )
        participant_id = self._internal_id(
            "participant", value.tenant_id, value.participant_public_id
        )
        if conversation_id is None:
            raise IA0RepositoryError("IA0_CONVERSATION_NOT_FOUND", "conversation not found")
        if value.interaction_session_public_id and session_id is None:
            raise IA0RepositoryError("IA0_SESSION_NOT_FOUND", "session not found")
        if value.participant_public_id and participant_id is None:
            raise IA0RepositoryError("IA0_PARTICIPANT_NOT_FOUND", "participant not found")
        transport = value.transport_reference
        if value.direction is MessageDirection.INBOUND and transport:
            existing = self.db_session.execute(
                text(
                    "SELECT public_id FROM ia0_interaction_messages "
                    "WHERE tenant_id=:t AND direction='inbound' "
                    "AND transport_authority=:a AND transport_reference=:r "
                    "FOR UPDATE"
                ),
                {
                    "t": value.tenant_id,
                    "a": transport.authority,
                    "r": transport.reference,
                },
            ).scalar()
            if existing:
                current = self.message(value.tenant_id, UUID(str(existing)))
                if current != replace(value, public_id=current.public_id):
                    raise IA0RepositoryError(
                        "IA0_INBOUND_TRANSPORT_CONFLICT",
                        "transport identity reused with different semantic message",
                    )
                return current
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_messages("
                "public_id,tenant_id,conversation_id,interaction_session_id,"
                "participant_id,direction,occurred_at,correlation_id,causation_id,"
                "content,transport_authority,transport_reference,"
                "artifact_references,provenance"
                ") VALUES(:p,:t,:c,:s,:part,:d,:at,:corr,:cause,"
                "CAST(:content AS jsonb),:ta,:tr,CAST(:artifacts AS jsonb),"
                "CAST(:prov AS jsonb))"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": conversation_id,
                "s": session_id,
                "part": participant_id,
                "d": value.direction.value,
                "at": value.occurred_at,
                "corr": str(value.correlation_id),
                "cause": str(value.causation_id) if value.causation_id else None,
                "content": _json(value.content),
                "ta": transport.authority if transport else None,
                "tr": transport.reference if transport else None,
                "artifacts": _json(value.artifact_references),
                "prov": _json(value.provenance),
            },
        )
        return self.message(value.tenant_id, value.public_id)

    def message(self, tenant_id: int, public_id: UUID) -> InteractionMessage | None:
        row = self.db_session.execute(
            text(
                "SELECT m.*,c.public_id conversation_public_id,"
                "s.public_id session_public_id,p.public_id participant_public_id "
                "FROM ia0_interaction_messages m "
                "JOIN ia0_conversations c ON "
                "(c.tenant_id,c.id)=(m.tenant_id,m.conversation_id) "
                "LEFT JOIN ia0_interaction_sessions s ON "
                "(s.tenant_id,s.id)=(m.tenant_id,m.interaction_session_id) "
                "LEFT JOIN ia0_conversation_participants p ON "
                "(p.tenant_id,p.id)=(m.tenant_id,m.participant_id) "
                "WHERE m.tenant_id=:t AND m.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        artifact_refs = tuple(
            PublicAuthorityReference(item["authority"], item["reference"])
            for item in (row.artifact_references or [])
        )
        return InteractionMessage(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            conversation_public_id=UUID(str(row.conversation_public_id)),
            direction=MessageDirection(row.direction),
            occurred_at=row.occurred_at,
            correlation_id=UUID(str(row.correlation_id)),
            content=tuple(_content_part(item) for item in row.content),
            interaction_session_public_id=(
                UUID(str(row.session_public_id)) if row.session_public_id else None
            ),
            participant_public_id=(
                UUID(str(row.participant_public_id))
                if row.participant_public_id
                else None
            ),
            transport_reference=_ref(
                row.transport_authority, row.transport_reference
            ),
            artifact_references=artifact_refs,
            provenance=_provenance(row.provenance),
            causation_id=UUID(str(row.causation_id)) if row.causation_id else None,
        )


    def insert_intent(self, value: InteractionIntent) -> InteractionIntent:
        conversation_id = self._internal_id(
            "conversation", value.tenant_id, value.conversation_public_id
        )
        session_id = self._internal_id(
            "session", value.tenant_id, value.interaction_session_public_id
        )
        message_id = self._internal_id(
            "message", value.tenant_id, value.source_message_public_id
        )
        if conversation_id is None:
            raise IA0RepositoryError("IA0_CONVERSATION_NOT_FOUND", "conversation not found")
        if value.interaction_session_public_id and session_id is None:
            raise IA0RepositoryError("IA0_SESSION_NOT_FOUND", "session not found")
        if value.source_message_public_id and message_id is None:
            raise IA0RepositoryError("IA0_MESSAGE_NOT_FOUND", "message not found")
        result = value.result_reference
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_intents("
                "public_id,tenant_id,conversation_id,interaction_session_id,"
                "source_message_id,intent_code,lifecycle_status,occurred_at,"
                "correlation_id,causation_id,proposal_provenance,"
                "validation_outcome,domain_bridge,result_authority,result_reference"
                ") VALUES(:p,:t,:c,:s,:m,:code,:ls,:at,:corr,:cause,"
                "CAST(:prov AS jsonb),:validation,CAST(:bridge AS jsonb),:ra,:rr)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": conversation_id,
                "s": session_id,
                "m": message_id,
                "code": value.intent_code,
                "ls": value.status.value,
                "at": value.occurred_at,
                "corr": str(value.correlation_id),
                "cause": str(value.causation_id) if value.causation_id else None,
                "prov": _json(value.proposal_provenance),
                "validation": value.validation_outcome,
                "bridge": _json(value.domain_bridge),
                "ra": result.authority if result else None,
                "rr": result.reference if result else None,
            },
        )
        return self.intent(value.tenant_id, value.public_id)

    def intent(self, tenant_id: int, public_id: UUID) -> InteractionIntent | None:
        row = self.db_session.execute(
            text(
                "SELECT i.*,c.public_id conversation_public_id,"
                "s.public_id session_public_id,m.public_id message_public_id "
                "FROM ia0_interaction_intents i "
                "JOIN ia0_conversations c ON "
                "(c.tenant_id,c.id)=(i.tenant_id,i.conversation_id) "
                "LEFT JOIN ia0_interaction_sessions s ON "
                "(s.tenant_id,s.id)=(i.tenant_id,i.interaction_session_id) "
                "LEFT JOIN ia0_interaction_messages m ON "
                "(m.tenant_id,m.id)=(i.tenant_id,i.source_message_id) "
                "WHERE i.tenant_id=:t AND i.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return InteractionIntent(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            conversation_public_id=UUID(str(row.conversation_public_id)),
            intent_code=row.intent_code,
            status=InteractionIntentStatus(row.lifecycle_status),
            occurred_at=row.occurred_at,
            correlation_id=UUID(str(row.correlation_id)),
            interaction_session_public_id=(
                UUID(str(row.session_public_id)) if row.session_public_id else None
            ),
            source_message_public_id=(
                UUID(str(row.message_public_id)) if row.message_public_id else None
            ),
            proposal_provenance=_provenance(row.proposal_provenance),
            validation_outcome=row.validation_outcome,
            domain_bridge=_bridge(row.domain_bridge),
            result_reference=_ref(row.result_authority, row.result_reference),
            causation_id=UUID(str(row.causation_id)) if row.causation_id else None,
        )

    def replace_intent(self, value: InteractionIntent) -> InteractionIntent:
        result = value.result_reference
        updated = self.db_session.execute(
            text(
                "UPDATE ia0_interaction_intents SET lifecycle_status=:ls,"
                "validation_outcome=:vo,domain_bridge=CAST(:bridge AS jsonb),"
                "result_authority=:ra,result_reference=:rr,"
                "row_version=row_version+1,updated_at=now() "
                "WHERE tenant_id=:t AND public_id=:p RETURNING public_id"
            ),
            {
                "ls": value.status.value,
                "vo": value.validation_outcome,
                "bridge": _json(value.domain_bridge),
                "ra": result.authority if result else None,
                "rr": result.reference if result else None,
                "t": value.tenant_id,
                "p": str(value.public_id),
            },
        ).scalar()
        if not updated:
            raise IA0RepositoryError("IA0_INTENT_NOT_FOUND", "intent not found")
        return self.intent(value.tenant_id, value.public_id)

    def insert_handoff(self, value: InteractionHandoff) -> InteractionHandoff:
        conversation_id = self._internal_id(
            "conversation", value.tenant_id, value.conversation_public_id
        )
        session_id = self._internal_id(
            "session", value.tenant_id, value.interaction_session_public_id
        )
        intent_id = self._internal_id(
            "intent", value.tenant_id, value.intent_public_id
        )
        if conversation_id is None:
            raise IA0RepositoryError("IA0_CONVERSATION_NOT_FOUND", "conversation not found")
        if value.interaction_session_public_id and session_id is None:
            raise IA0RepositoryError("IA0_SESSION_NOT_FOUND", "session not found")
        if value.intent_public_id and intent_id is None:
            raise IA0RepositoryError("IA0_INTENT_NOT_FOUND", "intent not found")
        workflow = value.workflow_reference
        task = value.task_reference
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_handoffs("
                "public_id,tenant_id,conversation_id,interaction_session_id,"
                "intent_id,lifecycle_status,requested_at,accepted_at,closed_at,"
                "workflow_authority,workflow_reference,task_authority,task_reference,"
                "correlation_id,causation_id"
                ") VALUES(:p,:t,:c,:s,:i,:ls,:rq,:ac,:cl,:wa,:wr,:ta,:tr,:corr,:cause)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": conversation_id,
                "s": session_id,
                "i": intent_id,
                "ls": value.status.value,
                "rq": value.requested_at,
                "ac": value.accepted_at,
                "cl": value.closed_at,
                "wa": workflow.authority if workflow else None,
                "wr": workflow.reference if workflow else None,
                "ta": task.authority if task else None,
                "tr": task.reference if task else None,
                "corr": str(value.correlation_id),
                "cause": str(value.causation_id) if value.causation_id else None,
            },
        )
        return self.handoff(value.tenant_id, value.public_id)

    def handoff(self, tenant_id: int, public_id: UUID) -> InteractionHandoff | None:
        row = self.db_session.execute(
            text(
                "SELECT h.*,c.public_id conversation_public_id,"
                "s.public_id session_public_id,i.public_id intent_public_id "
                "FROM ia0_interaction_handoffs h "
                "JOIN ia0_conversations c ON "
                "(c.tenant_id,c.id)=(h.tenant_id,h.conversation_id) "
                "LEFT JOIN ia0_interaction_sessions s ON "
                "(s.tenant_id,s.id)=(h.tenant_id,h.interaction_session_id) "
                "LEFT JOIN ia0_interaction_intents i ON "
                "(i.tenant_id,i.id)=(h.tenant_id,h.intent_id) "
                "WHERE h.tenant_id=:t AND h.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return InteractionHandoff(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            conversation_public_id=UUID(str(row.conversation_public_id)),
            status=InteractionHandoffStatus(row.lifecycle_status),
            requested_at=row.requested_at,
            correlation_id=UUID(str(row.correlation_id)),
            interaction_session_public_id=(
                UUID(str(row.session_public_id)) if row.session_public_id else None
            ),
            intent_public_id=(
                UUID(str(row.intent_public_id)) if row.intent_public_id else None
            ),
            workflow_reference=_ref(row.workflow_authority, row.workflow_reference),
            task_reference=_ref(row.task_authority, row.task_reference),
            accepted_at=row.accepted_at,
            closed_at=row.closed_at,
            causation_id=UUID(str(row.causation_id)) if row.causation_id else None,
        )


    def append_event(self, value: InteractionEvent) -> InteractionEvent:
        conversation_id = self._internal_id(
            "conversation", value.tenant_id, value.conversation_public_id
        )
        if conversation_id is None:
            raise IA0RepositoryError("IA0_CONVERSATION_NOT_FOUND", "conversation not found")
        session_id = self._internal_id(
            "session", value.tenant_id, value.interaction_session_public_id
        )
        participant_id = self._internal_id(
            "participant", value.tenant_id, value.participant_public_id
        )
        message_id = self._internal_id(
            "message", value.tenant_id, value.message_public_id
        )
        intent_id = self._internal_id(
            "intent", value.tenant_id, value.intent_public_id
        )
        handoff_id = self._internal_id(
            "handoff", value.tenant_id, value.handoff_public_id
        )
        optional_refs = (
            (value.interaction_session_public_id, session_id, "IA0_SESSION_NOT_FOUND"),
            (value.participant_public_id, participant_id, "IA0_PARTICIPANT_NOT_FOUND"),
            (value.message_public_id, message_id, "IA0_MESSAGE_NOT_FOUND"),
            (value.intent_public_id, intent_id, "IA0_INTENT_NOT_FOUND"),
            (value.handoff_public_id, handoff_id, "IA0_HANDOFF_NOT_FOUND"),
        )
        for public_ref, internal_ref, code in optional_refs:
            if public_ref is not None and internal_ref is None:
                raise IA0RepositoryError(code, "event reference not found or cross-tenant")
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_events("
                "public_id,tenant_id,conversation_id,interaction_session_id,"
                "participant_id,message_id,intent_id,handoff_id,event_type,"
                "source_authority,source_reference,correlation_id,causation_id,occurred_at"
                ") VALUES(:p,:t,:c,:s,:part,:m,:i,:h,:e,:sa,:sr,:corr,:cause,:at)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "c": conversation_id,
                "s": session_id,
                "part": participant_id,
                "m": message_id,
                "i": intent_id,
                "h": handoff_id,
                "e": value.event_type,
                "sa": value.source_reference.authority,
                "sr": value.source_reference.reference,
                "corr": str(value.correlation_id),
                "cause": str(value.causation_id) if value.causation_id else None,
                "at": value.occurred_at,
            },
        )
        return self.event(value.tenant_id, value.public_id)

    def event(self, tenant_id: int, public_id: UUID) -> InteractionEvent | None:
        row = self.db_session.execute(
            text(
                "SELECT e.*,c.public_id conversation_public_id,"
                "s.public_id session_public_id,p.public_id participant_public_id,"
                "m.public_id message_public_id,i.public_id intent_public_id,"
                "h.public_id handoff_public_id "
                "FROM ia0_interaction_events e "
                "JOIN ia0_conversations c ON "
                "(c.tenant_id,c.id)=(e.tenant_id,e.conversation_id) "
                "LEFT JOIN ia0_interaction_sessions s ON "
                "(s.tenant_id,s.id)=(e.tenant_id,e.interaction_session_id) "
                "LEFT JOIN ia0_conversation_participants p ON "
                "(p.tenant_id,p.id)=(e.tenant_id,e.participant_id) "
                "LEFT JOIN ia0_interaction_messages m ON "
                "(m.tenant_id,m.id)=(e.tenant_id,e.message_id) "
                "LEFT JOIN ia0_interaction_intents i ON "
                "(i.tenant_id,i.id)=(e.tenant_id,e.intent_id) "
                "LEFT JOIN ia0_interaction_handoffs h ON "
                "(h.tenant_id,h.id)=(e.tenant_id,e.handoff_id) "
                "WHERE e.tenant_id=:t AND e.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return InteractionEvent(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            conversation_public_id=UUID(str(row.conversation_public_id)),
            event_type=row.event_type,
            source_reference=PublicAuthorityReference(
                row.source_authority, row.source_reference
            ),
            correlation_id=UUID(str(row.correlation_id)),
            occurred_at=row.occurred_at,
            interaction_session_public_id=(
                UUID(str(row.session_public_id)) if row.session_public_id else None
            ),
            participant_public_id=(
                UUID(str(row.participant_public_id))
                if row.participant_public_id
                else None
            ),
            message_public_id=(
                UUID(str(row.message_public_id)) if row.message_public_id else None
            ),
            intent_public_id=(
                UUID(str(row.intent_public_id)) if row.intent_public_id else None
            ),
            handoff_public_id=(
                UUID(str(row.handoff_public_id)) if row.handoff_public_id else None
            ),
            causation_id=UUID(str(row.causation_id)) if row.causation_id else None,
        )

    def insert_capability(
        self, value: InteractionCapabilityGrant
    ) -> InteractionCapabilityGrant:
        participant_id = self._internal_id(
            "participant", value.tenant_id, value.subject_participant_public_id
        )
        if participant_id is None:
            raise IA0RepositoryError("IA0_PARTICIPANT_NOT_FOUND", "participant not found")
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_capability_grants("
                "public_id,tenant_id,subject_participant_id,capability_code,scope,"
                "lifecycle_status,issuer_authority,issuer_reference,"
                "provenance_authority,provenance_reference,effective_from,"
                "expires_at,revoked_at"
                ") VALUES(:p,:t,:part,:code,:scope,:ls,:ia,:ir,:pa,:pr,:ef,:ex,:rv)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "part": participant_id,
                "code": value.capability_code,
                "scope": value.scope,
                "ls": value.status.value,
                "ia": value.issuer_reference.authority,
                "ir": value.issuer_reference.reference,
                "pa": value.provenance.authority,
                "pr": value.provenance.reference,
                "ef": value.effective_from,
                "ex": value.expires_at,
                "rv": value.revoked_at,
            },
        )
        return self.capability(value.tenant_id, value.public_id)

    def capability(
        self, tenant_id: int, public_id: UUID
    ) -> InteractionCapabilityGrant | None:
        row = self.db_session.execute(
            text(
                "SELECT g.*,p.public_id participant_public_id "
                "FROM ia0_interaction_capability_grants g "
                "JOIN ia0_conversation_participants p ON "
                "(p.tenant_id,p.id)=(g.tenant_id,g.subject_participant_id) "
                "WHERE g.tenant_id=:t AND g.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return InteractionCapabilityGrant(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            subject_participant_public_id=UUID(str(row.participant_public_id)),
            capability_code=row.capability_code,
            scope=row.scope,
            issuer_reference=PublicAuthorityReference(
                row.issuer_authority, row.issuer_reference
            ),
            status=InteractionCapabilityStatus(row.lifecycle_status),
            effective_from=row.effective_from,
            provenance=PublicAuthorityReference(
                row.provenance_authority, row.provenance_reference
            ),
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
        )

    def insert_context_binding(
        self, value: InteractionContextBinding
    ) -> InteractionContextBinding:
        session_id = self._internal_id(
            "session", value.tenant_id, value.interaction_session_public_id
        )
        participant_id = self._internal_id(
            "participant", value.tenant_id, value.participant_public_id
        )
        if session_id is None:
            raise IA0RepositoryError("IA0_SESSION_NOT_FOUND", "session not found")
        if value.participant_public_id and participant_id is None:
            raise IA0RepositoryError("IA0_PARTICIPANT_NOT_FOUND", "participant not found")
        self.db_session.execute(
            text(
                "INSERT INTO ia0_interaction_context_bindings("
                "public_id,tenant_id,interaction_session_id,participant_id,"
                "source_authority,source_reference,source_version,source_hash,"
                "purpose_code,provenance_authority,provenance_reference,"
                "effective_from,expires_at,ended_at,correlation_id"
                ") VALUES(:p,:t,:s,:part,:sa,:sr,:sv,:sh,:purpose,:pa,:pr,"
                ":ef,:ex,:ended,:corr)"
            ),
            {
                "p": str(value.public_id),
                "t": value.tenant_id,
                "s": session_id,
                "part": participant_id,
                "sa": value.source_reference.authority,
                "sr": value.source_reference.reference,
                "sv": value.source_version,
                "sh": value.source_hash,
                "purpose": value.purpose_code,
                "pa": value.provenance.authority,
                "pr": value.provenance.reference,
                "ef": value.effective_from,
                "ex": value.expires_at,
                "ended": value.ended_at,
                "corr": str(value.correlation_id) if value.correlation_id else None,
            },
        )
        return self.context_binding(value.tenant_id, value.public_id)

    def context_binding(
        self, tenant_id: int, public_id: UUID
    ) -> InteractionContextBinding | None:
        row = self.db_session.execute(
            text(
                "SELECT b.*,s.public_id session_public_id,"
                "p.public_id participant_public_id "
                "FROM ia0_interaction_context_bindings b "
                "JOIN ia0_interaction_sessions s ON "
                "(s.tenant_id,s.id)=(b.tenant_id,b.interaction_session_id) "
                "LEFT JOIN ia0_conversation_participants p ON "
                "(p.tenant_id,p.id)=(b.tenant_id,b.participant_id) "
                "WHERE b.tenant_id=:t AND b.public_id=:p"
            ),
            {"t": tenant_id, "p": str(public_id)},
        ).first()
        if not row:
            return None
        return InteractionContextBinding(
            tenant_id=row.tenant_id,
            public_id=UUID(str(row.public_id)),
            interaction_session_public_id=UUID(str(row.session_public_id)),
            source_reference=PublicAuthorityReference(
                row.source_authority, row.source_reference
            ),
            purpose_code=row.purpose_code,
            provenance=PublicAuthorityReference(
                row.provenance_authority, row.provenance_reference
            ),
            effective_from=row.effective_from,
            participant_public_id=(
                UUID(str(row.participant_public_id))
                if row.participant_public_id
                else None
            ),
            source_version=row.source_version,
            source_hash=row.source_hash,
            expires_at=row.expires_at,
            ended_at=row.ended_at,
            correlation_id=UUID(str(row.correlation_id)) if row.correlation_id else None,
        )

    def context_binding_by_public_id(
        self, public_id: UUID
    ) -> InteractionContextBinding | None:
        """Resolve an IA0 binding only when the public id is globally unambiguous.

        IA0 public ids are tenant-scoped. Customer Channel intentionally does
        not supply tenant authority, so a duplicated public id across tenants
        must fail closed rather than select a tenant implicitly.
        """
        rows = self.db_session.execute(
            text(
                "SELECT tenant_id FROM ia0_interaction_context_bindings "
                "WHERE public_id=:p ORDER BY tenant_id"
            ),
            {"p": str(public_id)},
        ).scalars().all()
        tenant_ids = tuple(dict.fromkeys(int(value) for value in rows))
        if not tenant_ids:
            return None
        if len(tenant_ids) != 1:
            raise IA0RepositoryError(
                "IA0_CONTEXT_BINDING_AMBIGUOUS",
                "context binding public id is ambiguous across tenants",
            )
        return self.context_binding(tenant_ids[0], public_id)
