DROP TRIGGER IF EXISTS trg_payment_settlement_reversal_apply ON public.payment_settlement_reversals;
DROP TRIGGER IF EXISTS trg_payment_settlement_reversal_validate ON public.payment_settlement_reversals;
DROP TRIGGER IF EXISTS trg_payment_settlement_reject_delete ON public.payment_settlements;
DROP TRIGGER IF EXISTS trg_payment_settlement_guard_update ON public.payment_settlements;
DROP TRIGGER IF EXISTS trg_payment_settlement_transition_immutable ON public.payment_settlement_transitions;
DROP TRIGGER IF EXISTS trg_payment_settlement_transition_validate ON public.payment_settlement_transitions;
DROP TRIGGER IF EXISTS trg_payment_settlement_initial_transition ON public.payment_settlements;
DROP TRIGGER IF EXISTS trg_payment_settlement_validate_insert ON public.payment_settlements;
DROP FUNCTION IF EXISTS public.xbos_apply_payment_settlement_reversal();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_settlement_reversal();
DROP FUNCTION IF EXISTS public.xbos_guard_payment_settlement_update();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_settlement_transition();
DROP FUNCTION IF EXISTS public.xbos_capture_initial_payment_settlement_transition();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_settlement_insert();
DROP TABLE IF EXISTS public.payment_settlement_transitions;
DROP INDEX IF EXISTS public.uq_payment_settlements_provider_identity;
ALTER TABLE public.payment_settlements
    DROP CONSTRAINT IF EXISTS ck_payment_settlements_external_evidence,
    DROP CONSTRAINT IF EXISTS uq_payment_settlements_transition_target,
    DROP CONSTRAINT IF EXISTS ck_payment_settlements_reversed_amount,
    DROP CONSTRAINT IF EXISTS ck_payment_settlements_evidence,
    DROP CONSTRAINT IF EXISTS ck_payment_settlements_failure,
    DROP CONSTRAINT IF EXISTS ck_payment_settlements_terminal,
    DROP CONSTRAINT IF EXISTS ck_payment_settlements_value_date,
    DROP COLUMN IF EXISTS reversed_amount,
    DROP COLUMN IF EXISTS evidence_payload,
    DROP COLUMN IF EXISTS failure_code,
    DROP COLUMN IF EXISTS terminal_at,
    DROP COLUMN IF EXISTS value_date;

ALTER TABLE public.payment_settlements
    ADD CONSTRAINT ck_payment_settlements_external_evidence CHECK (
        finality_status <> 'final'
        OR payment_rail_code IN ('cash','internal_credit')
        OR provider_callback_event_id IS NOT NULL
    );
