CREATE OR REPLACE FUNCTION public.r63_legacy_inventory_item_fill_neutral_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.stock_location_id IS NULL THEN
        SELECT s.id
          INTO NEW.stock_location_id
          FROM public.so3_stock_locations s
         WHERE s.tenant_id = NEW.tenant_id
           AND s.legacy_branch_id = NEW.branch_id
         ORDER BY s.id
         LIMIT 1;
    END IF;

    IF NEW.stock_location_id IS NULL THEN
        RAISE EXCEPTION
            'R6.3 legacy inventory item write has no SO3 stock location mapping (tenant_id=%, branch_id=%)',
            NEW.tenant_id,
            NEW.branch_id;
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_r63_legacy_inventory_item_fill_neutral_fields
ON public.inventory_items;

CREATE TRIGGER trg_r63_legacy_inventory_item_fill_neutral_fields
BEFORE INSERT ON public.inventory_items
FOR EACH ROW
EXECUTE FUNCTION public.r63_legacy_inventory_item_fill_neutral_fields();


CREATE OR REPLACE FUNCTION public.r63_legacy_inventory_movement_fill_neutral_fields()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    mapped_stock_location_id bigint;
BEGIN
    IF NEW.stock_location_id IS NULL THEN
        SELECT i.stock_location_id
          INTO mapped_stock_location_id
          FROM public.inventory_items i
         WHERE i.tenant_id = NEW.tenant_id
           AND i.id = NEW.inventory_item_id;

        NEW.stock_location_id := mapped_stock_location_id;
    END IF;

    IF NEW.stock_location_id IS NULL THEN
        RAISE EXCEPTION
            'R6.3 legacy inventory movement write has no SO3 stock location mapping (tenant_id=%, inventory_item_id=%)',
            NEW.tenant_id,
            NEW.inventory_item_id;
    END IF;

    NEW.occurred_at := COALESCE(
        NEW.occurred_at,
        NEW.created_at,
        now()
    );

    NEW.reason_code := COALESCE(
        NULLIF(btrim(NEW.reason_code), ''),
        NULLIF(
            lower(
                regexp_replace(
                    COALESCE(NEW.movement_type, ''),
                    '[^a-zA-Z0-9]+',
                    '-',
                    'g'
                )
            ),
            ''
        ),
        'legacy'
    );

    NEW.source_reference := COALESCE(
        NULLIF(btrim(NEW.source_reference), ''),
        NEW.reference_id::text,
        CASE
            WHEN NEW.id IS NOT NULL THEN 'legacy:' || NEW.id::text
            ELSE 'legacy:pending'
        END
    );

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_r63_legacy_inventory_movement_fill_neutral_fields
ON public.inventory_movements;

CREATE TRIGGER trg_r63_legacy_inventory_movement_fill_neutral_fields
BEFORE INSERT ON public.inventory_movements
FOR EACH ROW
EXECUTE FUNCTION public.r63_legacy_inventory_movement_fill_neutral_fields();

COMMENT ON FUNCTION public.r63_legacy_inventory_item_fill_neutral_fields()
IS 'R6.3 compatibility adapter: derives SO3 stock_location_id for still-active legacy WND inventory-item INSERT writers.';

COMMENT ON FUNCTION public.r63_legacy_inventory_movement_fill_neutral_fields()
IS 'R6.3 compatibility adapter: derives SO3-required neutral fields for still-active legacy WND inventory-movement INSERT writers without changing legacy quantity semantics.';
