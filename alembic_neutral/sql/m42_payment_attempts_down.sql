DROP TRIGGER IF EXISTS trg_payment_attempt_reject_delete ON public.canonical_payment_attempts;
DROP TRIGGER IF EXISTS trg_payment_attempt_guard_update ON public.canonical_payment_attempts;
DROP TRIGGER IF EXISTS trg_payment_attempt_history_consistent ON public.canonical_payment_attempt_transitions;
DROP TRIGGER IF EXISTS trg_payment_attempt_transition_immutable ON public.canonical_payment_attempt_transitions;
DROP TRIGGER IF EXISTS trg_payment_attempt_transition_validate ON public.canonical_payment_attempt_transitions;
DROP TRIGGER IF EXISTS trg_payment_attempt_initial_transition ON public.canonical_payment_attempts;
DROP TRIGGER IF EXISTS trg_payment_attempt_validate_insert ON public.canonical_payment_attempts;

DROP FUNCTION IF EXISTS public.xbos_guard_payment_attempt_update();
DROP FUNCTION IF EXISTS public.xbos_confirm_payment_attempt_history();
DROP FUNCTION IF EXISTS public.xbos_capture_initial_payment_attempt_transition();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_attempt_transition();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_attempt_insert();

DROP TABLE IF EXISTS public.canonical_payment_attempt_transitions;

DROP INDEX IF EXISTS public.uq_canonical_payment_attempts_unbound_external;
DROP INDEX IF EXISTS public.ix_canonical_payment_attempts_retry;

ALTER TABLE public.canonical_payment_attempts
    DROP CONSTRAINT IF EXISTS ck_canonical_payment_attempts_failure,
    DROP CONSTRAINT IF EXISTS ck_canonical_payment_attempts_terminal,
    DROP CONSTRAINT IF EXISTS ck_canonical_payment_attempts_timeout,
    DROP CONSTRAINT IF EXISTS fk_canonical_payment_attempts_retry,
    DROP COLUMN IF EXISTS failure_code,
    DROP COLUMN IF EXISTS terminal_at,
    DROP COLUMN IF EXISTS timeout_at,
    DROP COLUMN IF EXISTS retry_of_attempt_id;
