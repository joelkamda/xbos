DROP TRIGGER IF EXISTS trg_so7_document_version_immutable ON public.so7_document_versions;
DROP FUNCTION IF EXISTS public.so7_version_immutable();
DROP VIEW IF EXISTS public.so7_document_search_projection;
DROP TABLE IF EXISTS public.so7_evidence_links;
DROP TABLE IF EXISTS public.so7_document_versions;
DROP TABLE IF EXISTS public.so7_documents;
DROP TABLE IF EXISTS public.so7_document_commands;
