CREATE TABLE public.so8_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.so8_delivery_jobs (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 delivery_kind varchar(80) NOT NULL, channel_code varchar(120) NOT NULL, destination_reference varchar(500) NOT NULL,
 subject_authority varchar(120), subject_reference varchar(240), document_version_public_id uuid,
 payload jsonb NOT NULL DEFAULT '{}'::jsonb, payload_sha256 char(64) NOT NULL,
 lifecycle_status varchar(24) NOT NULL DEFAULT 'pending', available_at timestamptz NOT NULL,
 max_attempts integer NOT NULL, attempt_count integer NOT NULL DEFAULT 0,
 worker_reference varchar(180), lease_until timestamptz, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so8_delivery_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so8_delivery_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(delivery_kind=lower(btrim(delivery_kind)) AND length(delivery_kind)>0),
 CHECK(channel_code=lower(btrim(channel_code)) AND length(channel_code)>0),
 CHECK(length(btrim(destination_reference))>0),
 CHECK((subject_authority IS NULL AND subject_reference IS NULL) OR (subject_authority IS NOT NULL AND subject_reference IS NOT NULL)),
 CHECK(subject_authority IS NULL OR (subject_authority=lower(btrim(subject_authority)) AND length(subject_authority)>0)),
 CHECK(subject_reference IS NULL OR length(btrim(subject_reference))>0),
 CHECK(jsonb_typeof(payload)='object'), CHECK(payload_sha256~'^[0-9a-f]{64}$'),
 CHECK(lifecycle_status IN('pending','in_progress','retry_wait','delivered','dead_letter','cancelled')),
 CHECK(max_attempts BETWEEN 1 AND 100), CHECK(attempt_count>=0 AND attempt_count<=max_attempts), CHECK(row_version>=1),
 CHECK((lifecycle_status='in_progress' AND worker_reference IS NOT NULL AND lease_until IS NOT NULL) OR
       (lifecycle_status<>'in_progress' AND worker_reference IS NULL AND lease_until IS NULL))
);

CREATE TABLE public.so8_delivery_attempts (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, job_id bigint NOT NULL,
 attempt_number integer NOT NULL, outcome varchar(24) NOT NULL, provider_code varchar(120) NOT NULL,
 provider_reference varchar(240), error_code varchar(160), attempted_at timestamptz NOT NULL, retry_at timestamptz,
 response_metadata jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so8_attempt_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so8_attempt_number UNIQUE(tenant_id,job_id,attempt_number),
 FOREIGN KEY(tenant_id,job_id) REFERENCES public.so8_delivery_jobs(tenant_id,id),
 CHECK(attempt_number>=1), CHECK(outcome IN('delivered','retryable_failure','terminal_failure')),
 CHECK(provider_code=lower(btrim(provider_code)) AND length(provider_code)>0),
 CHECK(error_code IS NULL OR (error_code=lower(btrim(error_code)) AND length(error_code)>0)),
 CHECK(jsonb_typeof(response_metadata)='object'),
 CHECK((outcome='retryable_failure' AND retry_at IS NOT NULL AND retry_at>attempted_at) OR (outcome<>'retryable_failure' AND retry_at IS NULL)),
 CHECK((outcome='delivered' AND error_code IS NULL) OR outcome<>'delivered')
);

CREATE TABLE public.so8_inbound_deliveries (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 source_code varchar(120) NOT NULL, external_event_key varchar(240) NOT NULL,
 payload_sha256 char(64) NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 subject_authority varchar(120), subject_reference varchar(240), received_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so8_inbound_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so8_inbound_external UNIQUE(tenant_id,source_code,external_event_key),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(source_code=lower(btrim(source_code)) AND length(source_code)>0), CHECK(length(btrim(external_event_key))>0),
 CHECK(payload_sha256~'^[0-9a-f]{64}$'), CHECK(jsonb_typeof(payload)='object'),
 CHECK((subject_authority IS NULL AND subject_reference IS NULL) OR (subject_authority IS NOT NULL AND subject_reference IS NOT NULL)),
 CHECK(subject_authority IS NULL OR (subject_authority=lower(btrim(subject_authority)) AND length(subject_authority)>0)),
 CHECK(subject_reference IS NULL OR length(btrim(subject_reference))>0)
);

CREATE TABLE public.so8_offline_commands (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 device_public_id uuid NOT NULL, client_sequence bigint NOT NULL, operation_code varchar(160) NOT NULL,
 target_authority varchar(120) NOT NULL, target_reference varchar(240) NOT NULL,
 payload jsonb NOT NULL DEFAULT '{}'::jsonb, payload_sha256 char(64) NOT NULL, base_version integer,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'queued', server_result_reference varchar(240), resolution_code varchar(160),
 captured_at timestamptz NOT NULL, resolved_at timestamptz, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so8_offline_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so8_offline_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so8_offline_device_sequence UNIQUE(tenant_id,device_public_id,client_sequence),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(client_sequence>=0), CHECK(operation_code=lower(btrim(operation_code)) AND length(operation_code)>0),
 CHECK(target_authority=lower(btrim(target_authority)) AND length(target_authority)>0), CHECK(length(btrim(target_reference))>0),
 CHECK(jsonb_typeof(payload)='object'), CHECK(payload_sha256~'^[0-9a-f]{64}$'), CHECK(base_version IS NULL OR base_version>=0),
 CHECK(lifecycle_status IN('queued','applied','conflict','rejected')), CHECK(row_version>=1),
 CHECK((lifecycle_status='queued' AND resolved_at IS NULL AND resolution_code IS NULL AND server_result_reference IS NULL) OR
       (lifecycle_status='applied' AND resolved_at IS NOT NULL AND resolution_code IS NOT NULL AND server_result_reference IS NOT NULL) OR
       (lifecycle_status IN('conflict','rejected') AND resolved_at IS NOT NULL AND resolution_code IS NOT NULL))
);

CREATE TABLE public.so8_offline_history (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, offline_command_id bigint NOT NULL,
 from_status varchar(16), to_status varchar(16) NOT NULL, reason_code varchar(160) NOT NULL, result_reference varchar(240),
 occurred_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so8_offline_history_public UNIQUE(tenant_id,public_id),
 FOREIGN KEY(tenant_id,offline_command_id) REFERENCES public.so8_offline_commands(tenant_id,id),
 CHECK(from_status IS NULL OR from_status IN('queued','applied','conflict','rejected')),
 CHECK(to_status IN('queued','applied','conflict','rejected')),
 CHECK(reason_code=lower(btrim(reason_code)) AND length(reason_code)>0)
);

CREATE INDEX ix_so8_delivery_due ON public.so8_delivery_jobs(tenant_id,lifecycle_status,available_at,id) WHERE lifecycle_status IN('pending','retry_wait');
CREATE INDEX ix_so8_delivery_subject ON public.so8_delivery_jobs(tenant_id,subject_authority,subject_reference);
CREATE INDEX ix_so8_attempt_job ON public.so8_delivery_attempts(tenant_id,job_id,attempt_number);
CREATE INDEX ix_so8_inbound_source ON public.so8_inbound_deliveries(tenant_id,source_code,received_at DESC);
CREATE INDEX ix_so8_offline_status ON public.so8_offline_commands(tenant_id,lifecycle_status,captured_at);
CREATE INDEX ix_so8_offline_history_command ON public.so8_offline_history(tenant_id,offline_command_id,id);

CREATE OR REPLACE FUNCTION public.so8_append_only_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SO8 delivery/inbound/offline history is append-only'; END $$;
CREATE TRIGGER trg_so8_delivery_attempt_immutable BEFORE UPDATE OR DELETE ON public.so8_delivery_attempts FOR EACH ROW EXECUTE FUNCTION public.so8_append_only_history();
CREATE TRIGGER trg_so8_inbound_immutable BEFORE UPDATE OR DELETE ON public.so8_inbound_deliveries FOR EACH ROW EXECUTE FUNCTION public.so8_append_only_history();
CREATE TRIGGER trg_so8_offline_history_immutable BEFORE UPDATE OR DELETE ON public.so8_offline_history FOR EACH ROW EXECUTE FUNCTION public.so8_append_only_history();
