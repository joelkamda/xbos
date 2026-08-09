# M3.4 — Deterministic Obligation Aging and As-of Balances

## Outcome

M3.4 makes receivable aging reproducible. A query names both an aware cutoff
timestamp and an explicit business date. The same facts, cutoff, and versioned
bucket policy always produce the same rows and totals.

## Historical lifecycle authority

The current obligation row alone cannot answer what its state was yesterday.
M3.4 therefore adds append-only `obligation_state_transitions`. Database
triggers record creation and every state change, including direct SQL. Existing
rows receive a baseline transition during migration. Transition rows cannot be
updated or deleted.

## As-of balance

For each obligation existing at the cutoff:

`outstanding = original − allocations through cutoff + reversals through cutoff`

The query separately cuts off obligations, allocations, reversals, and state
transitions. Zero balances are omitted and negative capacity fails closed.
Terminal obligations are excluded by default but may be explicitly included
with their state at the cutoff.

## Business dates and buckets

Due timestamps are converted to dates using the obligation organization’s
stored timezone. The caller supplies the reporting business date explicitly,
avoiding dependence on server-local “today.” Policy version 1 defines not due,
due today, 1–30, 31–60, 61–90, and 91+ past-due buckets.

## Boundaries

M3.4 adds no public route, mutable balance, saved report snapshot, collections
workflow, outbox dispatch, or WND writer cutover. Development data remains
empty; all behavioral proof uses one named disposable database.

## Next slice

M3.5 should add allocation-aware settlement and obligation trace explanations,
linking source value, allocation/reversal chains, as-of balances, lifecycle
history, and journal evidence into one deterministic read model.
