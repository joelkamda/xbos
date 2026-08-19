# ADR 0003 — R2 Restaurant menu and fulfillment authority

## Decision

Restaurant owns menu projection semantics, modifiers, preparation routing/tickets, recipes, yield, and waste evidence.

SO1 owns catalog/offers/prices. SO5 owns resource identity. SO3 owns inventory truth. SO8 owns durable delivery. Finance owns economic truth.

## Consequences

- Menus are projections rather than a second catalog.
- Modifiers are Restaurant semantics referencing SO1 targets/prices.
- Stations are SO5 resources with Restaurant profiles.
- Tickets may fan out across stations and support hold/fire/course and partial readiness.
- Printer/KDS delivery is a handoff to SO8.
- Recipes and preparation runs may explain ingredient use, yield, and waste without writing stock or inventing costing.
- WND remains a production specimen, not the capability ceiling.
