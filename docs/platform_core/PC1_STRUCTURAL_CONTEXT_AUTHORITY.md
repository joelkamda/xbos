# PC1 Tenant and Structural-Context Authority

PC1 evolves `tenants` and promotes `organization_units` in place. It introduces distinct `legal_entities` and `locations`, plus an explicit bridge from every legacy `branches` row to one organization unit and one location. Existing tenant, organization-unit, branch, and Finance identifiers are preserved.

Tenant lifecycle is governed by `provisioned`, `active`, `suspended`, and `retired`; retirement replaces normal destructive deletion. The structural resolver accepts explicit tenant, organization, legal-entity, location, and compatibility branch references, verifies every reference within the supplied tenant, resolves ancestry root-to-leaf, and fails on ambiguity, cycles, missing parents, unavailable tenants, or conflicting branch context.

Provisioning uses a PC1-local command key and canonical payload fingerprint. It does not reuse Finance idempotency or create a generic Platform idempotency authority. Structural export is canonical tenant-scoped JSON and creates no economic effect.

The single migration `pc1_structural_context_021` follows `m64_reconciliation_controls_020`. Its branch backfill uses separate, ordered organization, location, and mapping statements so mappings can see the newly created structural rows. The acceptance verifier reconstructs one coherent clean fixture, then rehearses clean upgrade, compatibility adoption, public provisioning, lifecycle, hierarchy/cycle protection, distinct legal/location context, cross-tenant denial, replay/conflict/concurrency, deterministic export, downgrade/re-upgrade, and cleanup in `xbos_platform_core_pc1_test` before controlled development upgrade. It refuses non-local PostgreSQL and confirms financial row counts do not change.
