DROP TRIGGER IF EXISTS trg_posting_dimension_policies_history
    ON public.posting_dimension_policies;
DROP TRIGGER IF EXISTS trg_financial_dimension_values_history
    ON public.financial_dimension_values;
DROP TRIGGER IF EXISTS trg_financial_dimension_types_history
    ON public.financial_dimension_types;
DROP FUNCTION IF EXISTS public.xbos_reject_dimension_configuration_mutation();
ALTER TABLE public.journal_lines
    DROP CONSTRAINT IF EXISTS ck_journal_lines_financial_dimensions_object;
DROP TABLE IF EXISTS public.posting_dimension_policies;
DROP TABLE IF EXISTS public.financial_dimension_values;
DROP TABLE IF EXISTS public.financial_dimension_types;
