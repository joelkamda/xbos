-- WND Track A: general order fulfillment mode (Dine In / Takeaway / Delivery)
-- Historical rows deliberately remain NULL/UNSPECIFIED.

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS fulfillment_mode VARCHAR(20);

ALTER TABLE orders
    ALTER COLUMN fulfillment_mode SET DEFAULT 'DINE_IN';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_orders_fulfillment_mode'
          AND conrelid = 'orders'::regclass
    ) THEN
        ALTER TABLE orders
            ADD CONSTRAINT ck_orders_fulfillment_mode
            CHECK (
                fulfillment_mode IS NULL
                OR fulfillment_mode IN ('DINE_IN', 'TAKEAWAY', 'DELIVERY')
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_orders_tenant_branch_fulfillment_mode
    ON orders (tenant_id, branch_id, fulfillment_mode);

COMMENT ON COLUMN orders.fulfillment_mode IS
    'Customer fulfillment mode: DINE_IN, TAKEAWAY, DELIVERY. NULL = historical/unspecified.';
