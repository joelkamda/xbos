# M7.0 — Legacy financial authority inventory and adapter boundary

M7.0 freezes the WND financial surface that later M7 packages must map. It is deliberately schema-neutral and does not route, shadow, duplicate, or retire a writer.

## Authority boundary

The machine-readable inventory identifies each legacy reader or writer by source path and Python symbol, records its legacy stores, names the existing neutral-finance authority it must ultimately target, and assigns its next M7 package. The inventory is validated against the checked-out source so a renamed or removed surface fails closed instead of silently making the catalog stale.

The adapter contract accepts a tenant- and organization-scoped source envelope and permits deterministic assessment only. M7.0 exposes no execution method. It cannot post a financial event, mutate a legacy row, or switch a production route.

## Frozen ownership

- M7.1 owns commercial, payment, A/R, discount, complimentary, and refund mapping.
- M7.2 owns inventory/COGS handoff and receipt/document linkage.
- M7.3 owns shadow execution, production-shaped rehearsal, and control totals.
- M7.4 owns dual-read compatibility, cutover readiness, and writer-retirement support.
- M7.5 owns M7 conformance and freeze.
- R6, not M7, owns live WND operational migration and production cutover.

M7.0 therefore leaves all current WND writers and readers untouched. No legacy module imports or invokes the new inventory or adapter boundary.

## Historical evidence safeguards

The later inventory/COGS mapping must not fabricate Food COGS where WND lacks reliable automatic source truth. Existing historical receipts remain historical artifacts; they must not be regenerated and represented as originals. The inventory records those surfaces without pretending missing source facts exist.

## Acceptance

The gate checks the exact M6 freeze checkpoint, the unchanged canonical database head, contract and source-symbol completeness, stable adapter fingerprints, the absence of adapter routing from legacy code, the schema-neutral persistence marker, focused contracts, and the full regression suite.
