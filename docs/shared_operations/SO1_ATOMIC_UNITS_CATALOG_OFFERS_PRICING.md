# SO1 Atomic Units, Catalog, Offers and Pricing

SO1 adopts the existing `atomic_units.id` identity in place. The additive migration assigns every legacy row a deterministic stable `public_id` and adds lifecycle/version metadata without rewriting IDs, foreign keys, taxonomy links, inventory references, order/sale references or Finance evidence.

Atomic Unit, PC3 semantic identity, taxonomy placement, catalog entry, offer, price, inventory balance and financial account are separate concepts. `atomic_unit_taxonomy` remains a many-to-many compatibility bridge to PC3. The legacy `unit_price` column is preserved but is not the canonical SO1 price resolver.

SO1 adds tenant-scoped catalogs, catalog entries, offers, deterministic offer components and effective operational prices. Price resolution selects exact structural scope over tenant scope, then higher precedence and later effective start. Equal rank, precedence and start are ambiguous and fail. A commercial price is never revenue and produces no Finance event.

The public authority requires PC1 scope validation and PC5 server authorization. PC3 owns classification; PC4 supplies business time and configuration; PC2 remains Party identity authority. SO3 will own stock, movement, reservation, count, costing and replenishment. XA renders SO1 metadata but never computes authoritative prices.

The fixtures demonstrate a retail/service tenant and a professional-service tenant using the same source. Industry meaning and terminology remain future PK declarations; no frontend or pack engine is included.

Run `XBOS_SO1_RUN_ACCEPTANCE.cmd` from source checkpoint `f72f4b5d8ad8e576212347615458fcd801e9f7bd` in the approved Python 3.13.3 environment. PostgreSQL acceptance uses a disposable database first, then adopts the development database only after rehearsal succeeds.
