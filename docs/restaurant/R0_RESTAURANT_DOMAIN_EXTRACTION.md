# R0 — Restaurant Domain Extraction

## Status

R0 is the first Restaurant-pack checkpoint after accepted Pre-R0 Semantic Classification Hardening. It is intentionally a **boundary/extraction freeze**, not Restaurant runtime implementation.

Source checkpoint: `64eb3e98135261ef20cd90622c1fd64bf24c99d8`  
Canonical migration head: `semantic_classification_hardening_041`  
WND production specimen tag: `wnd-track-a-final-accepted-20260818`

## Why R0 exists

WND proves real operating behavior, but WND is not the Restaurant-industry standard. R0 uses WND to preserve production invariants and discover legacy coupling while independently reserving the capabilities a robust Restaurant pack requires.

The Restaurant pack may deepen restaurant-specific operational meaning. It may not recreate or absorb Platform Core, Shared Operations, Pack Platform, Platform Administration, XA, or Neutral Finance truth.

## Frozen authority boundary

- PC1: tenant / organization / legal entity / location identity.
- PC2 + SO2: Party and operational relationships.
- PC3 + SC41: semantic identity, taxonomy, global/pack/tenant hierarchy and classifications.
- PC4: business time, localization and typed configuration.
- PC5: identity, permission, approval and audit.
- SO1: Atomic Units, catalogs, offers and prices. A Restaurant menu is an SO1 projection.
- SO3: inventory quantities, reservation, issue, movement, count and correction.
- SO5: Resource identity/capacity; Restaurant adds dining/table/station semantics without duplicating resource identity.
- SO6: generalized workflow/task/operational approval.
- SO7: documents/files/evidence.
- SO8: durable delivery jobs, retries, provider/integration envelopes and offline support.
- SO9: reports/read models/metrics.
- SO10: scheduling/reservations/service execution.
- Neutral Finance: obligations, receivables/payables, payments, settlement, allocations, journals, reconciliation and close.
- PK: pack and template composition.
- PA: merchant lifecycle/readiness/support.
- XA/F: experience contracts and presentation.

Restaurant owns only Restaurant-domain operational concepts and their legal handoffs to the authorities above.

## R0 aggregate boundaries

### `restaurant_order` — R1
Restaurant-owned order identity, line intent, lifecycle, service-mode context and participant references. It does not own canonical catalog price, inventory quantity, Party identity, financial obligation or settlement.

### `restaurant_service_session` — R1, optional
Dine-in/service-session state including guest count and restaurant resource assignments. SO5 still owns resource identity. Quick-service/takeaway/delivery orders need not invent a dine-in session.

### `restaurant_tab` — R1, optional
Operational grouping/partition intent for orders, lines or guests. It is **not** an A/R or balance authority. Amount owed, payment allocation and settlement remain Finance.

### `preparation_ticket` — R2
Kitchen/bar preparation intent, station routing intent, hold/fire/course state and partial readiness. SO8 owns durable dispatch; device/printer identity does not move into Restaurant.

### `restaurant_preparation_spec` — R2
Recipe/preparation/yield/portion semantics referencing SO1 Atomic Units and SO3 stock authority. It does not establish a universal costing model.

## WND production truths that become acceptance constraints

R0 records, but does not reimplement, the final Track A invariants. In particular:

1. A/R repayment is settlement of an existing receivable, not new income.
2. Reconciliation continuity/cascades and closed evidence remain Neutral Finance/control truth.
3. A reserved sale has exactly one inventory quantity effect.
4. `sale_commit` is finalization evidence and never a second deduction.
5. Direct-sale fallback deducts once only where no reservation lifecycle exists.
6. Manual inventory mutation remains stockability-gated, atomic and retry-safe.
7. Non-stock charges never affect inventory.
8. POS sales quantity is control evidence, not another stock deduction.
9. Historical mismatches/timestamps are preserved and explained, not silently rewritten.
10. WND conservative valuation must not become a universal Restaurant costing model.

## WND is not the Restaurant capability ceiling

The WND specimen does not prove or currently exercise every capability required by the future Restaurant pack. R0 therefore explicitly reserves support for dining areas/tables, configurable service modes, tabs/checks, split-bill partitioning, reservation/waitlist composition, station-aware kitchen/bar routing, course/hold/fire controls, multi-station fulfillment, recipes/yield/waste, external order channels and richer staff/service attribution.

Absence from WND is not grounds for omission from Restaurant.

## Extraction and migration law

Legacy `core/domain/orders`, `core/domain/sales`, WND-specific inventory coupling and the local kitchen-print watcher are **compatibility evidence**. R1-R5 may add canonical Restaurant-pack authorities; R6 alone retires legacy writers/adapters after migration rehearsal, financial controls, UAT and rollback proof.

WND-specific calendar, 18:00 attribution, payment choices, branding, terminology and taxonomy deltas become tenant/template/configuration rather than Restaurant or kernel constants.

## R0 does not authorize

- a database migration;
- a new Restaurant table;
- a Restaurant writer or API;
- a frontend route;
- any financial writer;
- replacement of SO1-SO10 or PC authorities;
- removal of a WND compatibility path.

R1 begins only after `R0_SINGLE_GATE=PASS`.
