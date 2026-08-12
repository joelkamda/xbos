DROP TRIGGER IF EXISTS trg_pc1_reject_organization_cycle ON public.organization_units;
DROP FUNCTION IF EXISTS public.pc1_reject_organization_cycle();
DROP TABLE IF EXISTS public.tenant_provisioning_commands;
DROP TABLE IF EXISTS public.legacy_branch_structural_mappings;
ALTER TABLE public.branches DROP CONSTRAINT IF EXISTS uq_branches_tenant_id_id;
DROP TABLE IF EXISTS public.locations;
ALTER TABLE public.organization_units DROP CONSTRAINT IF EXISTS fk_organization_units_legal_entity;
ALTER TABLE public.organization_units DROP COLUMN IF EXISTS legal_entity_id;
DROP TABLE IF EXISTS public.legal_entities;
ALTER TABLE public.tenants
    DROP CONSTRAINT IF EXISTS ck_tenants_pc1_row_version,
    DROP CONSTRAINT IF EXISTS ck_tenants_pc1_lifecycle_dates,
    DROP CONSTRAINT IF EXISTS ck_tenants_pc1_lifecycle,
    DROP COLUMN IF EXISTS row_version,
    DROP COLUMN IF EXISTS retired_at,
    DROP COLUMN IF EXISTS suspended_at,
    DROP COLUMN IF EXISTS lifecycle_state;
