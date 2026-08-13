COMMENT ON TABLE public.atomic_unit_taxonomy IS NULL;
COMMENT ON COLUMN public.taxonomy_nodes.taxonomy_type IS NULL;
COMMENT ON COLUMN public.taxonomy_nodes.semantic_level IS NULL;
DROP TABLE IF EXISTS public.semantic_commands;
DROP TABLE IF EXISTS public.classification_assignments;
DROP TABLE IF EXISTS public.semantic_mappings;
DROP TABLE IF EXISTS public.semantic_mapping_sets;
DROP TRIGGER IF EXISTS trg_pc3_taxonomy_cycle ON public.taxonomy_nodes;
DROP FUNCTION IF EXISTS public.pc3_reject_taxonomy_cycle();
ALTER TABLE public.taxonomy_nodes DROP CONSTRAINT IF EXISTS ck_taxonomy_nodes_semantic_version, DROP CONSTRAINT IF EXISTS ck_taxonomy_nodes_effective,
 DROP CONSTRAINT IF EXISTS fk_taxonomy_nodes_parent_tenant, DROP CONSTRAINT IF EXISTS fk_taxonomy_nodes_concept,
 DROP CONSTRAINT IF EXISTS fk_taxonomy_nodes_system, DROP CONSTRAINT IF EXISTS uq_taxonomy_nodes_public_id,
 DROP COLUMN IF EXISTS semantic_row_version, DROP COLUMN IF EXISTS effective_to, DROP COLUMN IF EXISTS effective_from, DROP COLUMN IF EXISTS semantic_concept_id,
 DROP COLUMN IF EXISTS taxonomy_system_id, DROP COLUMN IF EXISTS public_id;
DROP TABLE IF EXISTS public.taxonomy_systems;
DROP TABLE IF EXISTS public.semantic_labels;
DROP TRIGGER IF EXISTS trg_pc3_semantic_version_overlap ON public.semantic_versions;
DROP FUNCTION IF EXISTS public.pc3_reject_overlapping_semantic_versions();
DROP TABLE IF EXISTS public.semantic_versions;
DROP TABLE IF EXISTS public.semantic_concepts;
DROP TABLE IF EXISTS public.semantic_namespaces;
