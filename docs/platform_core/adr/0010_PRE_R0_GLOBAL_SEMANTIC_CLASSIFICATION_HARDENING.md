# ADR 0010 — Global Semantic Classification Hardening Before R0

## Status

Accepted candidate pending authoritative operator gate.

## Decision

Extend frozen PC3 additively before Restaurant R0 with a global-capable semantic taxonomy placement layer, effective-dated placement history, tenant overlays, tenant-qualified semantic-classification idempotency, governed target validation, provenance/effective classification governance, and five backend read lenses.

Do not alter frozen PC3/SO1/PK/PA/Finance artifacts. Do not make Restaurant or WND the semantic architecture. Do not clone inherited taxonomy trees per tenant. Do not introduce a universal DAG. Do not create a second template authority.

## Rationale

PC3's WND-compatible `taxonomy_nodes.tenant_id NOT NULL` cannot represent global/pack nodes and its mutable parent field cannot preserve historical hierarchy placement. Global XBOS requires semantic classifications that may be contributed by kernel, Finance, packs and tenants while remaining independently governed and historically explainable.

A new additive global placement table avoids weakening or rewriting the frozen WND compatibility tree. PK/PA supplies composition context; PC3 supplies semantics. Tenant overlays persist only deltas.

## Consequences

- The original PC3 `taxonomy_nodes` and `atomic_unit_taxonomy` remain compatibility bridges until explicit migration.
- New global/pack semantics use `semantic_taxonomy_nodes` and effective placements.
- Existing PC3 `classification_assignments` remains the semantic snapshot base; governance is extended through a one-to-one sidecar.
- New target types require an explicit native-authority validator.
- The 40-system global registry is a seed constitution, not an exhaustive ceiling.
- R0 becomes the first industry contributor after this checkpoint passes; R5/R6 later map WND without rewriting historical meaning.
