# M8.0 — Global invariants, property tests, concurrency and replay

M8.0 is the first adversarial Track B hardening package. It adds no migration,
table, balance, ledger, writer route, or production behavior. Canonical head
remains `m64_reconciliation_controls_020`.

The package proves exact-decimal global invariants across the accepted finance
authorities using a deterministic seeded corpus. It covers balanced journals,
obligation/allocation capacity, allocation and settlement reversal capacity,
and bilateral value conservation for treasury transfers.

The disposable PostgreSQL rehearsal then drives the accepted M2 transactional
event/outbox authority from eight simultaneous sessions. Exactly one session
may create the event and outbox message; the other seven must resolve as stable
replays. A changed payload must fail closed, a rolled-back command must leave no
reservation or financial effect, and a cross-tenant source reference must be
rejected.

M8.0 deliberately does not absorb ordering/offline behavior, authorization,
provider/database outage testing, performance/recovery, pack conformance, or
the final Track B exit. Those remain M8.1–M8.5. R6 remains the sole authority
for live WND migration and production cutover.
