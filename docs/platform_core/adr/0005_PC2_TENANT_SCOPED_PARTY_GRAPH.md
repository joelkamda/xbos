# ADR 0005: Tenant-scoped Party graph

Status: Accepted for PC2

## Decision

Party is tenant-scoped and has exactly two initial subtypes: Person and Organization Party. Business participation is represented through effective-dated roles and typed relationships. Exact identifiers and explicit mappings are authoritative; fuzzy matching is not.

PC1 Legal Entity remains distinct and may link one-to-one to Organization Party. PC5 Identity remains distinct and may later associate through explicit tenant membership. Finance counterparty snapshots remain Finance-owned.

## Consequences

- Cross-tenant Party reads and graph edges fail closed.
- The same real-world entity in two tenants is not automatically merged.
- A Party can hold multiple business roles without creating customer/vendor entity roots.
- Historical roles and relationships expire rather than being destructively deleted.
- Existing users and counterparties are preserved until explicit mapping evidence exists.
