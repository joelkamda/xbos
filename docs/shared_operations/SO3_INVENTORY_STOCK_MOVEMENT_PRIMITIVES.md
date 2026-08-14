# SO3 Inventory and Stock Movement Primitives

SO3 adopts the existing `inventory_items` position cache and `inventory_movements` ledger in place. It references the SO1 Atomic Unit and a PC1 Location through an SO3 stock-location role; legacy branches remain a compatibility reference only.

The public authority supports receipts, issues, adjustments, paired transfers, reservations, counts, corrections and tenant-scoped history. Commands are exactly replayable by key and fingerprint. Movement rows are append-only; corrections create compensating movements.

SO3 owns quantities, not financial value. It does not post journals, value inventory, define procurement, create UI, or replace PC1, SO1, PC5, XA or Finance authority. Negative-stock behavior is injected server policy. XA metadata describes presentation and denial surfaces but cannot authorize an operation.

Install by expanding the package over source checkpoint `fdb2cc8`, then run `XBOS_SO3_RUN_ACCEPTANCE.cmd` from the approved Python 3.13.3 environment. The gate performs a disposable clean replay and adopts the development database only after rehearsal.
