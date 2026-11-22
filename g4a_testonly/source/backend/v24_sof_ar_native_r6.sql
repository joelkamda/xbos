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
