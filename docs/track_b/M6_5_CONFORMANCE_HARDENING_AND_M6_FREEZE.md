# M6.5 — Conformance, hardening, and M6 freeze

M6.5 is the schema-neutral exit gate for Track B M6. It freezes the accepted M6.0–M6.4 semantic contracts at canonical head `m64_reconciliation_controls_020`; it creates no new financial authority.

The aggregate gate validates the single migration lineage and semantic manifest, proves the development database is structurally current and financially empty, and rehearses each accepted M6 capability on its own disposable clone. The final M6.4 clone also performs downgrade/upgrade recovery before exercising the complete M6.2–M6.4 reconciliation and close chain.

Frozen controls include operational-account balance provenance, bilateral non-P&L transfers, ordered series, deterministic calendar/shift attribution, predecessor continuity, append-only correction cascades, formal close protection, approved/evidenced reopen, and shared Bank/A/R/A/P reconciliation controls and deterministic reports.

Concurrency safety is frozen through tenant-scoped uniqueness and idempotency constraints plus row-locking repository paths. Replay/conflict, isolation, immutability, rollback, correction history, close/reopen, and non-authoritative reconciliation behavior remain exercised by the accepted milestone verifiers.

After the gate passes, control room commits and pushes this freeze package, creates the annotated tag `track-b-m6-treasury-reconciliation-close-control-20260811`, verifies the remote tag, and updates the running implementation ledger.
