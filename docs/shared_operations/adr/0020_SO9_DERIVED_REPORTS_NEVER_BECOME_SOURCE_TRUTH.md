# ADR 0020 — SO9 derived reports never become source-domain truth

## Status
Accepted for SO9 candidate implementation.

## Decision
SO9 owns derived operational read-model definitions, immutable projection snapshots, metric definitions, report definitions/runs and bounded report-automation rules/runs. Canonical business facts stay with their source authorities. SO9 therefore stores source identity/fingerprints and rebuildable results rather than promoting report tables into transactional truth.

Legacy `core.domain.reports` remains compatibility-only until source-specific convergence. Neutral Finance continues to own Finance read models and reporting semantics. SO8 owns actual report delivery; SO9 records and orchestrates only report automation intent through the SO8 public handoff.

## Consequences

- Report caches and projections may be rebuilt without mutating source domains.
- Metrics remain derived even when they display financial values.
- Report automation cannot complete workflows or schedule operational resources/services.
- Tenant filtering and PC5 authorization are mandatory on every query/mutation path.
- No new runtime dependency is required.
