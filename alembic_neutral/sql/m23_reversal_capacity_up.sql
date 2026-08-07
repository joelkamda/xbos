CREATE OR REPLACE FUNCTION public.xbos_enforce_financial_reversal_capacity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    original public.financial_events%%ROWTYPE;
    original_posting_eligible BOOLEAN;
    original_requires_original BOOLEAN;
    reversed_before NUMERIC(24,8);
BEGIN
    IF NEW.original_event_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.event_type_code NOT IN (
        'COMMERCIAL_RETURN_RECOGNIZED',
        'PAYMENT_SETTLEMENT_REVERSED',
        'PAYMENT_ALLOCATION_REVERSED',
        'FINANCIAL_FACT_REVERSED'
    ) THEN
        RAISE EXCEPTION 'only approved correction types may reference an original event'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO original
    FROM public.financial_events
    WHERE tenant_id = NEW.tenant_id AND id = NEW.original_event_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'original financial event is missing or cross-tenant'
            USING ERRCODE = '23514';
    END IF;

    SELECT posting_eligible,
           COALESCE(
               (account_role_policy ->> 'requires_original_event')::boolean,
               FALSE
           )
    INTO original_posting_eligible, original_requires_original
    FROM public.financial_event_type_versions
    WHERE event_type_code = original.event_type_code
      AND event_version = original.event_version;

    IF original.original_event_id IS NOT NULL OR original_requires_original THEN
        RAISE EXCEPTION 'a correction cannot become the original of another correction'
            USING ERRCODE = '23514';
    END IF;
    IF original.organization_unit_id <> NEW.organization_unit_id THEN
        RAISE EXCEPTION 'correction organization unit differs from original'
            USING ERRCODE = '23514';
    END IF;
    IF original.currency_code <> NEW.currency_code THEN
        RAISE EXCEPTION 'correction currency differs from original'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.occurred_at < original.occurred_at THEN
        RAISE EXCEPTION 'correction occurred_at precedes original event'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.event_type_code = 'COMMERCIAL_RETURN_RECOGNIZED'
       AND original.event_type_code <> 'COMMERCIAL_REVENUE_RECOGNIZED' THEN
        RAISE EXCEPTION 'commercial return requires commercial revenue original'
            USING ERRCODE = '23514';
    ELSIF NEW.event_type_code = 'PAYMENT_SETTLEMENT_REVERSED'
       AND original.event_type_code <> 'PAYMENT_SETTLED' THEN
        RAISE EXCEPTION 'settlement reversal requires payment settled original'
            USING ERRCODE = '23514';
    ELSIF NEW.event_type_code = 'PAYMENT_ALLOCATION_REVERSED'
       AND original.event_type_code <> 'PAYMENT_ALLOCATED' THEN
        RAISE EXCEPTION 'allocation reversal requires payment allocated original'
            USING ERRCODE = '23514';
    ELSIF NEW.event_type_code = 'FINANCIAL_FACT_REVERSED' THEN
        IF original.event_type_code IN (
            'COMMERCIAL_REVENUE_RECOGNIZED',
            'PAYMENT_SETTLED',
            'PAYMENT_ALLOCATED'
        ) THEN
            RAISE EXCEPTION 'original event requires its dedicated correction type'
                USING ERRCODE = '23514';
        END IF;
        IF NOT original_posting_eligible THEN
            RAISE EXCEPTION 'generic reversal requires posting-eligible original'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.event_type_code IN (
        'PAYMENT_SETTLEMENT_REVERSED', 'FINANCIAL_FACT_REVERSED'
    ) AND (
        NEW.source_operational_account_id IS DISTINCT FROM
            original.target_operational_account_id
        OR NEW.target_operational_account_id IS DISTINCT FROM
            original.source_operational_account_id
    ) THEN
        RAISE EXCEPTION 'correction accounts do not exactly invert original event'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.event_type_code IN (
        'COMMERCIAL_RETURN_RECOGNIZED', 'PAYMENT_ALLOCATION_REVERSED'
    ) AND (
        NEW.source_operational_account_id IS NOT NULL
        OR NEW.target_operational_account_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'correction type does not permit operational accounts'
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(sum(amount), 0)
    INTO reversed_before
    FROM public.financial_events
    WHERE tenant_id = NEW.tenant_id
      AND original_event_id = NEW.original_event_id;

    IF reversed_before + NEW.amount > original.amount THEN
        RAISE EXCEPTION 'cumulative correction exceeds original event amount'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;

CREATE TRIGGER tr_financial_events_reversal_capacity
BEFORE INSERT ON public.financial_events
FOR EACH ROW EXECUTE FUNCTION public.xbos_enforce_financial_reversal_capacity();
