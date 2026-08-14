CREATE TABLE public.so4_procurement_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, UNIQUE(tenant_id,command_key)
);
CREATE TABLE public.so4_purchase_requests (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 request_code varchar(80) NOT NULL, lifecycle_status varchar(24) NOT NULL DEFAULT 'draft', expected_by timestamptz,
 approval_public_id uuid, source_reference varchar(240), document_reference varchar(240), row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so4_request_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so4_request_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,request_code), FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(lifecycle_status IN('draft','submitted','approved','ordered','cancelled','closed')), CHECK(row_version>=1)
);
CREATE TABLE public.so4_purchase_request_lines (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, purchase_request_id bigint NOT NULL,
 line_number integer NOT NULL CHECK(line_number>0), line_type varchar(16) NOT NULL CHECK(line_type IN('stock','service')),
 description varchar(500) NOT NULL, atomic_unit_id bigint, stock_location_id bigint, requested_quantity integer NOT NULL CHECK(requested_quantity>0),
 UNIQUE(tenant_id,public_id), UNIQUE(tenant_id,purchase_request_id,line_number),
 FOREIGN KEY(tenant_id,purchase_request_id) REFERENCES public.so4_purchase_requests(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id),
 CHECK((line_type='stock' AND atomic_unit_id IS NOT NULL AND stock_location_id IS NOT NULL) OR (line_type='service' AND length(btrim(description))>0))
);
CREATE TABLE public.so4_purchase_orders (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, order_code varchar(80) NOT NULL,
 supplier_party_id bigint NOT NULL, supplier_relationship_id bigint NOT NULL, purchase_request_id bigint,
 lifecycle_status varchar(24) NOT NULL DEFAULT 'draft', over_receipt_policy varchar(32) NOT NULL DEFAULT 'forbid',
 expected_by timestamptz, approval_public_id uuid, source_reference varchar(240), document_reference varchar(240),
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so4_order_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so4_order_tenant_id UNIQUE(tenant_id,id), UNIQUE(tenant_id,order_code),
 FOREIGN KEY(tenant_id,supplier_party_id) REFERENCES public.parties(tenant_id,id),
 FOREIGN KEY(tenant_id,supplier_relationship_id) REFERENCES public.so2_operational_relationships(tenant_id,id),
 FOREIGN KEY(tenant_id,purchase_request_id) REFERENCES public.so4_purchase_requests(tenant_id,id),
 CHECK(lifecycle_status IN('draft','submitted','approved','ordered','partially_received','received','cancelled','closed')),
 CHECK(over_receipt_policy IN('forbid','allow_with_authorization')), CHECK(row_version>=1)
);
CREATE TABLE public.so4_purchase_order_lines (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, purchase_order_id bigint NOT NULL,
 line_number integer NOT NULL CHECK(line_number>0), line_type varchar(16) NOT NULL CHECK(line_type IN('stock','service')),
 description varchar(500) NOT NULL, atomic_unit_id bigint, stock_location_id bigint,
 ordered_quantity integer NOT NULL CHECK(ordered_quantity>0), received_quantity integer NOT NULL DEFAULT 0 CHECK(received_quantity>=0),
 UNIQUE(tenant_id,public_id), CONSTRAINT uq_so4_order_line_tenant_id UNIQUE(tenant_id,id), UNIQUE(tenant_id,purchase_order_id,line_number),
 FOREIGN KEY(tenant_id,purchase_order_id) REFERENCES public.so4_purchase_orders(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id),
 CHECK((line_type='stock' AND atomic_unit_id IS NOT NULL AND stock_location_id IS NOT NULL) OR (line_type='service' AND length(btrim(description))>0))
);
CREATE TABLE public.so4_operational_receipts (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, purchase_order_id bigint NOT NULL,
 receipt_code varchar(80) NOT NULL, occurred_at timestamptz NOT NULL, source_reference varchar(240), document_reference varchar(240), created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,public_id), CONSTRAINT uq_so4_receipt_tenant_id UNIQUE(tenant_id,id), UNIQUE(tenant_id,receipt_code),
 FOREIGN KEY(tenant_id,purchase_order_id) REFERENCES public.so4_purchase_orders(tenant_id,id)
);
CREATE TABLE public.so4_operational_receipt_lines (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, receipt_id bigint NOT NULL, purchase_order_line_id bigint NOT NULL,
 quantity integer NOT NULL CHECK(quantity>0), stock_movement_public_id uuid,
 UNIQUE(tenant_id,receipt_id,purchase_order_line_id),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES public.so4_operational_receipts(tenant_id,id),
 FOREIGN KEY(tenant_id,purchase_order_line_id) REFERENCES public.so4_purchase_order_lines(tenant_id,id),
 FOREIGN KEY(tenant_id,stock_movement_public_id) REFERENCES public.inventory_movements(tenant_id,public_id)
);
CREATE TABLE public.so4_procurement_history (
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), resource_type varchar(16) NOT NULL,
 resource_id bigint NOT NULL, from_status varchar(24), to_status varchar(24) NOT NULL, reason_code varchar(80) NOT NULL,
 occurred_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), CHECK(resource_type IN('request','order','receipt'))
);
CREATE INDEX ix_so4_order_supplier ON public.so4_purchase_orders(tenant_id,supplier_party_id,lifecycle_status);
CREATE INDEX ix_so4_order_status ON public.so4_purchase_orders(tenant_id,lifecycle_status,expected_by);
CREATE INDEX ix_so4_history_resource ON public.so4_procurement_history(tenant_id,resource_type,resource_id,sequence);
CREATE OR REPLACE FUNCTION public.so4_procurement_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SO4 procurement history is append-only'; END $$;
CREATE TRIGGER trg_so4_procurement_history_immutable BEFORE UPDATE OR DELETE ON public.so4_procurement_history FOR EACH ROW EXECUTE FUNCTION public.so4_procurement_history_immutable();
