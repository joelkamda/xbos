ALTER TABLE public.value_sources
    DROP CONSTRAINT IF EXISTS fk_value_sources_payment_settlement;

DROP TRIGGER IF EXISTS trg_payment_settlement_reversals_immutable
    ON public.payment_settlement_reversals;
DROP TRIGGER IF EXISTS trg_provider_callback_events_immutable
    ON public.provider_callback_events;

DROP TABLE IF EXISTS public.payment_settlement_reversals;
DROP TABLE IF EXISTS public.payment_settlements;
DROP TABLE IF EXISTS public.provider_callback_events;
DROP TABLE IF EXISTS public.canonical_payment_attempts;
DROP TABLE IF EXISTS public.canonical_payment_tenders;
DROP TABLE IF EXISTS public.canonical_payment_intents;
DROP TABLE IF EXISTS public.canonical_payment_requests;

DROP FUNCTION IF EXISTS public.xbos_reject_immutable_payment_evidence();

ALTER TABLE public.operational_financial_accounts
    DROP CONSTRAINT IF EXISTS uq_operational_financial_accounts_settlement_target;
