CREATE TABLE public.ia0_commands (
    id bigserial PRIMARY KEY,
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    command_key varchar(180) NOT NULL,
    request_fingerprint char(64) NOT NULL,
    command_type varchar(120) NOT NULL,
    result_type varchar(120),
    result_public_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT uq_ia0_cmd_key UNIQUE (tenant_id, command_key),
    CONSTRAINT ck_ia0_cmd_sha CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_ia0_cmd_type CHECK (
        command_type = lower(btrim(command_type)) AND length(command_type) > 0
    ),
    CONSTRAINT ck_ia0_cmd_result CHECK (
        (result_type IS NULL AND result_public_id IS NULL AND completed_at IS NULL)
        OR
        (result_type IS NOT NULL AND result_public_id IS NOT NULL AND completed_at IS NOT NULL)
    )
);

CREATE TABLE public.ia0_external_channel_identities (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    channel_kind varchar(120) NOT NULL,
    source_code varchar(120) NOT NULL,
    opaque_subject varchar(500) NOT NULL,
    lifecycle_status varchar(24) NOT NULL DEFAULT 'active',
    resolution_state varchar(32) NOT NULL DEFAULT 'unresolved',
    party_authority varchar(160),
    party_reference varchar(500),
    resolution_provenance_authority varchar(160),
    resolution_provenance_reference varchar(500),
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_ext_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_ext_tid UNIQUE (tenant_id, id),
    CONSTRAINT uq_ia0_ext_identity UNIQUE (
        tenant_id, channel_kind, source_code, opaque_subject
    ),
    CONSTRAINT ck_ia0_ext_channel CHECK (
        channel_kind = lower(btrim(channel_kind)) AND length(channel_kind) > 0
    ),
    CONSTRAINT ck_ia0_ext_source CHECK (
        source_code = lower(btrim(source_code)) AND length(source_code) > 0
    ),
    CONSTRAINT ck_ia0_ext_subject CHECK (length(btrim(opaque_subject)) > 0),
    CONSTRAINT ck_ia0_ext_status CHECK (lifecycle_status IN ('active','disabled')),
    CONSTRAINT ck_ia0_ext_resolution CHECK (
        resolution_state IN ('unresolved','channel_identified','party_resolved')
    ),
    CONSTRAINT ck_ia0_ext_party_pair CHECK (
        (resolution_state = 'party_resolved'
         AND party_authority IS NOT NULL
         AND party_reference IS NOT NULL)
        OR
        (resolution_state <> 'party_resolved'
         AND party_authority IS NULL
         AND party_reference IS NULL)
    ),
    CONSTRAINT ck_ia0_ext_prov_pair CHECK (
        (resolution_provenance_authority IS NULL
         AND resolution_provenance_reference IS NULL)
        OR
        (resolution_provenance_authority IS NOT NULL
         AND resolution_provenance_reference IS NOT NULL)
    ),
    CONSTRAINT ck_ia0_ext_rowver CHECK (row_version >= 1)
);

CREATE TABLE public.ia0_conversations (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    lifecycle_status varchar(16) NOT NULL DEFAULT 'open',
    opened_at timestamptz NOT NULL,
    closed_at timestamptz,
    correlation_id uuid NOT NULL,
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_conv_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_conv_tid UNIQUE (tenant_id, id),
    CONSTRAINT ck_ia0_conv_status CHECK (lifecycle_status IN ('open','closed')),
    CONSTRAINT ck_ia0_conv_closed CHECK (
        (lifecycle_status = 'closed' AND closed_at IS NOT NULL)
        OR
        (lifecycle_status = 'open' AND closed_at IS NULL)
    ),
    CONSTRAINT ck_ia0_conv_rowver CHECK (row_version >= 1)
);

CREATE TABLE public.ia0_conversation_participants (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    conversation_id bigint NOT NULL,
    participant_kind varchar(40) NOT NULL,
    actor_authority varchar(160) NOT NULL,
    actor_reference varchar(500) NOT NULL,
    joined_at timestamptz NOT NULL,
    left_at timestamptz,
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_part_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_part_tid UNIQUE (tenant_id, id),
    CONSTRAINT uq_ia0_part_conv UNIQUE (tenant_id, id, conversation_id),
    CONSTRAINT fk_ia0_part_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES public.ia0_conversations(tenant_id, id),
    CONSTRAINT ck_ia0_part_kind CHECK (
        participant_kind IN (
            'external_channel_identity',
            'party_reference',
            'pc5_identity_reference',
            'service_identity_reference',
            'ai_participant',
            'system_participant'
        )
    ),
    CONSTRAINT ck_ia0_part_actor CHECK (
        length(btrim(actor_authority)) > 0 AND length(btrim(actor_reference)) > 0
    ),
    CONSTRAINT ck_ia0_part_times CHECK (left_at IS NULL OR left_at >= joined_at),
    CONSTRAINT ck_ia0_part_rowver CHECK (row_version >= 1)
);

CREATE TABLE public.ia0_interaction_sessions (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    conversation_id bigint NOT NULL,
    participant_id bigint NOT NULL,
    lifecycle_status varchar(16) NOT NULL DEFAULT 'active',
    identity_resolution_state varchar(32) NOT NULL,
    verification_state varchar(32) NOT NULL,
    started_at timestamptz NOT NULL,
    expires_at timestamptz,
    closed_at timestamptz,
    correlation_id uuid NOT NULL,
    authentication_authority varchar(160),
    authentication_reference varchar(500),
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_sess_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_sess_tid UNIQUE (tenant_id, id),
    CONSTRAINT uq_ia0_sess_conv UNIQUE (tenant_id, id, conversation_id),
    CONSTRAINT fk_ia0_sess_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES public.ia0_conversations(tenant_id, id),
    CONSTRAINT fk_ia0_sess_part_conv FOREIGN KEY (
        tenant_id, participant_id, conversation_id
    ) REFERENCES public.ia0_conversation_participants(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT ck_ia0_sess_status CHECK (
        lifecycle_status IN ('active','expired','closed')
    ),
    CONSTRAINT ck_ia0_sess_resolution CHECK (
        identity_resolution_state IN (
            'unresolved','channel_identified','party_resolved'
        )
    ),
    CONSTRAINT ck_ia0_sess_verification CHECK (
        verification_state IN (
            'unverified','channel_verified','authenticated_external'
        )
    ),
    CONSTRAINT ck_ia0_sess_closed CHECK (
        (lifecycle_status = 'closed' AND closed_at IS NOT NULL)
        OR
        (lifecycle_status <> 'closed')
    ),
    CONSTRAINT ck_ia0_sess_active CHECK (
        lifecycle_status <> 'active' OR closed_at IS NULL
    ),
    CONSTRAINT ck_ia0_sess_auth_pair CHECK (
        (verification_state = 'authenticated_external'
         AND authentication_authority IS NOT NULL
         AND authentication_reference IS NOT NULL)
        OR
        (verification_state <> 'authenticated_external'
         AND (
             (authentication_authority IS NULL AND authentication_reference IS NULL)
             OR
             (authentication_authority IS NOT NULL AND authentication_reference IS NOT NULL)
         ))
    ),
    CONSTRAINT ck_ia0_sess_expiry CHECK (
        expires_at IS NULL OR expires_at > started_at
    ),
    CONSTRAINT ck_ia0_sess_rowver CHECK (row_version >= 1)
);
CREATE TABLE public.ia0_interaction_messages (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    conversation_id bigint NOT NULL,
    interaction_session_id bigint,
    participant_id bigint,
    direction varchar(16) NOT NULL,
    occurred_at timestamptz NOT NULL,
    correlation_id uuid NOT NULL,
    causation_id uuid,
    content jsonb NOT NULL,
    transport_authority varchar(160),
    transport_reference varchar(500),
    artifact_references jsonb NOT NULL DEFAULT '[]'::jsonb,
    provenance jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_msg_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_msg_tid UNIQUE (tenant_id, id),
    CONSTRAINT uq_ia0_msg_conv UNIQUE (tenant_id, id, conversation_id),
    CONSTRAINT fk_ia0_msg_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES public.ia0_conversations(tenant_id, id),
    CONSTRAINT fk_ia0_msg_sess_conv FOREIGN KEY (
        tenant_id, interaction_session_id, conversation_id
    ) REFERENCES public.ia0_interaction_sessions(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_msg_part_conv FOREIGN KEY (
        tenant_id, participant_id, conversation_id
    ) REFERENCES public.ia0_conversation_participants(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT ck_ia0_msg_direction CHECK (
        direction IN ('inbound','outbound','system')
    ),
    CONSTRAINT ck_ia0_msg_content CHECK (
        jsonb_typeof(content) = 'array' AND jsonb_array_length(content) > 0
    ),
    CONSTRAINT ck_ia0_msg_artifacts CHECK (
        jsonb_typeof(artifact_references) = 'array'
    ),
    CONSTRAINT ck_ia0_msg_provenance CHECK (
        provenance IS NULL OR jsonb_typeof(provenance) = 'object'
    ),
    CONSTRAINT ck_ia0_msg_transport_pair CHECK (
        (transport_authority IS NULL AND transport_reference IS NULL)
        OR
        (transport_authority IS NOT NULL AND transport_reference IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_ia0_msg_inbound_transport
ON public.ia0_interaction_messages(
    tenant_id, transport_authority, transport_reference
)
WHERE direction = 'inbound'
  AND transport_authority IS NOT NULL
  AND transport_reference IS NOT NULL;

CREATE TABLE public.ia0_interaction_intents (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    conversation_id bigint NOT NULL,
    interaction_session_id bigint,
    source_message_id bigint,
    intent_code varchar(180) NOT NULL,
    lifecycle_status varchar(16) NOT NULL,
    occurred_at timestamptz NOT NULL,
    correlation_id uuid NOT NULL,
    causation_id uuid,
    proposal_provenance jsonb,
    validation_outcome varchar(500),
    domain_bridge jsonb,
    result_authority varchar(160),
    result_reference varchar(500),
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_intent_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_intent_tid UNIQUE (tenant_id, id),
    CONSTRAINT uq_ia0_intent_conv UNIQUE (tenant_id, id, conversation_id),
    CONSTRAINT fk_ia0_intent_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES public.ia0_conversations(tenant_id, id),
    CONSTRAINT fk_ia0_intent_sess_conv FOREIGN KEY (
        tenant_id, interaction_session_id, conversation_id
    ) REFERENCES public.ia0_interaction_sessions(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_intent_msg_conv FOREIGN KEY (
        tenant_id, source_message_id, conversation_id
    ) REFERENCES public.ia0_interaction_messages(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT ck_ia0_intent_code CHECK (
        intent_code = lower(btrim(intent_code)) AND length(intent_code) > 0
    ),
    CONSTRAINT ck_ia0_intent_status CHECK (
        lifecycle_status IN (
            'proposed','validated','accepted','rejected','executed','failed'
        )
    ),
    CONSTRAINT ck_ia0_intent_prov CHECK (
        proposal_provenance IS NULL
        OR jsonb_typeof(proposal_provenance) = 'object'
    ),
    CONSTRAINT ck_ia0_intent_bridge_json CHECK (
        domain_bridge IS NULL OR jsonb_typeof(domain_bridge) = 'object'
    ),
    CONSTRAINT ck_ia0_intent_bridge_state CHECK (
        lifecycle_status NOT IN ('accepted','executed','failed')
        OR domain_bridge IS NOT NULL
    ),
    CONSTRAINT ck_ia0_intent_result_pair CHECK (
        (result_authority IS NULL AND result_reference IS NULL)
        OR
        (result_authority IS NOT NULL AND result_reference IS NOT NULL)
    ),
    CONSTRAINT ck_ia0_intent_exec_result CHECK (
        lifecycle_status <> 'executed'
        OR (result_authority IS NOT NULL AND result_reference IS NOT NULL)
    ),
    CONSTRAINT ck_ia0_intent_rowver CHECK (row_version >= 1)
);

CREATE TABLE public.ia0_interaction_handoffs (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    conversation_id bigint NOT NULL,
    interaction_session_id bigint,
    intent_id bigint,
    lifecycle_status varchar(16) NOT NULL,
    requested_at timestamptz NOT NULL,
    accepted_at timestamptz,
    closed_at timestamptz,
    workflow_authority varchar(160),
    workflow_reference varchar(500),
    task_authority varchar(160),
    task_reference varchar(500),
    correlation_id uuid NOT NULL,
    causation_id uuid,
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_handoff_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_handoff_tid UNIQUE (tenant_id, id),
    CONSTRAINT uq_ia0_handoff_conv UNIQUE (tenant_id, id, conversation_id),
    CONSTRAINT fk_ia0_handoff_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES public.ia0_conversations(tenant_id, id),
    CONSTRAINT fk_ia0_handoff_sess_conv FOREIGN KEY (
        tenant_id, interaction_session_id, conversation_id
    ) REFERENCES public.ia0_interaction_sessions(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_handoff_intent_conv FOREIGN KEY (
        tenant_id, intent_id, conversation_id
    ) REFERENCES public.ia0_interaction_intents(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT ck_ia0_handoff_status CHECK (
        lifecycle_status IN ('requested','accepted','rejected','closed')
    ),
    CONSTRAINT ck_ia0_handoff_workflow_pair CHECK (
        (workflow_authority IS NULL AND workflow_reference IS NULL)
        OR
        (workflow_authority IS NOT NULL AND workflow_reference IS NOT NULL)
    ),
    CONSTRAINT ck_ia0_handoff_task_pair CHECK (
        (task_authority IS NULL AND task_reference IS NULL)
        OR
        (task_authority IS NOT NULL AND task_reference IS NOT NULL)
    ),
    CONSTRAINT ck_ia0_handoff_workflow_state CHECK (
        lifecycle_status NOT IN ('accepted','closed')
        OR (workflow_authority IS NOT NULL AND workflow_reference IS NOT NULL)
    ),
    CONSTRAINT ck_ia0_handoff_task_requires_workflow CHECK (
        task_authority IS NULL OR workflow_authority IS NOT NULL
    ),
    CONSTRAINT ck_ia0_handoff_rowver CHECK (row_version >= 1)
);

CREATE TABLE public.ia0_interaction_capability_grants (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    subject_participant_id bigint NOT NULL,
    capability_code varchar(180) NOT NULL,
    scope varchar(500) NOT NULL,
    lifecycle_status varchar(16) NOT NULL DEFAULT 'active',
    issuer_authority varchar(160) NOT NULL,
    issuer_reference varchar(500) NOT NULL,
    provenance_authority varchar(160) NOT NULL,
    provenance_reference varchar(500) NOT NULL,
    effective_from timestamptz NOT NULL,
    expires_at timestamptz,
    revoked_at timestamptz,
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_cap_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_cap_tid UNIQUE (tenant_id, id),
    CONSTRAINT fk_ia0_cap_part FOREIGN KEY (tenant_id, subject_participant_id)
        REFERENCES public.ia0_conversation_participants(tenant_id, id),
    CONSTRAINT ck_ia0_cap_status CHECK (
        lifecycle_status IN ('active','revoked','expired')
    ),
    CONSTRAINT ck_ia0_cap_code CHECK (
        capability_code = lower(btrim(capability_code))
        AND length(capability_code) > 0
    ),
    CONSTRAINT ck_ia0_cap_scope CHECK (length(btrim(scope)) > 0),
    CONSTRAINT ck_ia0_cap_expiry CHECK (
        expires_at IS NULL OR expires_at > effective_from
    ),
    CONSTRAINT ck_ia0_cap_revoked CHECK (
        lifecycle_status <> 'revoked' OR revoked_at IS NOT NULL
    ),
    CONSTRAINT ck_ia0_cap_rowver CHECK (row_version >= 1)
);

CREATE TABLE public.ia0_interaction_context_bindings (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    interaction_session_id bigint NOT NULL,
    participant_id bigint,
    source_authority varchar(160) NOT NULL,
    source_reference varchar(500) NOT NULL,
    source_version varchar(240),
    source_hash char(64),
    purpose_code varchar(180) NOT NULL,
    provenance_authority varchar(160) NOT NULL,
    provenance_reference varchar(500) NOT NULL,
    effective_from timestamptz NOT NULL,
    expires_at timestamptz,
    ended_at timestamptz,
    correlation_id uuid,
    row_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_ctx_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_ctx_tid UNIQUE (tenant_id, id),
    CONSTRAINT fk_ia0_ctx_sess FOREIGN KEY (tenant_id, interaction_session_id)
        REFERENCES public.ia0_interaction_sessions(tenant_id, id),
    CONSTRAINT fk_ia0_ctx_part FOREIGN KEY (tenant_id, participant_id)
        REFERENCES public.ia0_conversation_participants(tenant_id, id),
    CONSTRAINT ck_ia0_ctx_source CHECK (
        length(btrim(source_authority)) > 0
        AND length(btrim(source_reference)) > 0
    ),
    CONSTRAINT ck_ia0_ctx_purpose CHECK (
        purpose_code = lower(btrim(purpose_code)) AND length(purpose_code) > 0
    ),
    CONSTRAINT ck_ia0_ctx_prov CHECK (
        length(btrim(provenance_authority)) > 0
        AND length(btrim(provenance_reference)) > 0
    ),
    CONSTRAINT ck_ia0_ctx_hash CHECK (
        source_hash IS NULL OR source_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_ia0_ctx_expiry CHECK (
        expires_at IS NULL OR expires_at > effective_from
    ),
    CONSTRAINT ck_ia0_ctx_ended CHECK (
        ended_at IS NULL OR ended_at >= effective_from
    ),
    CONSTRAINT ck_ia0_ctx_rowver CHECK (row_version >= 1)
);
CREATE TABLE public.ia0_interaction_events (
    id bigserial PRIMARY KEY,
    public_id uuid NOT NULL DEFAULT gen_random_uuid(),
    tenant_id bigint NOT NULL REFERENCES public.tenants(id),
    conversation_id bigint NOT NULL,
    interaction_session_id bigint,
    participant_id bigint,
    message_id bigint,
    intent_id bigint,
    handoff_id bigint,
    event_type varchar(180) NOT NULL,
    source_authority varchar(160) NOT NULL,
    source_reference varchar(500) NOT NULL,
    correlation_id uuid NOT NULL,
    causation_id uuid,
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ia0_event_public UNIQUE (tenant_id, public_id),
    CONSTRAINT uq_ia0_event_tid UNIQUE (tenant_id, id),
    CONSTRAINT fk_ia0_event_conv FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES public.ia0_conversations(tenant_id, id),
    CONSTRAINT fk_ia0_event_sess_conv FOREIGN KEY (
        tenant_id, interaction_session_id, conversation_id
    ) REFERENCES public.ia0_interaction_sessions(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_event_part_conv FOREIGN KEY (
        tenant_id, participant_id, conversation_id
    ) REFERENCES public.ia0_conversation_participants(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_event_msg_conv FOREIGN KEY (
        tenant_id, message_id, conversation_id
    ) REFERENCES public.ia0_interaction_messages(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_event_intent_conv FOREIGN KEY (
        tenant_id, intent_id, conversation_id
    ) REFERENCES public.ia0_interaction_intents(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT fk_ia0_event_handoff_conv FOREIGN KEY (
        tenant_id, handoff_id, conversation_id
    ) REFERENCES public.ia0_interaction_handoffs(
        tenant_id, id, conversation_id
    ),
    CONSTRAINT ck_ia0_event_type CHECK (
        event_type = lower(btrim(event_type)) AND length(event_type) > 0
    ),
    CONSTRAINT ck_ia0_event_source CHECK (
        length(btrim(source_authority)) > 0
        AND length(btrim(source_reference)) > 0
    )
);

CREATE INDEX ix_ia0_ext_party
    ON public.ia0_external_channel_identities(
        tenant_id, party_authority, party_reference
    );

CREATE INDEX ix_ia0_conv_status
    ON public.ia0_conversations(tenant_id, lifecycle_status, opened_at);

CREATE INDEX ix_ia0_part_conv
    ON public.ia0_conversation_participants(
        tenant_id, conversation_id, joined_at
    );

CREATE INDEX ix_ia0_sess_conv
    ON public.ia0_interaction_sessions(
        tenant_id, conversation_id, started_at
    );

CREATE INDEX ix_ia0_msg_conv
    ON public.ia0_interaction_messages(
        tenant_id, conversation_id, occurred_at, id
    );

CREATE INDEX ix_ia0_intent_conv
    ON public.ia0_interaction_intents(
        tenant_id, conversation_id, occurred_at, id
    );

CREATE INDEX ix_ia0_handoff_conv
    ON public.ia0_interaction_handoffs(
        tenant_id, conversation_id, requested_at, id
    );

CREATE INDEX ix_ia0_event_conv
    ON public.ia0_interaction_events(
        tenant_id, conversation_id, occurred_at, id
    );

CREATE INDEX ix_ia0_cap_part
    ON public.ia0_interaction_capability_grants(
        tenant_id, subject_participant_id, lifecycle_status
    );

CREATE INDEX ix_ia0_ctx_sess
    ON public.ia0_interaction_context_bindings(
        tenant_id, interaction_session_id, effective_from
    );

CREATE OR REPLACE FUNCTION public.ia0_reject_append_only_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'IA0 interaction message/event history is append-only';
END
$$;

CREATE TRIGGER trg_ia0_message_append_only
BEFORE UPDATE OR DELETE ON public.ia0_interaction_messages
FOR EACH ROW EXECUTE FUNCTION public.ia0_reject_append_only_mutation();

CREATE TRIGGER trg_ia0_event_append_only
BEFORE UPDATE OR DELETE ON public.ia0_interaction_events
FOR EACH ROW EXECUTE FUNCTION public.ia0_reject_append_only_mutation();
