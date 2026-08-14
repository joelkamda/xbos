# ADR 0013: SO2 relationship around PC2 Party

Status: accepted for SO2 candidate acceptance.

Decision: reuse the PC2 tenant-scoped Party composite identity and add one SO2 operational relationship aggregate. PC2 `party_roles` and `party_relationships` remain identity-graph facts; SO2 relationship types describe operational participation and grant no authorization. A real-world entity participating in different tenants requires explicit PC2 tenant Party records and independent SO2 relationships; SO2 does not globalize PC2 Party.

Consequences: the schema has no customer, supplier, person, organization or authentication table. One Party may carry several SO2 relationship types. Lifecycle history is append-only, preferences exclude canonical contacts/consent, segmentation is PC3-owned, authorization/audit are PC5-owned, Finance remains unchanged, and legacy strings are bridge evidence only.
