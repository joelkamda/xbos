# ADR 0027 — PA support is bounded and health is derived evidence

## Decision

Platform Administration may own bounded support-session, recovery-case and health-snapshot evidence, while PC5 remains authorization truth and domain modules remain source truth for the data they own.

## Consequences

- Delegated support never creates a permanent role or membership.
- Break-glass is short-lived, step-up protected and incident-evidenced.
- Recovery coordination records what operators tried; it does not bypass the affected public authority.
- Health is a read/observation concern and cannot mutate Finance, SO, PK or PC truth.
- Append-only evidence survives session closure and case resolution.
- Secret material is kept out of generic metadata.
