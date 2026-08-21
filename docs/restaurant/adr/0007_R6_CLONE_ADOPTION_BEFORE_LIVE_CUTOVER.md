# ADR 0007 — R6 clone adoption before live WND cutover

Status: Accepted for R6.1 rehearsal.

## Decision

The Track A WND reference release `wnd-track-a-reference-release-20260821` is not migrated in place during R6.1.

The exact snapshot-aligned backup `WND_R6_0_SERVER_PRODUCTION_SNAPSHOT_20260821_171736.backup` is restored into two hard-coded disposable databases. One remains an immutable source control. The second rehearses neutral lineage adoption and Restaurant Pack composition.

Production `xbos` remains untouched.

## Additional 21 Aug reference-release constraint

The live legacy schema contains post-stamp WND reference extensions: order fulfillment mode, Customer identity, and optional A/R customer linkage. R6.1 must prove these survive additive neutral adoption without backfill, identity guessing or authority reassignment.

## Consequence

Only a green disposable-clone rehearsal may authorize R6.2 production-shaped mapping work. Live writer retirement or production cutover still requires explicit later authorization.
