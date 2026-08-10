DROP VIEW IF EXISTS public.operational_account_reconciliation_series;
DROP INDEX IF EXISTS public.ix_m61_financial_events_target_occurred;
DROP INDEX IF EXISTS public.ix_m61_financial_events_source_occurred;
DROP TRIGGER IF EXISTS tr_financial_events_m61_transfer_validate ON public.financial_events;
DROP FUNCTION IF EXISTS public.xbos_validate_operational_transfer_event();
