# ADR 0022 — Shared Operations Aggregate Freeze and Tenant-Scoped Idempotency Hardening

## Decision

Freeze SO0–SO10 only after aggregate conformance establishes one linear authority graph and repairs the SO2 command ledger to use tenant-scoped idempotency.

## Context

SO0 requires explicit tenant context and fail-closed isolation. SO3–SO10 persist command identity as `(tenant_id, command_key)`. SO2 originally persisted `command_key` globally. Because command fingerprints include tenant identity, identical client-generated keys in different tenants could collide even though the business operations are unrelated.

## Consequences

`so_aggregate_conformance_hardening_036` adds no operational capability. It tenant-qualifies SO2 command uniqueness and result integrity. Completed historical commands are backfilled from their result relationship. Unresolved rows make the migration fail closed rather than guessing tenant ownership. Downgrade is refused once duplicate command keys exist across tenants because the historical global-unique schema could no longer represent that state safely.

Shared Operations remains operational only; Neutral Finance and XA are unchanged. Production cutover remains outside this milestone.
