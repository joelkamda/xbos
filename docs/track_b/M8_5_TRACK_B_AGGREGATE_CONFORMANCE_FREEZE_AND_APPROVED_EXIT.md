# M8.5 Track B Aggregate Conformance, Freeze and Approved Exit

M8.5 adds no financial product capability and no schema revision. It closes Track B by validating the accepted M2–M7 release manifests, the M8.0–M8.4 hardening contracts, the single neutral migration lineage through `m64_reconciliation_controls_020`, the frozen M7 boundary, and the final Track B release manifest.

The gate reads `xbos_track_b_dev` without writing to it and requires it to remain at the canonical head with empty financial tables. A separate database is created from `template0`, migrated from the neutral baseline to head, checked for empty state, rehearsed across the safe M6.3/M6.4 downgrade boundary, and exercised with a composed scenario. That scenario proves posted event and journal trace, stable replay, explicit conflict, settlement reversal, obligation/value allocation, payment intent/attempt/settlement, reconciliation controls, tenant isolation, closed-period rejection and transaction rollback.

Selected accepted M8 proofs are then rerun using their own disposable environments: M8.0 concurrency/replay, M8.1 ordering/offline/authorization, M8.2 provider uncertainty and rollback, M8.3 backup/restore and recovery equivalence, and M8.4 pack conformance and hidden-writer detection. Each verifier owns and cleans its bounded artifacts after success. The M8.5 clean-replay database is likewise dropped only after a complete successful rehearsal.

Track B now owns the neutral financial event, posting, obligation, allocation, payment, settlement, lifecycle, treasury, reconciliation, close, recovery and pack-conformance authorities recorded by the accepted milestone contracts. Future modules consume these authorities through their public command/service boundaries; they do not write financial-owned tables directly.

This approved exit does not switch WND production authority. Writer routing remains unchanged, `cutover=NOT_AUTHORIZED`, `writer_retirement=NOT_EXECUTED`, and R6 remains the live cutover owner. Platform Core and Shared Operations may build their separately approved capabilities around the frozen financial spine without redefining its economic truth.

After local acceptance, the control room—not Work—reviews the exact staged scope, commits the final Track B baseline, pushes it, creates the annotated Track B financial-hardening-and-approved-exit tag, pushes that tag, and verifies it remotely.
