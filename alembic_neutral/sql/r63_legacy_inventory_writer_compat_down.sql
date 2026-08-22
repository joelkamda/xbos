DROP TRIGGER IF EXISTS trg_r63_legacy_inventory_movement_fill_neutral_fields
ON public.inventory_movements;

DROP FUNCTION IF EXISTS public.r63_legacy_inventory_movement_fill_neutral_fields();

DROP TRIGGER IF EXISTS trg_r63_legacy_inventory_item_fill_neutral_fields
ON public.inventory_items;

DROP FUNCTION IF EXISTS public.r63_legacy_inventory_item_fill_neutral_fields();
