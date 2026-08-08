DROP TRIGGER IF EXISTS trg_allocation_reversals_immutable ON public.allocation_reversals;
DROP TRIGGER IF EXISTS trg_payment_allocations_immutable ON public.payment_allocations;
DROP TRIGGER IF EXISTS trg_payment_allocations_validate_scope ON public.payment_allocations;
DROP TRIGGER IF EXISTS trg_value_sources_immutable ON public.value_sources;
DROP TRIGGER IF EXISTS trg_financial_obligation_lines_immutable ON public.financial_obligation_lines;
DROP TRIGGER IF EXISTS trg_financial_obligations_no_delete ON public.financial_obligations;
DROP TRIGGER IF EXISTS trg_financial_obligations_protect_authority ON public.financial_obligations;

DROP FUNCTION IF EXISTS public.xbos_protect_financial_obligation_authority();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_allocation_scope();
DROP FUNCTION IF EXISTS public.xbos_reject_obligation_fact_mutation();

DROP TABLE IF EXISTS public.allocation_reversals;
DROP TABLE IF EXISTS public.payment_allocations;
DROP TABLE IF EXISTS public.value_sources;
DROP TABLE IF EXISTS public.financial_obligation_lines;
DROP TABLE IF EXISTS public.financial_obligations;
