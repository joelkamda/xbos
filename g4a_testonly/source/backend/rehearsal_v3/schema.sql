-- XCOMP WND V3 real functional rehearsal: separate PostgreSQL 55438.
-- No production data or external payments.
CREATE TABLE v3r_operator (
 username TEXT PRIMARY KEY CHECK(username='operator'),
 salt TEXT NOT NULL, hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role='REHEARSAL_ADMIN')
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
