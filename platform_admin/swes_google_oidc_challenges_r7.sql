-- SWES R7 ADDITIVE CANDIDATE — NOT applied or wired to hosted Alembic.
-- Target exact TEST DB wnd_xafpay_demo_austin_db after independent release checks.
-- No arbitrary tenant IDs, no tokens, no subject claims, no credentials.
CREATE TABLE public.swes_pa_oidc_challenges (
    state_digest CHAR(64) PRIMARY KEY,
    nonce_digest CHAR(64) NOT NULL,
    verifier_ciphertext BYTEA NOT NULL,
    tenant_id INTEGER NOT NULL CHECK (tenant_id = 910001),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT swes_pa_oidc_lifetime CHECK (expires_at > created_at
          AND expires_at <= created_at + INTERVAL '5 minutes')
);
REVOKE ALL ON public.swes_pa_oidc_challenges FROM PUBLIC;
-- The app runtime role requires narrowly granted SELECT,INSERT,DELETE
-- only after deployment and independent owner/role admission.
