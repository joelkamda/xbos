# ADR 0008 — R6.2 uses mapped-or-withheld shadow reconciliation before WND authority cutover

## Status
Accepted for R6.2 rehearsal.

## Context
The WND reference release contains reliable production truth alongside intentionally unresolved historical evidence: legacy allowance representation, older A/R satisfaction without complete repayment rows, missing historical inventory cost basis, and historical receipt identities without immutable original content hashes.

Forcing all of that history into canonical commands would fabricate facts.

## Decision
R6.2 executes deterministic M7 mapping services only for source records that satisfy their canonical contracts. Every other source amount is retained in an explicit withheld ledger.

The mandatory equation is:

`legacy source = canonical mapped shadow + explicit withheld`

Dual-read differences must equal the withheld ledger. They are not auto-corrected.

R6.2 may prepare but may not execute writer retirement.

## Consequences
- R6.2 can complete even when canonical-only historical parity is intentionally impossible, provided every variance is explicit and exactly reconciled.
- No zero COGS is invented from missing cost basis.
- No historical A/R payment is invented from aggregate balances.
- No historical customer identity is inferred by name.
- No historical receipt is regenerated as an original.
- R6.3 can test the application against a neutral candidate while legacy-primary historical read compatibility remains available.
