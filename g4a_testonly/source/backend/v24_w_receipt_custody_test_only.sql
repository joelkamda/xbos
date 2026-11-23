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
