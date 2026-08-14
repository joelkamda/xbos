-- Reverse aggregate tenant-idempotency hardening only when the data can
-- still satisfy the historical globally-unique SO2 command-key schema.

DO $$
BEGIN
    IF EXISTS (
        SELECT command_key
        FROM public.so2_relationship_commands
        GROUP BY command_key
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'SO_AGG_DOWNGRADE_GLOBAL_COMMAND_KEY_CONFLICT';
    END IF;
END
$$;

DROP INDEX IF EXISTS public.ix_so2_relationship_commands_tenant_created;

ALTER TABLE public.so2_relationship_commands
    DROP CONSTRAINT fk_so2_relationship_commands_result,
    DROP CONSTRAINT fk_so2_relationship_commands_tenant,
    DROP CONSTRAINT uq_so2_relationship_commands_tenant_key;

ALTER TABLE public.so2_relationship_commands
    ADD CONSTRAINT fk_so2_relationship_commands_result
        FOREIGN KEY(result_id)
        REFERENCES public.so2_operational_relationships(id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT uq_so2_relationship_commands_key
        UNIQUE(command_key);

ALTER TABLE public.so2_relationship_commands
    DROP COLUMN tenant_id;
