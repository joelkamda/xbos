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

-- SOF R6: additive synthetic TEST-only debtor/A/R trace, NOT canonical historical WND.
-- Run only on new v24_native_d7_test in captive no-egress PG17. NEVER on WND.
-- v3r_orders remains the one sale fact; an obligation is a link, not a new sale.
CREATE TABLE v24_ar_debtors (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK (tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK (branch_id=1),
 display_name TEXT NOT NULL CHECK (length(btrim(display_name)) BETWEEN 2 AND 100),
 source_ref TEXT UNIQUE,
 source_verified BOOLEAN NOT NULL DEFAULT FALSE CHECK (source_verified=FALSE),
 revision INTEGER NOT NULL DEFAULT 1 CHECK (revision>0),
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE v24_ar_obligations (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK (tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK (branch_id=1),
 order_id UUID NOT NULL UNIQUE REFERENCES v3r_orders(id),
 debtor_id UUID NOT NULL REFERENCES v24_ar_debtors(id),
 original_due_xaf BIGINT NOT NULL CHECK (original_due_xaf>0),
 cash_tender_at_link_xaf BIGINT NOT NULL CHECK(cash_tender_at_link_xaf>=0),
 provider_pending_at_link_xaf BIGINT NOT NULL CHECK(provider_pending_at_link_xaf>=0),
 due_date DATE,
 revision INTEGER NOT NULL DEFAULT 1 CHECK (revision>0),
 status TEXT NOT NULL DEFAULT 'LINKED_TEST' CHECK(status='LINKED_TEST'),
 prepared_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX v24_ar_obligation_debtor_idx
 ON v24_ar_obligations(tenant_id,branch_id,debtor_id,order_id);
CREATE TABLE v24_ar_collections (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK (tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK (branch_id=1),
 obligation_id UUID NOT NULL REFERENCES v24_ar_obligations(id),
 idem TEXT NOT NULL,
 amount_xaf BIGINT NOT NULL CHECK(amount_xaf>0),
 channel TEXT NOT NULL CHECK(channel IN('CASH','MTN','ORANGE','BANK')),
 state TEXT NOT NULL CHECK(state IN('CASH_RECEIVED_TEST','PROVIDER_PENDING_TEST')),
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE (tenant_id,branch_id,obligation_id,idem)
);
CREATE INDEX v24_ar_collections_obligation_idx
 ON v24_ar_collections(obligation_id,created_at,id);
CREATE TABLE v24_ar_audit (
 seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 debtor_id UUID NOT NULL REFERENCES v24_ar_debtors(id),
 obligation_id UUID REFERENCES v24_ar_obligations(id),
 collection_id UUID REFERENCES v24_ar_collections(id),
 action TEXT NOT NULL CHECK(action IN('CREATE_DEBTOR_TEST','LINK_ORDER_TEST','ALLOCATE_COLLECTION_TEST')),
 actor TEXT NOT NULL,
 at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- R7 PK/G4-A detached TEST only. Run AFTER inherited v24_init_r6.sql.
-- Synthetic authority fixtures only; no real issuer, PC5, Finance or live WND.
-- One source of mutable product+zone amounts: v24_product_workflow.
-- Price revisions are per-zone concurrency metadata, not duplicate price records.
ALTER TABLE v24_product_workflow
  ADD COLUMN main_price_revision INTEGER NOT NULL DEFAULT 1 CHECK(main_price_revision>=1),
  ADD COLUMN vip_price_revision INTEGER NOT NULL DEFAULT 1 CHECK(vip_price_revision>=1),
  ADD COLUMN bar_price_revision INTEGER NOT NULL DEFAULT 1 CHECK(bar_price_revision>=1);

CREATE FUNCTION v24_pk_zone_version_trigger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.main_xaf IS DISTINCT FROM OLD.main_xaf THEN
    NEW.main_price_revision := OLD.main_price_revision + 1;
  ELSE
    NEW.main_price_revision := OLD.main_price_revision;
  END IF;
  IF NEW.vip_xaf IS DISTINCT FROM OLD.vip_xaf THEN
    NEW.vip_price_revision := OLD.vip_price_revision + 1;
  ELSE
    NEW.vip_price_revision := OLD.vip_price_revision;
  END IF;
  IF NEW.bar_xaf IS DISTINCT FROM OLD.bar_xaf THEN
    NEW.bar_price_revision := OLD.bar_price_revision + 1;
  ELSE
    NEW.bar_price_revision := OLD.bar_price_revision;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER v24_pk_zone_versions_on_edit
BEFORE UPDATE OF main_xaf,vip_xaf,bar_xaf ON v24_product_workflow
FOR EACH ROW EXECUTE FUNCTION v24_pk_zone_version_trigger();

CREATE TABLE v24_pk_test_pack_readback (
 tenant_id INT NOT NULL CHECK(tenant_id=920002),
 branch_id INT NOT NULL CHECK(branch_id=1),
 pack_code TEXT NOT NULL CHECK(pack_code='industry.restaurant'),
 version TEXT NOT NULL, manifest_sha256 TEXT NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
 cert_sha256 TEXT NOT NULL CHECK(cert_sha256 ~ '^[a-f0-9]{64}$'),
 version_revision INT NOT NULL CHECK(version_revision>0),
 issuer_epoch INT NOT NULL CHECK(issuer_epoch>0),
 min_issuer_epoch INT NOT NULL CHECK(min_issuer_epoch>0),
 certified_axes JSONB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('ACTIVE_SOURCE','DISABLED_SOURCE','REVOKED_SOURCE')),
 source_grade TEXT NOT NULL DEFAULT 'SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'
   CHECK(source_grade='SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'),
 PRIMARY KEY(tenant_id,branch_id,pack_code)
);

CREATE TABLE v24_pk_test_policy_readback (
 tenant_id INT NOT NULL CHECK(tenant_id=920002),
 branch_id INT NOT NULL CHECK(branch_id=1),
 category_code TEXT NOT NULL,
 family TEXT NOT NULL CHECK(family IN ('bar','kitchen','other')),
 unit_code TEXT NOT NULL,
 uom_precision INT NOT NULL CHECK(uom_precision BETWEEN 0 AND 6),
 pc3_policy_revision INT NOT NULL CHECK(pc3_policy_revision>0),
 pc3_concept_sha256 TEXT NOT NULL CHECK(pc3_concept_sha256 ~ '^[a-f0-9]{64}$'),
 tax_policy_code TEXT NOT NULL,
 tax_policy_revision INT NOT NULL CHECK(tax_policy_revision>0),
 revenue_account_code TEXT NOT NULL,
 inventory_account_code TEXT,
 cogs_account_code TEXT,
 stock_tracked BOOLEAN NOT NULL,
 valid_from TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ,
 source_grade TEXT NOT NULL DEFAULT 'SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'
   CHECK(source_grade='SYNTHETIC_SOURCE_CONTRACT_NOT_ADMITTED'),
 PRIMARY KEY(tenant_id,branch_id,category_code,family,unit_code),
 CHECK(valid_until IS NULL OR valid_until>valid_from),
 CHECK((NOT stock_tracked AND inventory_account_code IS NULL AND cogs_account_code IS NULL)
    OR (stock_tracked AND inventory_account_code IS NOT NULL AND cogs_account_code IS NOT NULL))
);

-- Synthetic TEST fixtures; fabricated policy IDs are never claimed as WND/PC3/SOF authoritative.
INSERT INTO v24_pk_test_pack_readback
(tenant_id,branch_id,pack_code,version,manifest_sha256,cert_sha256,version_revision,
 issuer_epoch,min_issuer_epoch,certified_axes,state)
VALUES
(920002,1,'industry.restaurant','SYNTHETIC-R7','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
 1,4,4,
 '["architecture","tenant_isolation","migration_compatibility","authorization","semantics","finance","shared_operations","xa","manifest"]'::jsonb,
 'ACTIVE_SOURCE');

INSERT INTO v24_pk_test_policy_readback
(tenant_id,branch_id,category_code,family,unit_code,uom_precision,pc3_policy_revision,
 pc3_concept_sha256,tax_policy_code,tax_policy_revision,revenue_account_code,
 inventory_account_code,cogs_account_code,stock_tracked,valid_from)
VALUES
(920002,1,'MOCK DRINK','bar','BOTTLE',0,1,
 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
 'VAT_TEST_R7',1,'SALES_BAR_TEST','DRINK_STOCK_TEST','DRINK_COGS_TEST',TRUE,
 '2026-01-01T00:00:00+01:00');

-- PA additive synthetic TEST-only authorization schema.
-- No genuine PC5 issuer, account enrollment, or financial effect.
CREATE TABLE v24_pa_test_publish_policy (
  tenant_id BIGINT NOT NULL CHECK(tenant_id>0),
  branch_id BIGINT NOT NULL CHECK(branch_id>0),
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  minimum_issuer_epoch BIGINT NOT NULL CHECK(minimum_issuer_epoch>0),
  PRIMARY KEY (tenant_id,branch_id)
);
CREATE TABLE v24_pa_test_publish_grants (
  tenant_id BIGINT NOT NULL CHECK(tenant_id>0),
  branch_id BIGINT NOT NULL CHECK(branch_id>0),
  actor_ref TEXT NOT NULL REFERENCES v3r_operator(username),
  permission TEXT NOT NULL CHECK(permission='restaurant.product.publish.test'),
  issuer_epoch BIGINT NOT NULL CHECK(issuer_epoch>0),
  valid_from TIMESTAMPTZ NOT NULL,
  valid_until TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  grade TEXT NOT NULL CHECK(grade='SYNTHETIC_PG17_PERMISSION_NOT_GENUINE_PC5'),
  CHECK(valid_until>valid_from),
  PRIMARY KEY(tenant_id,branch_id,actor_ref,permission)
);

-- W V24 R6 additive PostgreSQL17 TEST-only receipt/reprint custody.
-- Not yet executed. Only apply in PCR/N approved fresh no-egress native
-- TEST tenant 920002 / branch 1. NO WND, provider or production connection.
-- Does not grant physical printer, fiscal receipt or real PC5 authority.
CREATE TABLE v24_w_receipt_custody (
 id UUID PRIMARY KEY,
 tenant_id INTEGER NOT NULL CHECK(tenant_id=920002),
 branch_id INTEGER NOT NULL CHECK(branch_id=1),
 order_id UUID NOT NULL REFERENCES v3r_orders(id),
 request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 8 AND 100),
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 8 AND 400),
 source_sha256 TEXT NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 status TEXT NOT NULL DEFAULT 'PENDING_REVIEW_TEST'
   CHECK(status IN('PENDING_REVIEW_TEST','PREVIEW_APPROVED_TEST','REJECTED_TEST')),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
 requested_by TEXT NOT NULL REFERENCES v3r_operator(username),
 reviewed_by TEXT REFERENCES v3r_operator(username),
 review_reason TEXT,
 requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 reviewed_at TIMESTAMPTZ,
 UNIQUE(tenant_id,branch_id,order_id,request_key),
 CHECK (reviewed_by IS NULL OR reviewed_by<>requested_by),
 CHECK ((status='PENDING_REVIEW_TEST') =
        (reviewed_by IS NULL AND review_reason IS NULL AND reviewed_at IS NULL))
);
CREATE INDEX v24_w_receipt_order_idx ON
    v24_w_receipt_custody(tenant_id,branch_id,order_id,requested_at);
CREATE TABLE v24_w_receipt_custody_audit (
 seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id UUID NOT NULL REFERENCES v24_w_receipt_custody(id),
 action TEXT NOT NULL CHECK(action IN(
    'REQUEST_TEST','APPROVE_PREVIEW_TEST','REJECT_TEST')),
 actor TEXT NOT NULL REFERENCES v3r_operator(username),
 details JSONB NOT NULL,
 at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX v24_w_receipt_audit_idx ON
    v24_w_receipt_custody_audit(request_id,seq);
