# PA0123 — Merchant Lifecycle, Subscriptions, Usage and Onboarding

PA0123 covers PA0–PA3 as one bounded Platform Administration package.

## Authority boundary

PA owns merchant-administration progression, commercial plan/subscription intent, usage evidence/quota comparison, and onboarding/readiness orchestration. It **does not** replace PC1 tenant lifecycle, PC4 effective entitlement, PC5 authorization/identity, or PK template/pack composition.

`MerchantAdministrationState` is deliberately separate from `TenantLifecycle`. A merchant may be administratively onboarding while the tenant is already provisioned/active; PA never edits the PC1 lifecycle table.

A subscription's entitlement list is a commercial projection. Runtime entitlement truth remains PC4. A quota breach is visible operational/commercial evidence; it does not silently revoke entitlement or create financial effects.

Readiness is derived from four external authority checks: PC1 tenant availability, exact PK template pinning, PC4 entitlement effectiveness, and PC5 tenant-admin readiness. Every check carries an evidence reference. Completing onboarding records PA readiness only; it does not grant permissions, apply a template, activate a tenant, or authorize WND cutover.

Usage events and readiness snapshots are tenant-scoped and append-only. Command replay is exact and tenant-scoped.
