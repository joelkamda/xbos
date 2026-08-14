DROP TRIGGER IF EXISTS trg_so3_inventory_movement_immutable ON public.inventory_movements;
DROP FUNCTION IF EXISTS public.so3_inventory_movement_immutable();
DROP TABLE IF EXISTS public.so3_stock_transfers;
DROP TABLE IF EXISTS public.so3_stock_counts;
DROP TABLE IF EXISTS public.so3_stock_reservations;
DROP TABLE IF EXISTS public.so3_inventory_commands;
ALTER TABLE public.inventory_movements DROP CONSTRAINT IF EXISTS fk_so3_movement_correction;
ALTER TABLE public.inventory_movements DROP CONSTRAINT IF EXISTS fk_so3_movement_atomic_unit;
ALTER TABLE public.inventory_movements DROP CONSTRAINT IF EXISTS fk_so3_movement_item;
ALTER TABLE public.inventory_movements DROP CONSTRAINT IF EXISTS fk_so3_movement_location;
ALTER TABLE public.inventory_movements DROP CONSTRAINT IF EXISTS uq_so3_movement_public;
ALTER TABLE public.inventory_movements DROP CONSTRAINT IF EXISTS uq_so3_movement_tenant_id;
DROP INDEX IF EXISTS public.uq_so3_one_correction;
DROP INDEX IF EXISTS public.ix_so3_movement_history;
ALTER TABLE public.inventory_movements DROP COLUMN IF EXISTS metadata, DROP COLUMN IF EXISTS quantity_after,
 DROP COLUMN IF EXISTS related_public_id, DROP COLUMN IF EXISTS correction_of_id, DROP COLUMN IF EXISTS request_fingerprint,
 DROP COLUMN IF EXISTS reason_code, DROP COLUMN IF EXISTS occurred_at, DROP COLUMN IF EXISTS source_reference,
 DROP COLUMN IF EXISTS stock_location_id, DROP COLUMN IF EXISTS public_id;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.inventory_items WHERE branch_id IS NULL) THEN
 RAISE EXCEPTION 'SO3 downgrade blocked: non-legacy stock locations exist'; END IF; END $$;
ALTER TABLE public.inventory_items DROP CONSTRAINT IF EXISTS fk_so3_inventory_location;
ALTER TABLE public.inventory_items DROP CONSTRAINT IF EXISTS fk_so3_inventory_atomic_unit;
ALTER TABLE public.inventory_items DROP CONSTRAINT IF EXISTS uq_so3_inventory_position;
ALTER TABLE public.inventory_items DROP CONSTRAINT IF EXISTS uq_so3_inventory_item_public;
ALTER TABLE public.inventory_items DROP CONSTRAINT IF EXISTS uq_so3_inventory_item_tenant_id;
ALTER TABLE public.inventory_items DROP CONSTRAINT IF EXISTS ck_so3_reserved_nonnegative;
ALTER TABLE public.inventory_items ALTER COLUMN branch_id SET NOT NULL;
ALTER TABLE public.inventory_items DROP COLUMN IF EXISTS updated_at, DROP COLUMN IF EXISTS row_version,
 DROP COLUMN IF EXISTS reserved_quantity, DROP COLUMN IF EXISTS stock_location_id, DROP COLUMN IF EXISTS public_id;
DROP TABLE IF EXISTS public.so3_stock_locations;
