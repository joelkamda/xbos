DROP TRIGGER IF EXISTS trg_sc41_semantic_classification_governance_protect ON public.semantic_classification_governance;
DROP TRIGGER IF EXISTS trg_sc41_semantic_classification_governance_validate ON public.semantic_classification_governance;
DROP FUNCTION IF EXISTS public.sc41_protect_semantic_classification_governance();
DROP FUNCTION IF EXISTS public.sc41_validate_semantic_classification_governance();
DROP TABLE IF EXISTS public.semantic_classification_governance;

DROP TRIGGER IF EXISTS trg_sc41_tenant_taxonomy_overlay_protect ON public.tenant_taxonomy_overlays;
DROP TRIGGER IF EXISTS trg_sc41_tenant_taxonomy_overlay_effective_cycle ON public.tenant_taxonomy_overlays;
DROP TRIGGER IF EXISTS trg_sc41_tenant_taxonomy_overlay_validate ON public.tenant_taxonomy_overlays;
DROP FUNCTION IF EXISTS public.sc41_protect_tenant_taxonomy_overlay();
DROP FUNCTION IF EXISTS public.sc41_validate_effective_cycles_after_overlay();
DROP FUNCTION IF EXISTS public.sc41_validate_tenant_taxonomy_overlay();
DROP TABLE IF EXISTS public.tenant_taxonomy_overlays;

DROP TRIGGER IF EXISTS trg_sc41_semantic_taxonomy_placement_protect ON public.semantic_taxonomy_placements;
DROP TRIGGER IF EXISTS trg_sc41_semantic_taxonomy_placement_effective_cycle ON public.semantic_taxonomy_placements;
DROP TRIGGER IF EXISTS trg_sc41_semantic_taxonomy_placement_validate ON public.semantic_taxonomy_placements;
DROP FUNCTION IF EXISTS public.sc41_protect_semantic_taxonomy_placement();
DROP FUNCTION IF EXISTS public.sc41_validate_effective_cycles_after_placement();
DROP FUNCTION IF EXISTS public.sc41_assert_effective_taxonomy_acyclic(BIGINT,INTEGER,TIMESTAMPTZ,TIMESTAMPTZ);
DROP FUNCTION IF EXISTS public.sc41_validate_semantic_taxonomy_placement();
DROP TABLE IF EXISTS public.semantic_taxonomy_placements;

DROP TRIGGER IF EXISTS trg_sc41_semantic_taxonomy_node_scope ON public.semantic_taxonomy_nodes;
DROP FUNCTION IF EXISTS public.sc41_validate_semantic_taxonomy_node_scope();
DROP TABLE IF EXISTS public.semantic_taxonomy_nodes;

DROP TABLE IF EXISTS public.semantic_classification_commands;
