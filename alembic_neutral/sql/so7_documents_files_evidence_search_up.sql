CREATE TABLE public.so7_document_commands (
 id bigserial PRIMARY KEY, tenant_id bigint NOT NULL REFERENCES public.tenants(id), command_key varchar(180) NOT NULL,
 request_fingerprint char(64) NOT NULL, command_type varchar(80) NOT NULL, result_type varchar(80), result_public_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 UNIQUE(tenant_id,command_key), CHECK(request_fingerprint~'^[0-9a-f]{64}$')
);

CREATE TABLE public.so7_documents (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 title varchar(240) NOT NULL, classification_code varchar(160) NOT NULL,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'active', current_version_number integer NOT NULL DEFAULT 0,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb, row_version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so7_document_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so7_document_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id) REFERENCES public.tenants(id),
 CHECK(length(btrim(title))>0),
 CHECK(classification_code=lower(btrim(classification_code)) AND length(classification_code)>0),
 CHECK(lifecycle_status IN('active','archived','withdrawn')),
 CHECK(current_version_number>=0), CHECK(jsonb_typeof(metadata)='object'), CHECK(row_version>=1)
);

CREATE TABLE public.so7_document_versions (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, document_id bigint NOT NULL,
 version_number integer NOT NULL, file_name varchar(260) NOT NULL, content_type varchar(160) NOT NULL,
 content_length bigint NOT NULL, content_sha256 char(64) NOT NULL,
 storage_provider varchar(80) NOT NULL, storage_key varchar(500) NOT NULL, created_by_reference varchar(180),
 created_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so7_version_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so7_version_number UNIQUE(tenant_id,document_id,version_number),
 CONSTRAINT uq_so7_version_tenant_document_id UNIQUE(tenant_id,document_id,id),
 FOREIGN KEY(tenant_id,document_id) REFERENCES public.so7_documents(tenant_id,id),
 CHECK(version_number>=1), CHECK(length(btrim(file_name))>0), CHECK(length(btrim(content_type))>0),
 CHECK(content_length>=0), CHECK(content_sha256~'^[0-9a-f]{64}$'),
 CHECK(storage_provider=lower(btrim(storage_provider)) AND length(storage_provider)>0),
 CHECK(length(btrim(storage_key))>0)
);

CREATE TABLE public.so7_evidence_links (
 id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
 document_id bigint NOT NULL, version_id bigint NOT NULL,
 subject_authority varchar(120) NOT NULL, subject_reference varchar(240) NOT NULL, relation_code varchar(120) NOT NULL,
 lifecycle_status varchar(16) NOT NULL DEFAULT 'active', ended_at timestamptz, end_reason_code varchar(120),
 row_version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CONSTRAINT uq_so7_evidence_public UNIQUE(tenant_id,public_id),
 CONSTRAINT uq_so7_evidence_tenant_id UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,document_id) REFERENCES public.so7_documents(tenant_id,id),
 FOREIGN KEY(tenant_id,document_id,version_id) REFERENCES public.so7_document_versions(tenant_id,document_id,id),
 CHECK(subject_authority=lower(btrim(subject_authority)) AND length(subject_authority)>0),
 CHECK(length(btrim(subject_reference))>0),
 CHECK(relation_code=lower(btrim(relation_code)) AND length(relation_code)>0),
 CHECK(lifecycle_status IN('active','ended')), CHECK(row_version>=1),
 CHECK((lifecycle_status='active' AND ended_at IS NULL AND end_reason_code IS NULL) OR
       (lifecycle_status='ended' AND ended_at IS NOT NULL AND end_reason_code IS NOT NULL AND length(btrim(end_reason_code))>0))
);
CREATE UNIQUE INDEX uq_so7_active_evidence_link ON public.so7_evidence_links(
 tenant_id,document_id,version_id,subject_authority,subject_reference,relation_code
) WHERE lifecycle_status='active';

CREATE INDEX ix_so7_documents_classification ON public.so7_documents(tenant_id,classification_code,lifecycle_status);
CREATE INDEX ix_so7_versions_document ON public.so7_document_versions(tenant_id,document_id,version_number DESC);
CREATE INDEX ix_so7_versions_hash ON public.so7_document_versions(tenant_id,content_sha256);
CREATE INDEX ix_so7_evidence_subject ON public.so7_evidence_links(tenant_id,subject_authority,subject_reference,lifecycle_status);

CREATE VIEW public.so7_document_search_projection AS
SELECT d.tenant_id,d.public_id AS document_public_id,d.title,d.classification_code,d.lifecycle_status,
 d.current_version_number,v.public_id AS current_version_public_id,v.file_name AS current_file_name,
 v.content_type AS current_content_type,v.content_sha256 AS current_content_sha256
FROM public.so7_documents d
LEFT JOIN public.so7_document_versions v
 ON (v.tenant_id,v.document_id,v.version_number)=(d.tenant_id,d.id,d.current_version_number);

CREATE OR REPLACE FUNCTION public.so7_version_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'SO7 document versions are append-only'; END $$;
CREATE TRIGGER trg_so7_document_version_immutable BEFORE UPDATE OR DELETE ON public.so7_document_versions
 FOR EACH ROW EXECUTE FUNCTION public.so7_version_immutable();
