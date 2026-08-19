# ADR 0006 — R5 WND Tenant/Template Composition Boundary

## Decision

R5 proves Wine & Dine as a tenant-specific composition of the certified Restaurant pack rather than as Restaurant source-code behavior.

A proof-only WND-shaped tenant is provisioned through PC1, the Restaurant pack is staged/installed/activated through PK, an explicit Restaurant template version is applied through PK4-PK6, and the resulting operating configuration is materialized through PC4.

## Consequences

- WND is pinned to `restaurant.counter_service@1.0.0`.
- `restaurant.full_service@1.0.0` remains a sibling proof that WND is not the capability ceiling.
- 08:00 business-day boundary, 18:00 payment-shift cutoff, payment choices, branding and terminology are tenant configuration.
- Commission attribution remains the original order creator.
- WND taxonomy, menu/catalog, staff, Finance, document and inventory data are migration plans only in R5.
- R5 creates no schema migration and no duplicate operational or financial authority.
- Production `xbos` is unchanged.

## Deferred to R6

Actual WND tenant/Logpom mapping, production data transformation, frontend UAT, final delta migration, writer retirement, cutover and rollback/recovery proof remain R6 responsibilities.
