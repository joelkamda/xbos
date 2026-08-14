CREATE TABLE public.so3_stock_locations (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 location_id bigint NOT NULL, legacy_branch_id bigint, code varchar(80) NOT NULL, name varchar(200) NOT NULL,
 active boolean NOT NULL DEFAULT true, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,public_id), CONSTRAINT uq_so3_stock_locations_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,location_id), UNIQUE(tenant_id,code),
 FOREIGN KEY(tenant_id,location_id) REFERENCES public.locations(tenant_id,id),
 FOREIGN KEY(tenant_id,legacy_branch_id) REFERENCES public.branches(tenant_id,id)
);

INSERT INTO public.so3_stock_locations(tenant_id,location_id,legacy_branch_id,code,name)
SELECT m.tenant_id,m.location_id,m.branch_id,'legacy-branch-'||m.branch_id,l.name
FROM public.legacy_branch_structural_mappings m JOIN public.locations l ON (l.tenant_id,l.id)=(m.tenant_id,m.location_id)
ON CONFLICT(tenant_id,location_id) DO NOTHING;

ALTER TABLE public.inventory_items ADD COLUMN public_id uuid DEFAULT gen_random_uuid();
ALTER TABLE public.inventory_items ADD COLUMN stock_location_id bigint;
ALTER TABLE public.inventory_items ADD COLUMN reserved_quantity integer NOT NULL DEFAULT 0;
ALTER TABLE public.inventory_items ADD COLUMN row_version integer NOT NULL DEFAULT 1;
ALTER TABLE public.inventory_items ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
UPDATE public.inventory_items i SET stock_location_id=s.id FROM public.so3_stock_locations s
 WHERE (s.tenant_id,s.legacy_branch_id)=(i.tenant_id,i.branch_id);
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.inventory_items WHERE stock_location_id IS NULL) THEN
 RAISE EXCEPTION 'SO3 legacy inventory item lacks PC1 location compatibility mapping'; END IF; END $$;
ALTER TABLE public.inventory_items ALTER COLUMN public_id SET NOT NULL;
ALTER TABLE public.inventory_items ALTER COLUMN stock_location_id SET NOT NULL;
ALTER TABLE public.inventory_items ALTER COLUMN branch_id DROP NOT NULL;
ALTER TABLE public.inventory_items ADD CONSTRAINT uq_so3_inventory_item_public UNIQUE(tenant_id,public_id);
ALTER TABLE public.inventory_items ADD CONSTRAINT uq_so3_inventory_item_tenant_id UNIQUE(tenant_id,id);
ALTER TABLE public.inventory_items ADD CONSTRAINT uq_so3_inventory_position UNIQUE(tenant_id,stock_location_id,atomic_unit_id);
ALTER TABLE public.inventory_items ADD CONSTRAINT fk_so3_inventory_location FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id);
ALTER TABLE public.inventory_items ADD CONSTRAINT fk_so3_inventory_atomic_unit FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id);
ALTER TABLE public.inventory_items ADD CONSTRAINT ck_so3_reserved_nonnegative CHECK(reserved_quantity>=0);

ALTER TABLE public.inventory_movements ADD COLUMN public_id uuid DEFAULT gen_random_uuid();
ALTER TABLE public.inventory_movements ADD COLUMN stock_location_id bigint;
ALTER TABLE public.inventory_movements ADD COLUMN source_reference varchar(240);
ALTER TABLE public.inventory_movements ADD COLUMN occurred_at timestamptz;
ALTER TABLE public.inventory_movements ADD COLUMN reason_code varchar(80);
ALTER TABLE public.inventory_movements ADD COLUMN request_fingerprint char(64);
ALTER TABLE public.inventory_movements ADD COLUMN correction_of_id bigint;
ALTER TABLE public.inventory_movements ADD COLUMN related_public_id uuid;
ALTER TABLE public.inventory_movements ADD COLUMN quantity_after integer;
ALTER TABLE public.inventory_movements ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
UPDATE public.inventory_movements m SET stock_location_id=i.stock_location_id, occurred_at=m.created_at,
 reason_code=COALESCE(NULLIF(lower(regexp_replace(m.movement_type,'[^a-zA-Z0-9]+','-','g')),''),'legacy'),
 source_reference=COALESCE(m.reference_id::text,'legacy:'||m.id)
 FROM public.inventory_items i WHERE (i.tenant_id,i.id)=(m.tenant_id,m.inventory_item_id);
ALTER TABLE public.inventory_movements ALTER COLUMN public_id SET NOT NULL;
ALTER TABLE public.inventory_movements ALTER COLUMN stock_location_id SET NOT NULL;
ALTER TABLE public.inventory_movements ALTER COLUMN occurred_at SET NOT NULL;
ALTER TABLE public.inventory_movements ALTER COLUMN reason_code SET NOT NULL;
ALTER TABLE public.inventory_movements ADD CONSTRAINT uq_so3_movement_public UNIQUE(tenant_id,public_id);
ALTER TABLE public.inventory_movements ADD CONSTRAINT uq_so3_movement_tenant_id UNIQUE(tenant_id,id);
ALTER TABLE public.inventory_movements ADD CONSTRAINT fk_so3_movement_location FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id);
ALTER TABLE public.inventory_movements ADD CONSTRAINT fk_so3_movement_item FOREIGN KEY(tenant_id,inventory_item_id) REFERENCES public.inventory_items(tenant_id,id);
ALTER TABLE public.inventory_movements ADD CONSTRAINT fk_so3_movement_atomic_unit FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id);
ALTER TABLE public.inventory_movements ADD CONSTRAINT fk_so3_movement_correction FOREIGN KEY(tenant_id,correction_of_id) REFERENCES public.inventory_movements(tenant_id,id);
CREATE UNIQUE INDEX uq_so3_one_correction ON public.inventory_movements(correction_of_id) WHERE correction_of_id IS NOT NULL;
CREATE INDEX ix_so3_movement_history ON public.inventory_movements(tenant_id,stock_location_id,atomic_unit_id,occurred_at,id);

CREATE TABLE public.so3_inventory_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, UNIQUE(tenant_id,command_key)
);
CREATE TABLE public.so3_stock_reservations (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 inventory_item_id bigint NOT NULL, atomic_unit_id bigint NOT NULL, stock_location_id bigint NOT NULL,
 quantity integer NOT NULL CHECK(quantity>0), lifecycle_status varchar(24) NOT NULL CHECK(lifecycle_status IN('active','released','consumed','expired')),
 source_type varchar(80) NOT NULL, source_reference varchar(240) NOT NULL, expires_at timestamptz,
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), released_at timestamptz, consumed_at timestamptz,
 UNIQUE(tenant_id,public_id), FOREIGN KEY(tenant_id,inventory_item_id) REFERENCES public.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id)
);
CREATE TABLE public.so3_stock_counts (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 inventory_item_id bigint NOT NULL, atomic_unit_id bigint NOT NULL, stock_location_id bigint NOT NULL,
 expected_quantity integer NOT NULL, counted_quantity integer NOT NULL CHECK(counted_quantity>=0), variance integer NOT NULL,
 lifecycle_status varchar(24) NOT NULL CHECK(lifecycle_status IN('pending','accepted','rejected')),
 reason_code varchar(80) NOT NULL, occurred_at timestamptz NOT NULL, adjustment_movement_id bigint,
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), accepted_at timestamptz,
 UNIQUE(tenant_id,public_id), FOREIGN KEY(tenant_id,inventory_item_id) REFERENCES public.inventory_items(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,adjustment_movement_id) REFERENCES public.inventory_movements(tenant_id,id)
);
CREATE TABLE public.so3_stock_transfers (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 atomic_unit_id bigint NOT NULL, source_stock_location_id bigint NOT NULL, destination_stock_location_id bigint NOT NULL,
 quantity integer NOT NULL CHECK(quantity>0), lifecycle_status varchar(24) NOT NULL,
 source_type varchar(80) NOT NULL, source_reference varchar(240), reason_code varchar(80) NOT NULL, occurred_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,public_id),
 CHECK(source_stock_location_id<>destination_stock_location_id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,source_stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id),
 FOREIGN KEY(tenant_id,destination_stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id)
);

CREATE OR REPLACE FUNCTION public.so3_inventory_movement_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SO3 inventory movements are append-only'; END $$;
CREATE TRIGGER trg_so3_inventory_movement_immutable BEFORE UPDATE OR DELETE ON public.inventory_movements
FOR EACH ROW EXECUTE FUNCTION public.so3_inventory_movement_immutable();
