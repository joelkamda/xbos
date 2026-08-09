DROP TRIGGER IF EXISTS trg_payment_tender_reject_delete ON public.canonical_payment_tenders;
DROP TRIGGER IF EXISTS trg_payment_tender_guard_update ON public.canonical_payment_tenders;
DROP TRIGGER IF EXISTS trg_payment_tender_transition_immutable ON public.payment_tender_transitions;
DROP TRIGGER IF EXISTS trg_payment_tender_transition_validate ON public.payment_tender_transitions;
DROP TRIGGER IF EXISTS trg_payment_tender_initial_transition ON public.canonical_payment_tenders;
DROP TRIGGER IF EXISTS trg_payment_tender_validate_insert ON public.canonical_payment_tenders;
DROP TRIGGER IF EXISTS trg_payment_pattern_settlement_guard ON public.payment_settlements;
DROP TRIGGER IF EXISTS trg_payment_pattern_settlement_validate ON public.payment_settlements;
DROP FUNCTION IF EXISTS public.xbos_guard_payment_tender_update();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_tender_transition();
DROP FUNCTION IF EXISTS public.xbos_capture_initial_payment_tender_transition();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_tender_insert();
DROP FUNCTION IF EXISTS public.xbos_guard_payment_pattern_settlement_update();
DROP FUNCTION IF EXISTS public.xbos_validate_payment_pattern_settlement();
DROP TABLE IF EXISTS public.payment_tender_transitions;
DROP INDEX IF EXISTS public.uq_canonical_payment_attempts_tender_success;
ALTER TABLE public.canonical_payment_tenders DROP CONSTRAINT IF EXISTS uq_canonical_payment_tenders_transition_target,DROP CONSTRAINT IF EXISTS ck_canonical_payment_tenders_terminal,DROP CONSTRAINT IF EXISTS ck_canonical_payment_tenders_failure,DROP CONSTRAINT IF EXISTS ck_canonical_payment_tenders_evidence,DROP COLUMN IF EXISTS terminal_at,DROP COLUMN IF EXISTS failure_code,DROP COLUMN IF EXISTS evidence_payload;
ALTER TABLE public.payment_settlements DROP CONSTRAINT IF EXISTS fk_payment_settlements_tender,DROP COLUMN IF EXISTS payment_tender_id;
CREATE OR REPLACE FUNCTION public.xbos_validate_payment_attempt_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE prior public.canonical_payment_attempts;
BEGIN
    IF NEW.retry_of_attempt_id IS NULL THEN RETURN NEW; END IF;
    SELECT * INTO prior FROM public.canonical_payment_attempts WHERE tenant_id=NEW.tenant_id AND id=NEW.retry_of_attempt_id FOR UPDATE;
    IF NOT FOUND OR prior.id=NEW.id OR prior.payment_intent_id<>NEW.payment_intent_id OR prior.organization_unit_id<>NEW.organization_unit_id OR prior.currency_code<>NEW.currency_code OR prior.attempt_state NOT IN('failed','cancelled','expired') THEN RAISE EXCEPTION USING MESSAGE='retry must follow a terminal unsuccessful attempt for the same intent'; END IF;
    RETURN NEW;
END; $$;
