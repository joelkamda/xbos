-- Track A WND Stock reconciliation close persistence.
-- Bounded operational schema; not the generalized Track B reconciliation model.
-- Apply explicitly only after environment-specific approval.

CREATE TABLE IF NOT EXISTS inventory_reconciliation_windows (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    business_date DATE NOT NULL,
    shift VARCHAR(16) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'closed',
    note TEXT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    line_count INTEGER NOT NULL DEFAULT 0,
    variance_line_count INTEGER NOT NULL DEFAULT 0,
    total_variance_qty INTEGER NOT NULL DEFAULT 0,
    closed_by_user_id INTEGER NULL,
    closed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_inventory_reconciliation_shift
        CHECK (shift IN ('day', 'night', 'full24')),
    CONSTRAINT ck_inventory_reconciliation_status
        CHECK (status IN ('closed')),
    CONSTRAINT uq_inventory_reconciliation_window
        UNIQUE (tenant_id, branch_id, business_date, shift)
);

CREATE INDEX IF NOT EXISTS ix_inventory_reconciliation_window_lookup
    ON inventory_reconciliation_windows
    (tenant_id, branch_id, business_date, shift);

CREATE TABLE IF NOT EXISTS inventory_reconciliation_lines (
    id BIGSERIAL PRIMARY KEY,
    window_id BIGINT NOT NULL
        REFERENCES inventory_reconciliation_windows(id)
        ON DELETE CASCADE,
    atomic_unit_id INTEGER NOT NULL,
    system_qty INTEGER NOT NULL,
    counted_qty INTEGER NOT NULL,
    variance_qty INTEGER NOT NULL,
    note TEXT NULL,
    movement_id BIGINT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_inventory_reconciliation_count_nonnegative
        CHECK (counted_qty >= 0),
    CONSTRAINT uq_inventory_reconciliation_line
        UNIQUE (window_id, atomic_unit_id)
);

CREATE INDEX IF NOT EXISTS ix_inventory_reconciliation_line_window
    ON inventory_reconciliation_lines(window_id);

CREATE INDEX IF NOT EXISTS ix_inventory_reconciliation_line_atomic
    ON inventory_reconciliation_lines(atomic_unit_id);
