-- Additive Phase B detached WND V3 Finance candidate, TEST scope only.
-- N must independently approve isolated database/schema before any durable DDL.
-- DO NOT execute against live WND, other tenants, hosted or production DB.
-- Test harness replaces CREATE TABLE with CREATE TEMP TABLE; entire test rolls back.
CREATE TABLE v3r_b_finance_drafts (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=910001),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 idempotency_key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('INCOME_TEST','EXPENSE_TEST','MOVEMENT_TEST')),
 channel TEXT NOT NULL CHECK(channel IN ('CASH','MTN','ORANGE','BANK')),
 signed_amount_xaf BIGINT NOT NULL CHECK(signed_amount_xaf <> 0),
 transfer_ref TEXT,
 status TEXT NOT NULL DEFAULT 'DRAFT_TEST' CHECK(status='DRAFT_TEST'),
 effective_at TIMESTAMPTZ NOT NULL,
 note TEXT NOT NULL,
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 CHECK ((kind='MOVEMENT_TEST') = (transfer_ref IS NOT NULL)),
 CHECK ((kind <> 'INCOME_TEST') OR signed_amount_xaf>0),
 CHECK ((kind <> 'EXPENSE_TEST') OR signed_amount_xaf<0)
);
CREATE INDEX v3r_b_drafts_tenant_time ON v3r_b_finance_drafts(tenant_id,branch_id,effective_at,id);
CREATE TABLE v3r_b_reconciliation_drafts (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=910001),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 business_date DATE NOT NULL,
 shift TEXT NOT NULL CHECK(shift IN ('DAY','NIGHT')),
 cashier_count_xaf BIGINT NOT NULL CHECK(cashier_count_xaf>=0),
 system_cash_xaf BIGINT NOT NULL,
 variance_xaf BIGINT NOT NULL,
 recorded_by TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'DRAFT_TEST' CHECK(status='DRAFT_TEST'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(tenant_id,branch_id,business_date,shift)
);
CREATE TABLE v3r_b_debtor_alias_drafts (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=910001),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 source_debtor_ref TEXT NOT NULL,
 alias TEXT NOT NULL,
 source_sha256 TEXT NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 status TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED_TEST' CHECK(status='REVIEW_REQUIRED_TEST'),
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(tenant_id,branch_id,source_debtor_ref,alias)
);
