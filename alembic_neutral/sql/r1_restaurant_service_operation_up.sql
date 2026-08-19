CREATE TABLE public.r1_restaurant_commands(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.r1_restaurant_service_modes(
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 mode_code varchar(120) NOT NULL, display_name varchar(240) NOT NULL,
 requires_session boolean NOT NULL DEFAULT false, requires_resource boolean NOT NULL DEFAULT false,
 supports_tabs boolean NOT NULL DEFAULT false, supports_reservations boolean NOT NULL DEFAULT false,
 allows_remote_origin boolean NOT NULL DEFAULT false, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 active boolean NOT NULL DEFAULT true, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r1_mode_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_r1_mode_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_r1_mode_code UNIQUE(tenant_id,mode_code), FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(mode_code=lower(btrim(mode_code)) AND length(mode_code)>0), CHECK(length(btrim(display_name))>0),
 CHECK(NOT requires_resource OR requires_session), CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.r1_restaurant_resource_profiles(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, resource_id bigint NOT NULL, role_code varchar(40) NOT NULL,
 parent_resource_id bigint, service_mode_codes text[] NOT NULL DEFAULT ARRAY[]::text[], metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,resource_id), FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id),
 FOREIGN KEY(tenant_id,parent_resource_id) REFERENCES public.so5_resources(tenant_id,id),
 CHECK(role_code IN('dining_area','table','counter_seat','bar_seat','service_station','pickup_point')),
 CHECK(parent_resource_id IS NULL OR parent_resource_id<>resource_id), CHECK(jsonb_typeof(metadata)='object')
);

CREATE TABLE public.r1_restaurant_service_sessions(
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 service_mode_id bigint NOT NULL, guest_count integer NOT NULL, lifecycle_status varchar(16) NOT NULL DEFAULT 'open',
 opened_at timestamptz NOT NULL, closed_at timestamptz, reservation_id bigint, party_id bigint, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r1_session_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_r1_session_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id), FOREIGN KEY(tenant_id,service_mode_id) REFERENCES public.r1_restaurant_service_modes(tenant_id,id),
 FOREIGN KEY(tenant_id,reservation_id) REFERENCES public.so10_reservations(tenant_id,id), FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id),
 CHECK(guest_count>=1), CHECK(lifecycle_status IN('open','closed','cancelled')),
 CHECK((lifecycle_status='open' AND closed_at IS NULL) OR (lifecycle_status<>'open' AND closed_at IS NOT NULL)), CHECK(row_version>=1)
);

CREATE TABLE public.r1_restaurant_session_resources(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, session_id bigint NOT NULL, resource_id bigint NOT NULL, assigned_at timestamptz NOT NULL,
 FOREIGN KEY(tenant_id,session_id) REFERENCES public.r1_restaurant_service_sessions(tenant_id,id),
 FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id), UNIQUE(tenant_id,session_id,resource_id)
);
CREATE TABLE public.r1_restaurant_session_staff(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, session_id bigint NOT NULL, role_code varchar(120) NOT NULL, party_id bigint NOT NULL, identity_id bigint,
 FOREIGN KEY(tenant_id,session_id) REFERENCES public.r1_restaurant_service_sessions(tenant_id,id), FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id),
 FOREIGN KEY(identity_id) REFERENCES public.identities(id), UNIQUE(tenant_id,session_id,role_code,party_id),
 CHECK(role_code=lower(btrim(role_code)) AND length(role_code)>0)
);

CREATE TABLE public.r1_restaurant_orders(
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 order_code varchar(180) NOT NULL, service_mode_id bigint NOT NULL, source_channel_code varchar(120) NOT NULL,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'open', opened_at timestamptz NOT NULL, submitted_at timestamptz, cancelled_at timestamptz,
 service_session_id bigint, party_id bigint, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r1_order_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_r1_order_tenant_id UNIQUE(tenant_id,id), UNIQUE(tenant_id,order_code),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id), FOREIGN KEY(tenant_id,service_mode_id) REFERENCES public.r1_restaurant_service_modes(tenant_id,id),
 FOREIGN KEY(tenant_id,service_session_id) REFERENCES public.r1_restaurant_service_sessions(tenant_id,id), FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id),
 CHECK(length(btrim(order_code))>0), CHECK(source_channel_code=lower(btrim(source_channel_code)) AND length(source_channel_code)>0),
 CHECK(lifecycle_status IN('open','submitted','cancelled')), CHECK(row_version>=1)
);
CREATE INDEX ix_r1_orders_session ON public.r1_restaurant_orders(tenant_id,service_session_id,lifecycle_status);
CREATE TABLE public.r1_restaurant_order_staff(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, order_id bigint NOT NULL, role_code varchar(120) NOT NULL, party_id bigint NOT NULL, identity_id bigint,
 FOREIGN KEY(tenant_id,order_id) REFERENCES public.r1_restaurant_orders(tenant_id,id), FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id),
 FOREIGN KEY(identity_id) REFERENCES public.identities(id), UNIQUE(tenant_id,order_id,role_code,party_id),
 CHECK(role_code=lower(btrim(role_code)) AND length(role_code)>0)
);

CREATE TABLE public.r1_restaurant_order_lines(
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, order_id bigint NOT NULL,
 target_type varchar(16) NOT NULL, atomic_unit_id integer, offer_id bigint, price_id bigint NOT NULL REFERENCES public.so1_prices(id),
 quantity numeric(18,6) NOT NULL, unit_price_snapshot numeric(18,6) NOT NULL, currency char(3) NOT NULL, note text, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r1_line_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_r1_line_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,order_id) REFERENCES public.r1_restaurant_orders(tenant_id,id), FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,offer_id) REFERENCES public.so1_offers(tenant_id,id),
 CHECK((target_type='atomic_unit' AND atomic_unit_id IS NOT NULL AND offer_id IS NULL) OR (target_type='offer' AND offer_id IS NOT NULL AND atomic_unit_id IS NULL)),
 CHECK(quantity>0), CHECK(unit_price_snapshot>=0), CHECK(currency=upper(currency) AND currency~'^[A-Z]{3}$'), CHECK(row_version>=1)
);
CREATE INDEX ix_r1_lines_order ON public.r1_restaurant_order_lines(tenant_id,order_id,id);

CREATE TABLE public.r1_restaurant_tabs(
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, tab_code varchar(180) NOT NULL,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'open', opened_at timestamptz NOT NULL, closed_at timestamptz,
 service_session_id bigint, party_id bigint, partition_version integer NOT NULL DEFAULT 0, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_r1_tab_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_r1_tab_tenant_id UNIQUE(tenant_id,id), UNIQUE(tenant_id,tab_code),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id), FOREIGN KEY(tenant_id,service_session_id) REFERENCES public.r1_restaurant_service_sessions(tenant_id,id),
 FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id), CHECK(lifecycle_status IN('open','closed','cancelled')),
 CHECK((lifecycle_status='open' AND closed_at IS NULL) OR (lifecycle_status<>'open' AND closed_at IS NOT NULL)), CHECK(partition_version>=0), CHECK(row_version>=1)
);
CREATE TABLE public.r1_restaurant_tab_orders(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, tab_id bigint NOT NULL, order_id bigint NOT NULL, attached_at timestamptz NOT NULL,
 FOREIGN KEY(tenant_id,tab_id) REFERENCES public.r1_restaurant_tabs(tenant_id,id), FOREIGN KEY(tenant_id,order_id) REFERENCES public.r1_restaurant_orders(tenant_id,id),
 UNIQUE(tenant_id,order_id), UNIQUE(tenant_id,tab_id,order_id)
);
CREATE TABLE public.r1_restaurant_tab_partitions(
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, tab_id bigint NOT NULL,
 partition_version integer NOT NULL, partition_code varchar(120) NOT NULL, created_at timestamptz NOT NULL,
 CONSTRAINT uq_r1_partition_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_r1_partition_tenant_id UNIQUE(tenant_id,id),
 UNIQUE(tenant_id,tab_id,partition_version,partition_code),
 FOREIGN KEY(tenant_id,tab_id) REFERENCES public.r1_restaurant_tabs(tenant_id,id), CHECK(partition_version>=1),
 CHECK(partition_code=lower(btrim(partition_code)) AND length(partition_code)>0)
);
CREATE TABLE public.r1_restaurant_tab_partition_lines(
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, partition_id bigint NOT NULL, order_line_id bigint NOT NULL, quantity numeric(18,6) NOT NULL,
 FOREIGN KEY(tenant_id,partition_id) REFERENCES public.r1_restaurant_tab_partitions(tenant_id,id),
 FOREIGN KEY(tenant_id,order_line_id) REFERENCES public.r1_restaurant_order_lines(tenant_id,id), UNIQUE(tenant_id,partition_id,order_line_id), CHECK(quantity>0)
);

CREATE TABLE public.r1_restaurant_session_history(
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, session_id bigint NOT NULL, event_type varchar(64) NOT NULL,
 from_status varchar(16), to_status varchar(16) NOT NULL, reason_code varchar(160) NOT NULL, occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,session_id) REFERENCES public.r1_restaurant_service_sessions(tenant_id,id), CHECK(jsonb_typeof(event_payload)='object')
);
CREATE TABLE public.r1_restaurant_order_history(
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, order_id bigint NOT NULL, event_type varchar(64) NOT NULL,
 from_status varchar(16), to_status varchar(16) NOT NULL, reason_code varchar(160) NOT NULL, occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,order_id) REFERENCES public.r1_restaurant_orders(tenant_id,id), CHECK(jsonb_typeof(event_payload)='object')
);
CREATE TABLE public.r1_restaurant_tab_history(
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, tab_id bigint NOT NULL, event_type varchar(64) NOT NULL,
 from_status varchar(16), to_status varchar(16) NOT NULL, reason_code varchar(160) NOT NULL, occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,tab_id) REFERENCES public.r1_restaurant_tabs(tenant_id,id), CHECK(jsonb_typeof(event_payload)='object')
);
CREATE INDEX ix_r1_session_history ON public.r1_restaurant_session_history(tenant_id,session_id,sequence);
CREATE INDEX ix_r1_order_history ON public.r1_restaurant_order_history(tenant_id,order_id,sequence);
CREATE INDEX ix_r1_tab_history ON public.r1_restaurant_tab_history(tenant_id,tab_id,sequence);

CREATE OR REPLACE FUNCTION public.r1_restaurant_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'R1 Restaurant historical/partition evidence is append-only'; END $$;
CREATE TRIGGER trg_r1_session_history_immutable BEFORE UPDATE OR DELETE ON public.r1_restaurant_session_history FOR EACH ROW EXECUTE FUNCTION public.r1_restaurant_append_only();
CREATE TRIGGER trg_r1_order_history_immutable BEFORE UPDATE OR DELETE ON public.r1_restaurant_order_history FOR EACH ROW EXECUTE FUNCTION public.r1_restaurant_append_only();
CREATE TRIGGER trg_r1_tab_history_immutable BEFORE UPDATE OR DELETE ON public.r1_restaurant_tab_history FOR EACH ROW EXECUTE FUNCTION public.r1_restaurant_append_only();
CREATE TRIGGER trg_r1_partitions_immutable BEFORE UPDATE OR DELETE ON public.r1_restaurant_tab_partitions FOR EACH ROW EXECUTE FUNCTION public.r1_restaurant_append_only();
CREATE TRIGGER trg_r1_partition_lines_immutable BEFORE UPDATE OR DELETE ON public.r1_restaurant_tab_partition_lines FOR EACH ROW EXECUTE FUNCTION public.r1_restaurant_append_only();

CREATE OR REPLACE FUNCTION public.r1_validate_staff_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.identity_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.identity_memberships m WHERE m.identity_id=NEW.identity_id AND m.tenant_id=NEW.tenant_id AND m.party_id=NEW.party_id AND m.status='active') THEN
  RAISE EXCEPTION 'R1 identity is not active for attributed Party in tenant' USING ERRCODE='23514';
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER trg_r1_session_staff_identity BEFORE INSERT OR UPDATE OF tenant_id,party_id,identity_id ON public.r1_restaurant_session_staff FOR EACH ROW EXECUTE FUNCTION public.r1_validate_staff_identity();
CREATE TRIGGER trg_r1_order_staff_identity BEFORE INSERT OR UPDATE OF tenant_id,party_id,identity_id ON public.r1_restaurant_order_staff FOR EACH ROW EXECUTE FUNCTION public.r1_validate_staff_identity();

CREATE OR REPLACE FUNCTION public.r1_validate_line_authorities() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p public.so1_prices%ROWTYPE;
BEGIN
 SELECT * INTO p FROM public.so1_prices WHERE id=NEW.price_id;
 IF NOT FOUND OR p.tenant_id<>NEW.tenant_id OR p.target_type<>NEW.target_type OR
    (NEW.target_type='atomic_unit' AND p.atomic_unit_id IS DISTINCT FROM NEW.atomic_unit_id) OR
    (NEW.target_type='offer' AND p.offer_id IS DISTINCT FROM NEW.offer_id) THEN
  RAISE EXCEPTION 'R1 order line price/target authority mismatch' USING ERRCODE='23514';
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER trg_r1_line_authority BEFORE INSERT OR UPDATE OF tenant_id,target_type,atomic_unit_id,offer_id,price_id ON public.r1_restaurant_order_lines FOR EACH ROW EXECUTE FUNCTION public.r1_validate_line_authorities();

COMMENT ON TABLE public.r1_restaurant_resource_profiles IS 'Restaurant semantics over SO5 resource identity; tables are optional and never duplicate SO5 resources.';
COMMENT ON TABLE public.r1_restaurant_orders IS 'Restaurant operational order truth only; Finance owns obligations/payments and SO3 owns stock truth.';
COMMENT ON TABLE public.r1_restaurant_order_lines IS 'SO1 commercial snapshots for historical Restaurant intent; not revenue/accounting/inventory authority.';
COMMENT ON TABLE public.r1_restaurant_tabs IS 'Operational tab/check grouping and split intent; Finance owns amount owed/allocation/settlement.';
