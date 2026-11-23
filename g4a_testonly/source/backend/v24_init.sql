-- XCOMP WND V3 real functional rehearsal: separate PostgreSQL 55438.
-- No production data or external payments.
CREATE TABLE v3r_operator (
 username TEXT PRIMARY KEY CHECK(username IN ('merchant','reviewer','cashier','closer')),
 salt TEXT NOT NULL, hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('MERCHANT_TEST','REVIEWER_TEST','CASHIER_TEST','CLOSER_TEST'))
);
CREATE TABLE v3r_sessions (
 id UUID PRIMARY KEY,
 issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ,
 username TEXT NOT NULL REFERENCES v3r_operator(username)
);
CREATE TABLE v3r_products (
 sku TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 category TEXT NOT NULL,
 family TEXT NOT NULL CHECK(family IN ('kitchen','bar','other')),
 unit TEXT NOT NULL DEFAULT 'unit',
 source_revision INTEGER NOT NULL DEFAULT 1,
 active BOOLEAN NOT NULL DEFAULT TRUE,
 stock_qty INTEGER CHECK(stock_qty IS NULL OR stock_qty>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE v3r_prices (
 sku TEXT NOT NULL REFERENCES v3r_products(sku),
 zone TEXT NOT NULL CHECK(zone IN ('MAIN','VIP','BAR')),
 amount_xaf INTEGER NOT NULL CHECK(amount_xaf>=0),
 price_revision INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(sku,zone)
);
CREATE TABLE v3r_orders (
 id UUID PRIMARY KEY,
 idempotency_key TEXT NOT NULL UNIQUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 tenant_id INTEGER NOT NULL DEFAULT 920002 CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL DEFAULT 1 CHECK(branch_id=1),
 zone TEXT NOT NULL CHECK(zone IN ('MAIN','VIP','BAR')),
 status TEXT NOT NULL DEFAULT 'UNPAID_TEST' CHECK(status IN ('UNPAID_TEST','CASH_SETTLED_TEST')),
 amount_xaf INTEGER NOT NULL CHECK(amount_xaf>0)
);
CREATE TABLE v3r_order_lines (
 order_id UUID NOT NULL REFERENCES v3r_orders(id),
 sku TEXT NOT NULL REFERENCES v3r_products(sku),
 quantity INTEGER NOT NULL CHECK(quantity>0 AND quantity<=20),
 unit_xaf INTEGER NOT NULL CHECK(unit_xaf>=0),
 line_xaf INTEGER NOT NULL CHECK(line_xaf>=0),
 PRIMARY KEY(order_id,sku)
);
CREATE TABLE v3r_kitchen_tickets (
 id UUID PRIMARY KEY,
 order_id UUID NOT NULL REFERENCES v3r_orders(id),
 sku TEXT NOT NULL REFERENCES v3r_products(sku),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','READY')),
 UNIQUE(order_id,sku)
);
CREATE TABLE v3r_stock_movements (
 id UUID PRIMARY KEY,
 sku TEXT NOT NULL REFERENCES v3r_products(sku),
 order_id UUID REFERENCES v3r_orders(id),
 delta INTEGER NOT NULL CHECK(delta<>0),
 quantity_after INTEGER CHECK(quantity_after>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE v3r_finance_events (
 id UUID PRIMARY KEY,
 order_id UUID NOT NULL REFERENCES v3r_orders(id),
 kind TEXT NOT NULL CHECK(kind IN ('RECEIVABLE_TEST','CASH_RECEIPT_TEST')),
 amount_xaf INTEGER NOT NULL CHECK(amount_xaf>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(order_id,kind)
);
CREATE INDEX idx_v3r_tickets_status ON v3r_kitchen_tickets(status);
CREATE INDEX idx_v3r_finance_order ON v3r_finance_events(order_id);

-- Additive Phase B detached WND V3 Finance candidate, TEST scope only.
-- N must independently approve isolated database/schema before any durable DDL.
-- DO NOT execute against live WND, other tenants, hosted or production DB.
-- Test harness replaces CREATE TABLE with CREATE TEMP TABLE; entire test rolls back.
CREATE TABLE v3r_b_finance_drafts (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 idempotency_key TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('INCOME_TEST','EXPENSE_TEST','MOVEMENT_TEST','CANCEL_TEST','FORWARD_AMENDMENT_TEST')),
 channel TEXT NOT NULL CHECK(channel IN ('CASH','MTN','ORANGE','BANK')),
 signed_amount_xaf BIGINT NOT NULL CHECK(signed_amount_xaf <> 0),
 transfer_ref TEXT,
 status TEXT NOT NULL DEFAULT 'DRAFT_TEST' CHECK(status='DRAFT_TEST'),
 effective_at TIMESTAMPTZ NOT NULL,
 note TEXT NOT NULL,
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 CHECK ((kind IN ('MOVEMENT_TEST','CANCEL_TEST')) = (transfer_ref IS NOT NULL)),
 CHECK ((kind <> 'INCOME_TEST') OR signed_amount_xaf>0),
 CHECK ((kind <> 'EXPENSE_TEST') OR signed_amount_xaf<0)
);
CREATE INDEX v3r_b_drafts_tenant_time ON v3r_b_finance_drafts(tenant_id,branch_id,effective_at,id);
CREATE TABLE v3r_b_reconciliation_drafts (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
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
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 source_debtor_ref TEXT NOT NULL,
 alias TEXT NOT NULL,
 source_sha256 TEXT NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 status TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED_TEST' CHECK(status='REVIEW_REQUIRED_TEST'),
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(tenant_id,branch_id,source_debtor_ref,alias)
);

-- V24 additive native TEST PostgreSQL extensions; fresh isolated DB only.
-- Exactly one existing operative TEST table per truth: v3r_products/prices,
-- v3r_orders/stock_movements, v3r_b_finance_drafts; v24 tables are workflow metadata.
CREATE TABLE v24_product_workflow (
 sku TEXT PRIMARY KEY, tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1), name TEXT NOT NULL,
 category TEXT, family TEXT, unit TEXT,
 main_xaf INTEGER CHECK(main_xaf>=0), vip_xaf INTEGER CHECK(vip_xaf>=0),
 bar_xaf INTEGER CHECK(bar_xaf>=0), stock_qty INTEGER,
 status TEXT NOT NULL DEFAULT 'DRAFT_TEST'
   CHECK(status IN('DRAFT_TEST','REVIEW_TEST','PUBLISHED_TEST','INACTIVE_TEST')),
 revision INTEGER NOT NULL DEFAULT 1,
 creator TEXT NOT NULL, reviewer TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE v24_product_audit (
 sku TEXT NOT NULL REFERENCES v24_product_workflow(sku),
 revision INTEGER NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
 state JSONB NOT NULL, at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(sku,revision)
);
CREATE TABLE v24_stock_counts (
 id UUID PRIMARY KEY,tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 sku TEXT NOT NULL REFERENCES v3r_products(sku),
 count_qty INTEGER CHECK(count_qty>=0),revision INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'DRAFT_TEST' CHECK(status IN('DRAFT_TEST','APPROVED_TEST')),
 author TEXT NOT NULL, reviewer TEXT,created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE v24_stock_audit (
 seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 draft_id UUID NOT NULL REFERENCES v24_stock_counts(id),
 action TEXT NOT NULL, actor TEXT NOT NULL,details JSONB NOT NULL,at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE v24_tender_intents (
 id UUID PRIMARY KEY,order_id UUID NOT NULL REFERENCES v3r_orders(id),
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 idem TEXT NOT NULL, channel TEXT NOT NULL,
 amount_xaf BIGINT NOT NULL CHECK(amount_xaf>0),
 status TEXT NOT NULL CHECK(status IN('CASH_RECEIVED_TEST','PROVIDER_PENDING_TEST')),
 created_by TEXT NOT NULL,created_at TIMESTAMPTZ DEFAULT now(),
 UNIQUE(order_id,idem)
);
CREATE INDEX v24_tenders_order_idx ON v24_tender_intents(order_id);
CREATE TABLE v24_finance_periods (
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 period TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'OPEN_TEST'
   CHECK(status IN('OPEN_TEST','PREPARED_TEST','REVIEWED_TEST','CLOSED_TEST')),
 opening_cash_xaf BIGINT NOT NULL DEFAULT 0,
 prepared_by TEXT,reviewed_by TEXT,closed_by TEXT,
 PRIMARY KEY(tenant_id,period)
);
CREATE TABLE v24_finance_audit (
 seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tenant_id INTEGER NOT NULL, period TEXT NOT NULL,
 action TEXT NOT NULL,actor TEXT NOT NULL,reference TEXT NOT NULL,
 at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX v24_finance_one_cancel
 ON v3r_b_finance_drafts(transfer_ref) WHERE kind='CANCEL_TEST';
CREATE INDEX v24_finance_snapshot
 ON v3r_b_finance_drafts(tenant_id,branch_id,effective_at,id,created_at);
CREATE INDEX v24_finance_kind_channel_snapshot
 ON v3r_b_finance_drafts(tenant_id,branch_id,kind,channel,effective_at,id,created_at);
