# ADR 0010: XA frontend authority and composition boundary

Status: Accepted candidate for operator gate
Source: `9ce8c1a5746ec7607636d6a9be20102194e9f230`

## Decision

XA is a schema-neutral contract layer outside the frozen `core/platform` implementation namespace. It consumes declared public Platform Core facade results and presents immutable metadata envelopes. XA has an independent release manifest so historical PC0–PC6 manifests and authorities remain unchanged.

The server supplies authorization decisions, transition legality, effective configuration, business time, capabilities, source provenance, projection freshness, and offline/idempotency policy. The frontend may select a declared composition and render or invoke what the contract describes; it may not manufacture those facts.

Future Shared Operations modules will own work, projections, documents, delivery and workflow capabilities. Future PK will own template composition. Future PA will own provisioning automation. Their references in examples are boundary declarations, not implementations.

## Consequences

- Platform and tenant shells remain structurally distinct.
- Tenant administration never implies platform authority.
- Hidden controls do not replace backend denial.
- Presentation diversity does not fork business contracts.
- XA requires no migration, UI runtime, React toolchain, or database write.
