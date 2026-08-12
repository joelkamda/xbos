# ADR 0004: Adopt Existing Structural Authorities In Place

- Status: Accepted
- Scope: PC1

## Decision

`tenants` is adopted and evolved without replacing IDs. `organization_units` is promoted in place as the sole organization hierarchy; its existing composite tenant keys and all Neutral Finance references remain intact. Legal Entity and Location are separate tenant-scoped authorities and are never aliases for Tenant, Organization Unit, or Branch.

Legacy `branches` remains a compatibility runtime surface. Each existing branch receives deterministic organization-unit and location mappings. New Platform Core code resolves branches only through that bridge and may not depend on branches as canonical hierarchy.

## Consequences

PC1 adds lifecycle columns, Legal Entity and Location tables, a branch mapping table, bounded provisioning command records, and a hierarchy-cycle trigger. It changes no Finance writer, economic table, organization reference, authentication, Party, configuration-value, WND cutover, or pack authority.
