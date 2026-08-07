DROP TRIGGER IF EXISTS tr_financial_events_reversal_capacity
    ON public.financial_events;

DROP FUNCTION IF EXISTS public.xbos_enforce_financial_reversal_capacity();
