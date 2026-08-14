# SO10 Scheduling, Reservations and Service Execution

SO10 establishes neutral time-bound scheduling authority without redefining Party, catalog, resources, workflow, delivery or Finance.

## Authority boundaries

- PC4 owns prospective business calendars, timezone and business-time interpretation.
- PC1 owns locations and structural context.
- PC2 and SO2 own Party identity and operational participation.
- SO1 owns Atomic Units/offers used as schedulable targets.
- SO5 owns Resource identity and operational capacity metadata.
- PC5 owns authorization.
- SO6 remains generalized workflow/task authority.
- SO8 remains communications/reminder delivery authority.
- Neutral Finance remains the sole financial authority.

A reservation is not a receivable, obligation, payment or revenue event. Service completion is operational evidence only.

## Schedulable services and availability

A scheduling service references one SO1 Atomic Unit or Offer and one immutable PC4 business-calendar version. SO10 availability windows bind that service to a PC1 Location, UTC interval and bounded capacity. Availability windows do not create resources or change PC4 calendars.

Every requested/confirmed interval is timezone-aware, normalized to UTC and resolved through PC4. One reservation must resolve to one PC4 business date. Actual bookability is additionally constrained by explicit SO10 availability windows.

## Reservation lifecycle

The neutral lifecycle is `requested → confirmed → completed`, with terminal `cancelled` and `no_show` alternatives. Rescheduling preserves the same reservation identity, increments optimistic version state and appends explicit history.

Confirmation and rescheduling require an explicit PC1 location, then serialize the authoritative reservation and matching location-specific availability-window rows. SO5 Resource rows are locked in deterministic public-id order while capacity is checked, preventing concurrent over-allocation without creating a second Resource authority.

Resource-allocation rows are immutable and versioned by reservation row version. Earlier allocation sets remain historical evidence after rescheduling.

## Service execution

Starting service creates one operational execution for a confirmed reservation. Completion records result/evidence reference, completes the execution and changes reservation state to `completed`. This does not post Finance, settle payment or mark an SO6 workflow complete.

## Idempotency and isolation

Every mutation uses a tenant-scoped SO10 command key plus exact canonical command fingerprint. Exact replay returns the prior result; changed content under the same key fails with `SO10_COMMAND_CONFLICT`.

All persistent references are tenant-qualified. Availability, reservations, resources and service executions cannot bind foreign-tenant authorities.

## Neutrality and future composition

Clinical appointments and field-service visits use the same SO10 source with different terminology/configuration. Hotel, restaurant, clinic or field-service semantics belong in future packs/templates, not the SO10 kernel.
