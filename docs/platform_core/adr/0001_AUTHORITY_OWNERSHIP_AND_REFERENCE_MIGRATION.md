# ADR 0001: Authority Ownership and Reference Migration

- Status: Accepted
- Scope: PC0

## Decision

Every inventoried authority has exactly one declared owner in the data-authority register. Existing storage does not acquire target-authority status by implication. Every shared reference that changes authority has an explicit current authority, target authority, compatibility path, retirement owner, and milestone.

Tenant is the isolation/customer boundary; Organization Unit is the operational/management hierarchy; Legal Entity is the juridical/accounting owner; Location is a physical or virtual place. PC1 adopts `organization_units` in place and maps legacy `branches`; it must not introduce a competing hierarchy. Identity is global with tenant-scoped memberships and remains separate from Party.

Neutral Finance retains transactional source, financial idempotency, financial outbox, historical resolved financial-time facts, evidence hashes/references, contracts, tables, writers, and semantics. PC0 defines boundary law only. SO9 owns future generic delivery/jobs/retries/offline operations, PC5 generic audit, SO7 generic document/file authority, PC4 core-module/configuration/entitlement and prospective business-time authority, and PK pack lifecycle.

## Consequences

PC0 performs no reference migration, backfill, schema change, cutover, or writer retirement. Later packages must use the registered compatibility paths and close their named retirement milestones explicitly.
