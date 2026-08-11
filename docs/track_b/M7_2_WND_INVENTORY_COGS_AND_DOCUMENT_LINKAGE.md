# M7.2 — WND inventory/COGS handoff and document linkage

M7.2 is a side-effect-free adapter package. It does not migrate a database, execute a canonical command, reroute a WND writer, or perform the R6 production cutover.

WND `inventory_movements` remain quantity truth; `inventory_items.quantity_on_hand` remains a cache. A fulfillment movement is eligible for a canonical `COST_OF_FULFILLMENT_RECOGNIZED` plan only when the source includes an exact positive cost basis, approved provenance, and immutable evidence hash. The posting shape is fulfillment expense against inventory/deferred-cost asset and never revenue.

An inventory movement without reliable historical cost is returned as `withheld: missing_reliable_cost_basis`. M7.2 does not infer cost from current mutable item metadata and does not manufacture zero COGS. This is particularly important for historical WND food records, although the rule applies neutrally to every inventory class.

Receipt and correction documents are linked to canonical public identities by document type, preserved source number, issued time, immutable content hash, and deterministic targets. The original artifact is never regenerated or rewritten. M7.2 is not a general file-management, rendering, or OCR subsystem.

M7.3 owns shadow execution, production-shaped rehearsal, and control-total comparison. R6 continues to own live migration and production cutover.
