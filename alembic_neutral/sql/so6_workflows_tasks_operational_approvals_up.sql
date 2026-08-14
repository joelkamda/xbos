CREATE TABLE public.so6_workflow_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.so6_workflows (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 workflow_type_code varchar(120) NOT NULL, title varchar(240) NOT NULL,
 subject_authority varchar(120) NOT NULL, subject_reference varchar(240) NOT NULL,
 organization_unit_id bigint, location_id bigint,
 lifecycle_status varchar(20) NOT NULL DEFAULT 'open', priority varchar(16) NOT NULL DEFAULT 'normal', due_at timestamptz,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so6_workflow_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so6_workflow_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,organization_unit_id) REFERENCES public.organization_units(tenant_id,id),
 FOREIGN KEY(tenant_id,location_id) REFERENCES public.locations(tenant_id,id),
 CHECK(workflow_type_code=lower(btrim(workflow_type_code)) AND length(workflow_type_code)>0),
 CHECK(subject_authority=lower(btrim(subject_authority)) AND length(subject_authority)>0),
 CHECK(length(btrim(title))>0), CHECK(length(btrim(subject_reference))>0),
 CHECK(lifecycle_status IN('open','completed','cancelled')),
 CHECK(priority IN('low','normal','high','urgent')), CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.so6_workflow_tasks (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, workflow_id bigint NOT NULL,
 task_type_code varchar(120) NOT NULL, title varchar(240) NOT NULL, assignee_resource_id bigint, required_capability_code varchar(120),
 lifecycle_status varchar(20) NOT NULL DEFAULT 'pending', priority varchar(16) NOT NULL DEFAULT 'normal', due_at timestamptz,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so6_task_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so6_task_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so6_task_workflow_id UNIQUE(tenant_id,workflow_id,id),
 FOREIGN KEY(tenant_id,workflow_id) REFERENCES public.so6_workflows(tenant_id,id),
 FOREIGN KEY(tenant_id,assignee_resource_id) REFERENCES public.so5_resources(tenant_id,id),
 CHECK(task_type_code=lower(btrim(task_type_code)) AND length(task_type_code)>0),
 CHECK(required_capability_code IS NULL OR (required_capability_code=lower(btrim(required_capability_code)) AND length(required_capability_code)>0)),
 CHECK(length(btrim(title))>0), CHECK(lifecycle_status IN('pending','in_progress','completed','cancelled')),
 CHECK(priority IN('low','normal','high','urgent')), CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.so6_operational_approvals (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, workflow_id bigint NOT NULL,
 task_id bigint, approval_type_code varchar(120) NOT NULL, approver_resource_id bigint,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'pending', due_at timestamptz, evidence_reference varchar(240),
 decision_note text, decided_at timestamptz, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so6_approval_public UNIQUE(tenant_id,public_id), CONSTRAINT uq_so6_approval_tenant_id UNIQUE(tenant_id,id),
 CONSTRAINT uq_so6_approval_workflow_id UNIQUE(tenant_id,workflow_id,id),
 FOREIGN KEY(tenant_id,workflow_id) REFERENCES public.so6_workflows(tenant_id,id),
 FOREIGN KEY(tenant_id,workflow_id,task_id) REFERENCES public.so6_workflow_tasks(tenant_id,workflow_id,id),
 FOREIGN KEY(tenant_id,approver_resource_id) REFERENCES public.so5_resources(tenant_id,id),
 CHECK(approval_type_code=lower(btrim(approval_type_code)) AND length(approval_type_code)>0),
 CHECK(lifecycle_status IN('pending','approved','rejected','cancelled')), CHECK(row_version>=1),
 CHECK((lifecycle_status IN('approved','rejected') AND decided_at IS NOT NULL) OR lifecycle_status IN('pending','cancelled'))
);

CREATE TABLE public.so6_workflow_history (
 sequence bigserial PRIMARY KEY, tenant_id bigint NOT NULL, workflow_id bigint NOT NULL, task_id bigint, approval_id bigint,
 entity_type varchar(16) NOT NULL, event_type varchar(40) NOT NULL, from_status varchar(20), to_status varchar(20),
 reason_code varchar(120) NOT NULL, occurred_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,workflow_id) REFERENCES public.so6_workflows(tenant_id,id),
 FOREIGN KEY(tenant_id,workflow_id,task_id) REFERENCES public.so6_workflow_tasks(tenant_id,workflow_id,id),
 FOREIGN KEY(tenant_id,workflow_id,approval_id) REFERENCES public.so6_operational_approvals(tenant_id,workflow_id,id),
 CHECK(entity_type IN('workflow','task','approval')), CHECK(length(btrim(event_type))>0), CHECK(length(btrim(reason_code))>0)
);

CREATE INDEX ix_so6_workflows_status ON public.so6_workflows(tenant_id,lifecycle_status,priority,due_at);
CREATE INDEX ix_so6_tasks_workflow ON public.so6_workflow_tasks(tenant_id,workflow_id,lifecycle_status,priority,due_at);
CREATE INDEX ix_so6_tasks_assignee ON public.so6_workflow_tasks(tenant_id,assignee_resource_id,lifecycle_status) WHERE assignee_resource_id IS NOT NULL;
CREATE INDEX ix_so6_approvals_workflow ON public.so6_operational_approvals(tenant_id,workflow_id,lifecycle_status,due_at);

CREATE OR REPLACE FUNCTION public.so6_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'SO6 history is append-only'; END $$;
CREATE TRIGGER trg_so6_workflow_history_immutable BEFORE UPDATE OR DELETE ON public.so6_workflow_history FOR EACH ROW EXECUTE FUNCTION public.so6_history_immutable();
