# ADR 0001 — R0 Restaurant Domain Extraction Boundary

## Decision

Freeze Restaurant as an industry-pack operational authority that composes existing neutral authorities rather than duplicating them.

WND is treated as a production specimen/invariant source, not the Restaurant domain definition. Missing WND capabilities do not constrain the future pack.

## Consequences

- `restaurant_order`, optional service-session/tab semantics, preparation tickets and Restaurant preparation specifications are candidate pack-owned domains for R1/R2.
- Menu/catalog/offer/price remain SO1.
- Stock quantity/reservation/movement remain SO3.
- Resources remain SO5.
- Reservations remain SO10.
- Durable kitchen-print/integration delivery remains SO8.
- All economic truth remains Neutral Finance.
- SC41 supplies global/pack/tenant classification without cloned tenant trees.
- WND literals and operating rules move to R5 configuration/profile work.
- Legacy WND writers/adapters remain until R6 cutover proves retirement safe.

## Rejected

- Making current WND tables the canonical Restaurant schema.
- Treating lack of table service/reservations in WND as a Restaurant design decision.
- Creating Restaurant-specific stock, payment, reconciliation or accounting authorities.
- Reusing the local print watcher as the target durable kitchen-delivery architecture.
- Converting WND valuation behavior into a universal Restaurant costing model.
