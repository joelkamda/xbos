CREATE TABLE public.so5_resource_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);
CREATE TABLE public.so5_resources (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 resource_kind varchar(16) NOT NULL, classification_code varchar(120) NOT NULL, display_label varchar(240) NOT NULL,
 party_id bigint, identity_id bigint, organization_unit_id bigint, location_id bigint,
 lifecycle_status varchar(20) NOT NULL DEFAULT 'active', capacity integer NOT NULL DEFAULT 1,
 exclusive_assignment boolean NOT NULL DEFAULT false, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so5_resource_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so5_resource_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,party_id) REFERENCES public.parties(tenant_id,id), FOREIGN KEY(identity_id) REFERENCES public.identities(id),
 FOREIGN KEY(tenant_id,organization_unit_id) REFERENCES public.organization_units(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES public.locations(tenant_id,id),
 CHECK(resource_kind IN('person','non_person')), CHECK((resource_kind='person' AND party_id IS NOT NULL) OR (resource_kind='non_person' AND party_id IS NULL AND identity_id IS NULL)),
 CHECK(classification_code=lower(btrim(classification_code)) AND length(classification_code)>0), CHECK(length(btrim(display_label))>0),
 CHECK(lifecycle_status IN('active','inactive','unavailable','retired')), CHECK(capacity>=1), CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);
CREATE OR REPLACE FUNCTION public.so5_validate_identity_membership() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.identity_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.identity_memberships m WHERE m.identity_id=NEW.identity_id AND m.tenant_id=NEW.tenant_id AND m.status='active') THEN
  RAISE EXCEPTION 'SO5 identity has no active membership in tenant' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_so5_resource_identity_tenant BEFORE INSERT OR UPDATE OF tenant_id,identity_id ON public.so5_resources FOR EACH ROW EXECUTE FUNCTION public.so5_validate_identity_membership();
CREATE TABLE public.so5_operational_assignments (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, resource_id bigint NOT NULL,
 capability_code varchar(120) NOT NULL, organization_unit_id bigint, location_id bigint, lifecycle_status varchar(16) NOT NULL DEFAULT 'active',
 effective_from timestamptz NOT NULL, effective_to timestamptz, source_reference varchar(240), row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so5_assignment_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so5_assignment_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_unit_id) REFERENCES public.organization_units(tenant_id,id), FOREIGN KEY(tenant_id,location_id) REFERENCES public.locations(tenant_id,id),
 CHECK(capability_code=lower(btrim(capability_code)) AND length(capability_code)>0), CHECK(lifecycle_status IN('active','ended','cancelled')),
 CHECK(effective_to IS NULL OR effective_to>effective_from), CHECK(row_version>=1)
);
CREATE TABLE public.so5_resource_history (
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, resource_id bigint NOT NULL, event_type varchar(40) NOT NULL,
 from_status varchar(20), to_status varchar(20), reason_code varchar(120) NOT NULL, occurred_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id)
);
CREATE TABLE public.so5_assignment_history (
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, assignment_id bigint NOT NULL, event_type varchar(40) NOT NULL,
 from_status varchar(16), to_status varchar(16), reason_code varchar(120) NOT NULL, occurred_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,assignment_id) REFERENCES public.so5_operational_assignments(tenant_id,id)
);
CREATE TABLE public.so5_resource_compatibility_mappings (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), resource_id bigint NOT NULL,
 source_authority varchar(120) NOT NULL, source_record_id varchar(180) NOT NULL, evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,source_authority,source_record_id),
 FOREIGN KEY(tenant_id,resource_id) REFERENCES public.so5_resources(tenant_id,id), CHECK(jsonb_typeof(evidence)='object')
);
CREATE INDEX ix_so5_resources_classification ON public.so5_resources(tenant_id,classification_code,lifecycle_status);
CREATE INDEX ix_so5_assignments_resource ON public.so5_operational_assignments(tenant_id,resource_id,lifecycle_status,effective_from);
CREATE OR REPLACE FUNCTION public.so5_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'SO5 history is append-only'; END $$;
CREATE TRIGGER trg_so5_resource_history_immutable BEFORE UPDATE OR DELETE ON public.so5_resource_history FOR EACH ROW EXECUTE FUNCTION public.so5_history_immutable();
CREATE TRIGGER trg_so5_assignment_history_immutable BEFORE UPDATE OR DELETE ON public.so5_assignment_history FOR EACH ROW EXECUTE FUNCTION public.so5_history_immutable();
