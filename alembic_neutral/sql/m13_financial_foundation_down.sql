DROP TRIGGER IF EXISTS tr_outbox_content_immutable ON public.outbox_messages;
DROP TRIGGER IF EXISTS tr_financial_event_taxonomy_immutable ON public.financial_event_taxonomy;
DROP TRIGGER IF EXISTS tr_financial_events_immutable ON public.financial_events;
DROP TRIGGER IF EXISTS tr_financial_events_validate_amount ON public.financial_events;
DROP TRIGGER IF EXISTS tr_financial_event_types_immutable ON public.financial_event_type_versions;

DROP FUNCTION IF EXISTS public.xbos_protect_outbox_content();
DROP FUNCTION IF EXISTS public.xbos_validate_financial_event_amount();
DROP FUNCTION IF EXISTS public.xbos_reject_immutable_financial_mutation();

DROP TABLE IF EXISTS public.historical_transformation_exceptions;
DROP TABLE IF EXISTS public.historical_transformation_runs;
DROP TABLE IF EXISTS public.outbox_messages;
DROP TABLE IF EXISTS public.financial_event_taxonomy;
DROP TABLE IF EXISTS public.financial_events;
DROP TABLE IF EXISTS public.financial_event_type_versions;
DROP TABLE IF EXISTS public.idempotency_records;
DROP TABLE IF EXISTS public.payment_provider_accounts;
DROP TABLE IF EXISTS public.operational_financial_accounts;
DROP TABLE IF EXISTS public.financial_counterparties;
DROP TABLE IF EXISTS public.kernel_source_records;

ALTER TABLE IF EXISTS public.organization_units
    DROP CONSTRAINT IF EXISTS fk_organization_units_business_calendar_policy;
DROP TABLE IF EXISTS public.business_cycle_policies;
DROP TABLE IF EXISTS public.tenant_currency_policies;
DROP TABLE IF EXISTS public.currency_assets;
DROP TABLE IF EXISTS public.organization_units;

ALTER TABLE IF EXISTS public.taxonomy_nodes
    DROP CONSTRAINT IF EXISTS uq_taxonomy_nodes_tenant_id_id;
ALTER TABLE IF EXISTS public.users
    DROP CONSTRAINT IF EXISTS uq_users_tenant_id_id;
