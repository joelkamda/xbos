BEGIN;

CREATE TABLE IF NOT EXISTS customers (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    name VARCHAR(200) NOT NULL,
    primary_phone VARCHAR(80),
    normalized_phone VARCHAR(80),
    email VARCHAR(254),
    notes TEXT,
    created_by_user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_customers_context_name
    ON customers (tenant_id, branch_id, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS ux_customers_context_normalized_phone
    ON customers (tenant_id, branch_id, normalized_phone)
    WHERE normalized_phone IS NOT NULL AND normalized_phone <> '';

ALTER TABLE accounts_receivable
    ADD COLUMN IF NOT EXISTS customer_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_accounts_receivable_customer_id'
    ) THEN
        ALTER TABLE accounts_receivable
            ADD CONSTRAINT fk_accounts_receivable_customer_id
            FOREIGN KEY (customer_id) REFERENCES customers(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_accounts_receivable_customer_id
    ON accounts_receivable (tenant_id, branch_id, customer_id);

-- Promote only explicit historical debtor identities with an explicit phone.
-- Name-only historical A/R stays unlinked so identity is never guessed.
WITH explicit_ar AS (
    SELECT DISTINCT ON (
        ar.tenant_id,
        ar.branch_id,
        regexp_replace(coalesce(ar.customer_phone, ''), '[^0-9+]', '', 'g')
    )
        ar.tenant_id,
        ar.branch_id,
        trim(ar.customer_name) AS name,
        trim(ar.customer_phone) AS primary_phone,
        regexp_replace(coalesce(ar.customer_phone, ''), '[^0-9+]', '', 'g') AS normalized_phone,
        ar.created_by_user_id,
        coalesce(ar.updated_at, ar.created_at) AS source_time
    FROM accounts_receivable ar
    WHERE nullif(trim(coalesce(ar.customer_name, '')), '') IS NOT NULL
      AND lower(trim(ar.customer_name)) <> 'debtor not recorded'
      AND nullif(trim(coalesce(ar.customer_phone, '')), '') IS NOT NULL
    ORDER BY
        ar.tenant_id,
        ar.branch_id,
        regexp_replace(coalesce(ar.customer_phone, ''), '[^0-9+]', '', 'g'),
        coalesce(ar.updated_at, ar.created_at) DESC NULLS LAST,
        ar.id DESC
)
INSERT INTO customers (
    tenant_id,
    branch_id,
    name,
    primary_phone,
    normalized_phone,
    created_by_user_id
)
SELECT
    tenant_id,
    branch_id,
    name,
    primary_phone,
    normalized_phone,
    created_by_user_id
FROM explicit_ar
WHERE normalized_phone <> ''
ON CONFLICT (tenant_id, branch_id, normalized_phone)
WHERE normalized_phone IS NOT NULL AND normalized_phone <> ''
DO NOTHING;

UPDATE accounts_receivable ar
SET customer_id = c.id
FROM customers c
WHERE ar.customer_id IS NULL
  AND c.tenant_id = ar.tenant_id
  AND c.branch_id = ar.branch_id
  AND c.normalized_phone IS NOT NULL
  AND c.normalized_phone <> ''
  AND c.normalized_phone = regexp_replace(coalesce(ar.customer_phone, ''), '[^0-9+]', '', 'g')
  AND nullif(trim(coalesce(ar.customer_phone, '')), '') IS NOT NULL;

COMMIT;
