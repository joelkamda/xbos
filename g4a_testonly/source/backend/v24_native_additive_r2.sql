-- V24 TEST-only native integration extension R2; additive, scope-fenced.
-- Only apply to fresh isolated synthetic v24_native_d7_test at 55449.
-- Native order/stock/Finance source-of-truth tables remain unchanged.
CREATE TABLE v24_order_discounts (
 order_id UUID PRIMARY KEY REFERENCES v3r_orders(id),
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 amount_xaf BIGINT NOT NULL CHECK(amount_xaf>0),
 reason TEXT NOT NULL CHECK(length(reason)>=4),
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE v24_cost_policies (
 sku TEXT PRIMARY KEY REFERENCES v3r_products(sku),
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 policy TEXT NOT NULL CHECK(policy IN ('DRINK_AUTO_TEST','FOOD_MANUAL_TEST')),
 unit_cost_xaf INTEGER NOT NULL CHECK(unit_cost_xaf>=0),
 revision INTEGER NOT NULL DEFAULT 1,
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX v24_discounts_tenant_order ON v24_order_discounts(tenant_id,order_id);
