DROP TRIGGER IF EXISTS trg_obligation_state_transitions_immutable ON public.obligation_state_transitions;
DROP TRIGGER IF EXISTS trg_obligation_state_transition_update ON public.financial_obligations;
DROP TRIGGER IF EXISTS trg_obligation_state_transition_insert ON public.financial_obligations;
DROP FUNCTION IF EXISTS public.xbos_record_obligation_state_transition();
DROP TABLE IF EXISTS public.obligation_state_transitions;
