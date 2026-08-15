# ADR 0024 — PK certification, immutable templates and explicit upgrades

## Decision

Pack certification is immutable evidence, template versions are immutable composition declarations, tenant template state is version-pinned, and upgrades require a deterministic preflight plus explicit acceptance.

## Why

XBOS must support many products and industries without turning templates into hidden source code forks or alternative authorities. Silent template mutation would make merchant behavior non-reproducible. Certification without evidence would provide false assurance. Auto-upgrade without conflict detection would destroy legitimate merchant divergence.

## Consequences

1. Certification records bind pack version, manifest hash, conformance-suite version and evidence hashes.
2. Templates reference PC3 semantics and public PC/SO/Finance/XA contracts; they do not rewrite them.
3. Merchant override paths are allowlisted by the immutable template version.
4. Two merchants may start from the same template and legitimately diverge through allowed overrides.
5. Applying or upgrading a template never grants permissions and never changes Finance truth directly.
6. A Payments-only product may hide the Accounting workspace while keeping the Neutral Finance kernel active.
7. Outbound provider execution remains an edge/integration concern unless a conformance test proves a missing universal Finance invariant.
