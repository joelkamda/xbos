-- Shared Operations aggregate conformance hardening.
-- No new business capability. This makes SO2 command idempotency tenant-scoped,
-- matching SO0 explicit-tenant-context law and SO3-SO10 command ledgers.

ALTER TABLE public.so2_relationship_commands
    ADD COLUMN tenant_id INTEGER NULL;

UPDATE public.so2_relationship_commands c
SET tenant_id = r.tenant_id
FROM public.so2_operational_relationships r
WHERE c.result_id = r.id
  AND c.tenant_id IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.so2_relationship_commands
        WHERE tenant_id IS NULL
    ) THEN
        RAISE EXCEPTION 'SO_AGG_SO2_COMMAND_TENANT_BACKFILL_REQUIRED';
    END IF;
END
$$;

ALTER TABLE public.so2_relationship_commands
    ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE public.so2_relationship_commands
    DROP CONSTRAINT uq_so2_relationship_commands_key;

ALTER TABLE public.so2_relationship_commands
    DROP CONSTRAINT fk_so2_relationship_commands_result;

ALTER TABLE public.so2_relationship_commands
    ADD CONSTRAINT fk_so2_relationship_commands_tenant
        FOREIGN KEY(tenant_id)
        REFERENCES public.tenants(id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT fk_so2_relationship_commands_result
        FOREIGN KEY(tenant_id,result_id)
        REFERENCES public.so2_operational_relationships(tenant_id,id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT uq_so2_relationship_commands_tenant_key
        UNIQUE(tenant_id,command_key);

CREATE INDEX ix_so2_relationship_commands_tenant_created
    ON public.so2_relationship_commands(tenant_id,created_at,id);

COMMENT ON COLUMN public.so2_relationship_commands.tenant_id
IS 'Aggregate conformance hardening: SO2 idempotency namespace is tenant-scoped; same command key may be used independently by different tenants.';
