CREATE TABLE public.so9_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.so9_read_models (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 code varchar(160) NOT NULL, title varchar(240) NOT NULL, source_authority varchar(160) NOT NULL, projection_code varchar(160) NOT NULL,
 parameter_schema jsonb NOT NULL DEFAULT '{}'::jsonb, lifecycle_status varchar(16) NOT NULL DEFAULT 'active', row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_read_model_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_read_model_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so9_read_model_code UNIQUE(tenant_id,code),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(code=lower(btrim(code)) AND length(code)>0), CHECK(length(btrim(title))>0),
 CHECK(source_authority=lower(btrim(source_authority)) AND length(source_authority)>0),
 CHECK(projection_code=lower(btrim(projection_code)) AND length(projection_code)>0),
 CHECK(jsonb_typeof(parameter_schema)='object'), CHECK(lifecycle_status IN('active','archived')), CHECK(row_version>=1)
);

CREATE TABLE public.so9_projection_snapshots (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, read_model_id bigint NOT NULL,
 revision_number integer NOT NULL, as_of_at timestamptz NOT NULL, source_fingerprint char(64) NOT NULL,
 payload jsonb NOT NULL, payload_sha256 char(64) NOT NULL, source_watermark varchar(240), created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_snapshot_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_snapshot_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so9_snapshot_revision UNIQUE(tenant_id,read_model_id,revision_number),
 FOREIGN KEY(tenant_id,read_model_id) REFERENCES public.so9_read_models(tenant_id,id),
 CHECK(revision_number>=1), CHECK(source_fingerprint~'^[0-9a-f]{64}$'), CHECK(payload_sha256~'^[0-9a-f]{64}$'),
 CHECK(jsonb_typeof(payload)='object'), CHECK(jsonb_typeof(payload->'rows')='array'),
 CHECK(source_watermark IS NULL OR length(btrim(source_watermark))>0)
);

CREATE TABLE public.so9_metric_definitions (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, read_model_id bigint NOT NULL,
 metric_code varchar(160) NOT NULL, label varchar(240) NOT NULL, aggregation_code varchar(16) NOT NULL,
 field_path varchar(240), metadata jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_metric_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_metric_code UNIQUE(tenant_id,metric_code),
 FOREIGN KEY(tenant_id,read_model_id) REFERENCES public.so9_read_models(tenant_id,id),
 CHECK(metric_code=lower(btrim(metric_code)) AND length(metric_code)>0), CHECK(length(btrim(label))>0),
 CHECK(aggregation_code IN('count','sum','average','min','max')),
 CHECK((aggregation_code='count') OR field_path IS NOT NULL), CHECK(field_path IS NULL OR length(btrim(field_path))>0), CHECK(jsonb_typeof(metadata)='object')
);

CREATE TABLE public.so9_report_definitions (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, read_model_id bigint NOT NULL,
 report_code varchar(160) NOT NULL, title varchar(240) NOT NULL, parameter_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
 metric_codes jsonb NOT NULL DEFAULT '[]'::jsonb, lifecycle_status varchar(16) NOT NULL DEFAULT 'active', row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_report_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_report_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so9_report_code UNIQUE(tenant_id,report_code),
 FOREIGN KEY(tenant_id,read_model_id) REFERENCES public.so9_read_models(tenant_id,id),
 CHECK(report_code=lower(btrim(report_code)) AND length(report_code)>0), CHECK(length(btrim(title))>0),
 CHECK(jsonb_typeof(parameter_schema)='object'), CHECK(jsonb_typeof(metric_codes)='array'),
 CHECK(lifecycle_status IN('active','archived')), CHECK(row_version>=1)
);

CREATE TABLE public.so9_report_runs (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, report_id bigint NOT NULL, snapshot_id bigint NOT NULL,
 parameters jsonb NOT NULL DEFAULT '{}'::jsonb, result_payload jsonb NOT NULL, result_sha256 char(64) NOT NULL,
 generated_at timestamptz NOT NULL, outcome varchar(16) NOT NULL DEFAULT 'succeeded', created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_report_run_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_report_run_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,report_id) REFERENCES public.so9_report_definitions(tenant_id,id),
 FOREIGN KEY(tenant_id,snapshot_id) REFERENCES public.so9_projection_snapshots(tenant_id,id),
 CHECK(jsonb_typeof(parameters)='object'), CHECK(jsonb_typeof(result_payload)='object'),
 CHECK(result_sha256~'^[0-9a-f]{64}$'), CHECK(outcome IN('succeeded','failed'))
);

CREATE TABLE public.so9_automation_rules (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, report_id bigint NOT NULL,
 automation_code varchar(160) NOT NULL, trigger_code varchar(160) NOT NULL, trigger_config jsonb NOT NULL DEFAULT '{}'::jsonb,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'active', delivery_enabled boolean NOT NULL DEFAULT false,
 delivery_kind varchar(160), channel_code varchar(160), destination_reference varchar(500), row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_automation_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_automation_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so9_automation_code UNIQUE(tenant_id,automation_code),
 FOREIGN KEY(tenant_id,report_id) REFERENCES public.so9_report_definitions(tenant_id,id),
 CHECK(automation_code=lower(btrim(automation_code)) AND length(automation_code)>0),
 CHECK(trigger_code=lower(btrim(trigger_code)) AND length(trigger_code)>0), CHECK(jsonb_typeof(trigger_config)='object'),
 CHECK(lifecycle_status IN('active','paused','retired')), CHECK(row_version>=1),
 CHECK((delivery_enabled AND delivery_kind IS NOT NULL AND channel_code IS NOT NULL AND destination_reference IS NOT NULL) OR
       (NOT delivery_enabled AND delivery_kind IS NULL AND channel_code IS NULL AND destination_reference IS NULL)),
 CHECK(delivery_kind IS NULL OR (delivery_kind=lower(btrim(delivery_kind)) AND length(delivery_kind)>0)),
 CHECK(channel_code IS NULL OR (channel_code=lower(btrim(channel_code)) AND length(channel_code)>0)),
 CHECK(destination_reference IS NULL OR length(btrim(destination_reference))>0)
);

CREATE TABLE public.so9_automation_runs (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 automation_id bigint NOT NULL, report_run_id bigint NOT NULL, execution_key varchar(240) NOT NULL,
 outcome varchar(16) NOT NULL, occurred_at timestamptz NOT NULL, delivery_job_public_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so9_automation_run_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so9_automation_execution UNIQUE(tenant_id,automation_id,execution_key),
 FOREIGN KEY(tenant_id,automation_id) REFERENCES public.so9_automation_rules(tenant_id,id),
 FOREIGN KEY(tenant_id,report_run_id) REFERENCES public.so9_report_runs(tenant_id,id),
 CHECK(length(btrim(execution_key))>0), CHECK(outcome IN('succeeded','failed'))
);

CREATE INDEX ix_so9_snapshot_latest ON public.so9_projection_snapshots(tenant_id,read_model_id,revision_number DESC);
CREATE INDEX ix_so9_report_run_report ON public.so9_report_runs(tenant_id,report_id,generated_at DESC);
CREATE INDEX ix_so9_automation_status ON public.so9_automation_rules(tenant_id,lifecycle_status,automation_code);
CREATE INDEX ix_so9_automation_runs_rule ON public.so9_automation_runs(tenant_id,automation_id,occurred_at DESC);

CREATE OR REPLACE FUNCTION public.so9_derived_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SO9 derived snapshot/report/automation history is append-only'; END $$;
CREATE TRIGGER trg_so9_snapshot_immutable BEFORE UPDATE OR DELETE ON public.so9_projection_snapshots FOR EACH ROW EXECUTE FUNCTION public.so9_derived_history_immutable();
CREATE TRIGGER trg_so9_report_run_immutable BEFORE UPDATE OR DELETE ON public.so9_report_runs FOR EACH ROW EXECUTE FUNCTION public.so9_derived_history_immutable();
CREATE TRIGGER trg_so9_automation_run_immutable BEFORE UPDATE OR DELETE ON public.so9_automation_runs FOR EACH ROW EXECUTE FUNCTION public.so9_derived_history_immutable();
