# M7.5 — Finance migration support conformance and freeze

M7.5 freezes the accepted M7.0–M7.4 finance-facing WND migration-support
authority at canonical head `m64_reconciliation_controls_020`.

The package validates the semantic digests of every M7 component, replays each
read-only verifier, confirms the development financial state remains empty, and
freezes the adapter boundary. It creates no Alembic revision and performs no
production write, writer reroute, writer disablement, retirement, or cutover.

The frozen M7 boundary is:

- M7.0 inventories legacy financial authority and defines the adapter boundary;
- M7.1 maps commercial, payment, receivable, allowance, and refund facts;
- M7.2 maps verified inventory cost and preserves financial-document identity;
- M7.3 rehearses shadow execution and deterministic control totals in isolation;
- M7.4 provides dual-read comparison, advisory readiness, and reversible writer-retirement support;
- R6 alone owns live WND operational migration and production cutover.

After the single gate passes, commit and push the freeze package, create and
push the annotated M7 release tag, verify it remotely, and update the running
implementation ledger. M8 remains responsible for Track B global hardening and
approved exit.
