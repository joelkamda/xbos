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
