DROP TRIGGER IF EXISTS trg_allocation_reversals_validate_capacity ON public.allocation_reversals;
DROP FUNCTION IF EXISTS public.xbos_validate_allocation_reversal_capacity();
DROP TRIGGER IF EXISTS trg_allocation_scope_policies_immutable ON public.allocation_scope_policies;
DROP TABLE IF EXISTS public.allocation_scope_policies;

CREATE OR REPLACE FUNCTION public.xbos_validate_payment_allocation_scope()
RETURNS trigger LANGUAGE plpgsql AS $body$
DECLARE source_org_id BIGINT; obligation_org_id BIGINT;
BEGIN
  SELECT organization_unit_id INTO source_org_id FROM public.value_sources
    WHERE tenant_id=NEW.tenant_id AND id=NEW.value_source_id;
  SELECT organization_unit_id INTO obligation_org_id FROM public.financial_obligations
    WHERE tenant_id=NEW.tenant_id AND id=NEW.obligation_id;
  IF obligation_org_id IS NOT NULL AND NEW.organization_unit_id <> obligation_org_id THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='allocation organization must be the obligation organization';
  END IF;
  IF source_org_id IS NOT NULL AND obligation_org_id IS NOT NULL THEN
    IF source_org_id <> obligation_org_id AND NEW.cross_organization_policy_code IS NULL THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='cross-organization allocation requires explicit policy';
    END IF;
    IF source_org_id = obligation_org_id AND NEW.cross_organization_policy_code IS NOT NULL THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='cross-organization policy is invalid for same-organization allocation';
    END IF;
  END IF;
  RETURN NEW;
END
$body$;
