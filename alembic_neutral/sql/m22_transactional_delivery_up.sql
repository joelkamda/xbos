ALTER TABLE public.idempotency_records
    DROP CONSTRAINT ck_idempotency_records_state;

ALTER TABLE public.idempotency_records
    ADD CONSTRAINT ck_idempotency_records_state
    CHECK (
        processing_state IN (
            'processing', 'completed', 'failed_retryable', 'failed_terminal'
        )
    );

ALTER TABLE public.outbox_messages
    ADD COLUMN organization_unit_id BIGINT,
    ADD COLUMN topic VARCHAR(160),
    ADD COLUMN message_key VARCHAR(200),
    ADD COLUMN occurred_at TIMESTAMPTZ,
    ADD COLUMN recorded_at TIMESTAMPTZ;

ALTER TABLE public.outbox_messages
    ALTER COLUMN organization_unit_id SET NOT NULL,
    ALTER COLUMN topic SET NOT NULL,
    ALTER COLUMN message_key SET NOT NULL,
    ALTER COLUMN occurred_at SET NOT NULL,
    ALTER COLUMN recorded_at SET NOT NULL,
    ADD CONSTRAINT fk_outbox_messages_org FOREIGN KEY
        (tenant_id, organization_unit_id)
        REFERENCES public.organization_units(tenant_id, id) ON DELETE RESTRICT,
    ADD CONSTRAINT uq_outbox_messages_topic_key
        UNIQUE (tenant_id, topic, message_key),
    ADD CONSTRAINT ck_outbox_messages_topic_nonblank
        CHECK (length(btrim(topic)) > 0),
    ADD CONSTRAINT ck_outbox_messages_message_key_nonblank
        CHECK (length(btrim(message_key)) > 0);

CREATE INDEX ix_outbox_tenant_topic_created
    ON public.outbox_messages (tenant_id, topic, created_at DESC);

CREATE OR REPLACE FUNCTION public.xbos_protect_outbox_content()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox messages are durable and cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF ROW(
        NEW.public_id, NEW.tenant_id, NEW.organization_unit_id,
        NEW.source_event_public_id, NEW.aggregate_type,
        NEW.aggregate_public_id, NEW.topic, NEW.message_key,
        NEW.event_name, NEW.event_version, NEW.payload, NEW.payload_hash,
        NEW.occurred_at, NEW.recorded_at, NEW.created_at,
        NEW.correlation_id, NEW.causation_id
    ) IS DISTINCT FROM ROW(
        OLD.public_id, OLD.tenant_id, OLD.organization_unit_id,
        OLD.source_event_public_id, OLD.aggregate_type,
        OLD.aggregate_public_id, OLD.topic, OLD.message_key,
        OLD.event_name, OLD.event_version, OLD.payload, OLD.payload_hash,
        OLD.occurred_at, OLD.recorded_at, OLD.created_at,
        OLD.correlation_id, OLD.causation_id
    ) THEN
        RAISE EXCEPTION 'outbox message content and identity are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER tr_outbox_content_immutable ON public.outbox_messages;
CREATE TRIGGER tr_outbox_content_immutable
BEFORE UPDATE OR DELETE ON public.outbox_messages
FOR EACH ROW EXECUTE FUNCTION public.xbos_protect_outbox_content();
