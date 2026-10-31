-- R10 SOURCE-ONLY candidate rollback. NEVER execute on hosted without
-- exact migration lineage, independent backup and empty-ticket qualification.
-- Only the exact SWES synthetic-test OIDC challenge table is eligible.
DO $swes$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.swes_pa_oidc_challenges
    ) THEN
        RAISE EXCEPTION 'HOLD_OIDC_CHALLENGES_PENDING';
    END IF;
END
$swes$;
DROP TABLE public.swes_pa_oidc_challenges;
