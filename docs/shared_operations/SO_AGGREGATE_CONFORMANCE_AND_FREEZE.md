# Shared Operations Aggregate Conformance and Freeze

This milestone closes Shared Operations as a coherent neutral operating layer. It adds no business capability. SO0–SO10 remain the owners of the capabilities already accepted by their individual gates, while Platform Core, XA and Neutral Finance retain their frozen authorities.

The aggregate audit checks the authority graph, public application boundaries, tenant isolation, neutrality, migration lineage, XA compatibility, production dependency authority, frozen Finance integrity, release fingerprints and PK consumption readiness. It treats derived search/report projections as non-authoritative, operational facts as non-financial, and frontend metadata as non-authorization.

## Aggregate hardening discovered by conformance

The audit found one concrete descendant defect: the original SO2 relationship command ledger used a globally unique `command_key`, unlike the tenant-qualified command ledgers in SO3–SO10. The SO2 command fingerprint includes `tenant_id`, so two independent tenants reusing the same client command key could receive a false `SO2_COMMAND_CONFLICT`.

The aggregate hardening migration adds `tenant_id` to `so2_relationship_commands`, backfills completed historical commands through their relationship result, fails closed if any row cannot be assigned to a tenant, changes uniqueness to `(tenant_id, command_key)`, and tenant-qualifies the result foreign key. The repository uses the tenant-qualified path at aggregate head while retaining historical replay compatibility for disposable SO2 predecessor rehearsals.

This is conformance hardening only. It does not change Party identity, relationship lifecycle, CRM meaning, Finance semantics, provider behavior, or production dependencies.

## Public-boundary proof

SO application code may consume another SO module only through its public package. Aggregate static proof rejects imports of another module's private repository/internal implementation and rejects SQL writes to another SO or Finance-owned table. Tenant-qualified relational foreign keys and read-only reference resolution do not transfer source-domain authority.

## Migration and operator proof

The aggregate head is `so_aggregate_conformance_hardening_036`, a single linear descendant of `so10_scheduling_reservations_service_execution_035`. The operator gate performs clean replay through SO10, upgrades to aggregate head, downgrades/re-upgrades the hardening revision while the data is downgrade-compatible, proves independent tenants can safely reuse the same SO2 command key, verifies tenant-qualified result integrity, confirms Finance row counts remain unchanged, adopts the development database resumably, and then runs the complete regression.

After `SO_AGG_SINGLE_GATE=PASS`, the control room may commit and tag the Shared Operations aggregate freeze. PK may then consume SO capabilities; it must not redefine their persistence or financial truth.
