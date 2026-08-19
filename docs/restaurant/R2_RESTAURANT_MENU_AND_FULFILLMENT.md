# R2 — Restaurant Menu and Fulfillment

Source checkpoint: `053fb8a6bbe40c11eeaeef23113ad2888122de65`

Canonical predecessor: `r1_restaurant_service_operation_042`

Canonical accepted head: `r2_restaurant_menu_fulfillment_043`

R2 is the Restaurant pack's menu/preparation authority. It deliberately does not turn Restaurant into a second catalog, inventory, delivery, or financial system.

## Menu

A Restaurant menu is an SO1 catalog projection. R2 adds Restaurant presentation sections, explicit SO1 catalog-entry placement, and modifier choice semantics around SO1 catalog entries, Atomic Units, offers, and prices. It does not duplicate those identities. Section placement is tenant-safe and cannot attach an entry from a different SO1 catalog.

Modifier selections are versioned append-only operational snapshots attached to R1 order lines. This allows preparation meaning to remain explainable even when the future menu configuration changes.

## Stations and routing

SO5 remains the resource identity authority. R2 profiles resources as kitchen, bar, expo, pastry, prep, beverage, pickup, or other Restaurant stations and defines effective-dated routing rules. Rules may target an SO1 item/offer directly or consume SC41 semantic classification through an injected resolver. One order line may fan out to more than one station.

No station is assumed to be a printer. KDS, printers, screens, local agents, and provider adapters are delivery mechanisms outside Restaurant truth.

## Tickets

Preparation tickets own Restaurant preparation intent and state: held, fired/queued, in progress, partial readiness, ready, completed, or voided. A release may target selected R1 order lines, allowing course-specific firing without changing R1 order truth. Ticket items remain linked to R1 order lines and snapshot selected modifiers, including their SO1 price/instruction evidence for later R3 handoff. Parent readiness rolls up from item state. Multi-ticket release replay is scoped to the exact tenant command, not every historical ticket for an order.

SO8 owns durable delivery jobs, retry, dead-letter, devices, and provider behavior. R2 exposes a deterministic delivery handoff only.

## Recipes, yield, and waste

Preparation specifications are versioned and may depend on Atomic Units or earlier preparation specifications. Preparation runs record planned inputs, actual consumption, output yield, and waste.

SO3 remains the only inventory movement/position authority. R2 emits deterministic stock intents; it does not insert inventory movements or alter balances. Costing and valuation remain outside Restaurant authority.

## WND boundary

WND's accepted local kitchen-print watcher is migration evidence, not the Restaurant standard. R2 therefore supports station routing and delivery-neutral ticket payloads without requiring WND's printer topology, menu shape, or kitchen maturity.
