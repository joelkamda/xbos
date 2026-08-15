# ADR 0027 — PA6 freezes Platform Administration without acquiring domain authority

## Status
Accepted by PA6 aggregate conformance gate.

## Decision
Platform Administration is frozen as an orchestration and evidence layer. It may coordinate merchant lifecycle administration, commercial subscriptions, usage quotas, onboarding readiness, bounded support/recovery and health observation, but it may not become tenant lifecycle, runtime entitlement, authorization, pack-composition, operational or financial source truth.

No PA6 schema revision is introduced. The canonical head remains `pa45_support_recovery_health_040`.

## Consequences
- PC1 remains tenant lifecycle authority.
- PC4 remains effective runtime configuration and entitlement authority.
- PC5 remains identity, authorization, step-up and audit authority.
- PK remains pack/template composition authority.
- Finance and Shared Operations remain unchanged.
- Health and recovery evidence can trigger investigation or an explicitly authorized command elsewhere, but never mutate another authority merely because PA observed a problem.
- Future descendants must preserve the PA0123 -> PA45 migration prefix and the aggregate authority boundaries frozen here.
