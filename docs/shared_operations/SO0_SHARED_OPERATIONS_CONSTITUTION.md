# SO0 Shared Operations Constitution

SO0 establishes the laws for SO1–SO10. It implements none of their operational capabilities and adds no persistence.

## Authority boundary

Platform Core remains authority for structure, Party identity, semantics, typed configuration, business time, identity, authorization, approval policy and generic audit. Shared Operations consumes those public contracts and owns reusable operational truth. Finance remains the sole financial authority. XA remains the frontend-experience authority. PK will own pack and template lifecycle.

An operational fact is not a financial event. SO may emit approved operational evidence; it may not invent revenue, expenses, receivables, payables, settlements, journals or reconciliation truth. Finance transactional source identity, idempotency, outbox and atomicity are untouched.

## Module law

Every future SO module declares a stable code, capabilities, public commands and queries, operational facts, Platform Core dependencies, optional Finance integration, permissions, configuration and semantic dependencies, XA hooks, lifecycle, pack hooks and ownership classification.

Cross-module access is public-contract only. Another module's repository, SQL, private persistence and internal domain are inaccessible. Commands validate tenant/scope, use PC5 authorization and return stable result/error contracts. Queries never mutate.

Operational records use stable public IDs across boundaries, explicit tenant and authority type, actor/time/scope attribution and appropriate concurrency/history rules. Equal table-local integer IDs have no cross-authority meaning.

## Prospective ownership refinements

Atomic Units are implemented by SO1; SO0 performs no data or schema change. The older frozen “SO0” label is retained as program provenance. Delivery, retries, notifications, integration and offline support belong to SO8; SO9 owns operational reporting, read models and report automation. These refinements change no frozen Platform Core bytes.

## Neutrality

Industry behavior belongs to packs and templates. Generic SO source has no active defaults for the legacy tenant, restaurant/hospitality workflows, a neighborhood, or country-specific payment assumptions. Historical references require named compatibility documentation.

Run `XBOS_SO0_RUN_ACCEPTANCE.cmd` from the exact source checkpoint in the approved active Python 3.13.3 environment. The gate runs frozen PC/XA checks, SO0 conformance, full regression, compilation, JSON validation and `git diff --check`.
