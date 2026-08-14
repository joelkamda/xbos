CREATE TABLE public.so10_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.so10_services (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 service_code varchar(160) NOT NULL, title varchar(240) NOT NULL, target_type varchar(16) NOT NULL,
 offer_id bigint, atomic_unit_id integer, calendar_code varchar(120) NOT NULL, calendar_version integer NOT NULL,
 default_duration_minutes integer NOT NULL DEFAULT 60, max_capacity integer NOT NULL DEFAULT 1,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb, lifecycle_status varchar(16) NOT NULL DEFAULT 'active', row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so10_service_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so10_service_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so10_service_code UNIQUE(tenant_id,service_code), FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 FOREIGN KEY(tenant_id,offer_id) REFERENCES public.so1_offers(tenant_id,id),
 FOREIGN KEY(tenant_id,atomic_unit_id) REFERENCES public.atomic_units(tenant_id,id),
 FOREIGN KEY(tenant_id,calendar_code,calendar_version) REFERENCES public.business_calendars(tenant_id,calendar_code,calendar_version),
 CHECK(service_code=lower(btrim(service_code)) AND length(service_code)>0), CHECK(length(btrim(title))>0),
 CHECK((target_type='offer' AND offer_id IS NOT NULL AND atomic_unit_id IS NULL) OR (target_type='atomic_unit' AND atomic_unit_id IS NOT NULL AND offer_id IS NULL)),
 CHECK(default_duration_minutes BETWEEN 1 AND 10080), CHECK(max_capacity>=1), CHECK(jsonb_typeof(metadata)='object'),
 CHECK(lifecycle_status IN('active','inactive','retired')), CHECK(row_version>=1)
);

CREATE TABLE public.so10_availability_windows (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, service_id bigint NOT NULL, location_id bigint NOT NULL,
 starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL, capacity integer NOT NULL, lifecycle_status varchar(16) NOT NULL DEFAULT 'active', row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so10_window_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so10_window_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,service_id) REFERENCES public.so10_services(tenant_id,id), FOREIGN KEY(tenant_id,location_id) REFERENCES public.locations(tenant_id,id),
 CHECK(ends_at>starts_at), CHECK(capacity>=1), CHECK(lifecycle_status IN('active','inactive')), CHECK(row_version>=1)
);

CREATE TABLE public.so10_reservations (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, service_id bigint NOT NULL,
 party_id bigint NOT NULL, relationship_id bigint NOT NULL, availability_window_id bigint, location_id bigint,
 requested_start timestamptz NOT NULL, requested_end timestamptz NOT NULL, confirmed_start timestamptz, confirmed_end timestamptz,
 business_date date, capacity_units integer NOT NULL, lifecycle_status varchar(16) NOT NULL DEFAULT 'requested', source_reference varchar(240),
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so10_reservation_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so10_reservation_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,service_id) REFERENCES public.so10_services(tenant_id,id), FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id),
 FOREIGN KEY(tenant_id,relationship_id) REFERENCES public.so2_operational_relationships(tenant_id,id),
 FOREIGN KEY(tenant_id,availability_window_id) REFERENCES public.so10_availability_windows(tenant_id,id), FOREIGN KEY(tenant_id,location_id) REFERENCES public.locations(tenant_id,id),
 CHECK(requested_end>requested_start), CHECK((confirmed_start IS NULL AND confirmed_end IS NULL) OR (confirmed_start IS NOT NULL AND confirmed_end IS NOT NULL AND confirmed_end>confirmed_start)),
 CHECK(capacity_units>=1), CHECK(lifecycle_status IN('requested','confirmed','cancelled','no_show','completed')), CHECK(row_version>=1),
 CHECK((lifecycle_status='requested' AND confirmed_start IS NULL) OR lifecycle_status<>'requested')
);

CREATE TABLE public.so10_resource_allocations (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, reservation_id bigint NOT NULL, resource_id bigint NOT NULL,
 allocation_version integer NOT NULL, starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL, capacity_units integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so10_resource_allocation UNIQUE(tenant_id,reservation_id,resource_id,allocation_version),
 FOREIGN KEY(tenant_id,reservation_id) REFERENCES public.so10_reservations(tenant_id,id), FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id),
 CHECK(allocation_version>=1), CHECK(ends_at>starts_at), CHECK(capacity_units>=1)
);

CREATE TABLE public.so10_reservation_history (
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, reservation_id bigint NOT NULL, event_type varchar(48) NOT NULL,
 from_status varchar(16), to_status varchar(16) NOT NULL, reason_code varchar(160) NOT NULL, occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,reservation_id) REFERENCES public.so10_reservations(tenant_id,id), CHECK(jsonb_typeof(event_payload)='object')
);

CREATE TABLE public.so10_service_executions (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, reservation_id bigint NOT NULL,
 lifecycle_status varchar(16) NOT NULL, started_at timestamptz NOT NULL, completed_at timestamptz, result_code varchar(160), evidence_reference varchar(500),
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so10_execution_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so10_execution_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so10_execution_reservation UNIQUE(tenant_id,reservation_id), FOREIGN KEY(tenant_id,reservation_id) REFERENCES public.so10_reservations(tenant_id,id),
 CHECK(lifecycle_status IN('in_progress','completed','aborted')), CHECK((lifecycle_status='in_progress' AND completed_at IS NULL) OR (lifecycle_status<>'in_progress' AND completed_at IS NOT NULL)),
 CHECK(result_code IS NULL OR (result_code=lower(btrim(result_code)) AND length(result_code)>0)), CHECK(row_version>=1)
);

CREATE TABLE public.so10_execution_history (
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, execution_id bigint NOT NULL, event_type varchar(48) NOT NULL,
 from_status varchar(16), to_status varchar(16) NOT NULL, reason_code varchar(160) NOT NULL, occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,execution_id) REFERENCES public.so10_service_executions(tenant_id,id), CHECK(jsonb_typeof(event_payload)='object')
);

CREATE INDEX ix_so10_windows_lookup ON public.so10_availability_windows(tenant_id,service_id,location_id,lifecycle_status,starts_at,ends_at);
CREATE INDEX ix_so10_reservations_schedule ON public.so10_reservations(tenant_id,service_id,lifecycle_status,confirmed_start,confirmed_end);
CREATE INDEX ix_so10_allocations_resource ON public.so10_resource_allocations(tenant_id,resource_id,starts_at,ends_at,allocation_version);
CREATE INDEX ix_so10_history_reservation ON public.so10_reservation_history(tenant_id,reservation_id,sequence);

CREATE OR REPLACE FUNCTION public.so10_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SO10 scheduling history is append-only'; END $$;
CREATE TRIGGER trg_so10_reservation_history_immutable BEFORE UPDATE OR DELETE ON public.so10_reservation_history FOR EACH ROW EXECUTE FUNCTION public.so10_history_immutable();
CREATE TRIGGER trg_so10_execution_history_immutable BEFORE UPDATE OR DELETE ON public.so10_execution_history FOR EACH ROW EXECUTE FUNCTION public.so10_history_immutable();
CREATE TRIGGER trg_so10_resource_allocation_immutable BEFORE UPDATE OR DELETE ON public.so10_resource_allocations FOR EACH ROW EXECUTE FUNCTION public.so10_history_immutable();
