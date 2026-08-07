CREATE OR REPLACE FUNCTION public.xbos_protect_outbox_content()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF ROW(
        NEW.public_id, NEW.tenant_id, NEW.source_event_public_id,
        NEW.aggregate_type, NEW.aggregate_public_id, NEW.event_name,
        NEW.event_version, NEW.payload, NEW.payload_hash,
        NEW.created_at, NEW.correlation_id, NEW.causation_id
    ) IS DISTINCT FROM ROW(
        OLD.public_id, OLD.tenant_id, OLD.source_event_public_id,
        OLD.aggregate_type, OLD.aggregate_public_id, OLD.event_name,
        OLD.event_version, OLD.payload, OLD.payload_hash,
        OLD.created_at, OLD.correlation_id, OLD.causation_id
    ) THEN
        RAISE EXCEPTION 'outbox message content and identity are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER tr_outbox_content_immutable ON public.outbox_messages;
CREATE TRIGGER tr_outbox_content_immutable
BEFORE UPDATE ON public.outbox_messages
FOR EACH ROW EXECUTE FUNCTION public.xbos_protect_outbox_content();

DROP INDEX IF EXISTS public.ix_outbox_tenant_topic_created;

ALTER TABLE public.outbox_messages
    DROP CONSTRAINT IF EXISTS ck_outbox_messages_message_key_nonblank,
    DROP CONSTRAINT IF EXISTS ck_outbox_messages_topic_nonblank,
    DROP CONSTRAINT IF EXISTS uq_outbox_messages_topic_key,
    DROP CONSTRAINT IF EXISTS fk_outbox_messages_org,
    DROP COLUMN IF EXISTS recorded_at,
    DROP COLUMN IF EXISTS occurred_at,
    DROP COLUMN IF EXISTS message_key,
    DROP COLUMN IF EXISTS topic,
    DROP COLUMN IF EXISTS organization_unit_id;

ALTER TABLE public.idempotency_records
    DROP CONSTRAINT ck_idempotency_records_state;

ALTER TABLE public.idempotency_records
    ADD CONSTRAINT ck_idempotency_records_state
    CHECK (processing_state IN ('processing', 'completed', 'failed', 'expired'));
