# M3.1 — Typed Obligation Lifecycle and Derived Balances

## Outcome

M3.1 activates the first application authority over the empty M3.0 obligation
foundation. It creates obligations and their explanatory lines atomically,
enforces command idempotency, governs terminal lifecycle transitions, and
derives outstanding value from immutable allocation facts.

No migration is introduced. The canonical head remains
`m30_obligation_foundation_008`.

## Creation authority

`CreateObligationCommand` is a framework-independent command containing tenant
and organization scope, opaque debtor and creditor Party references, original
amount and currency, due and business dates, actor and source context,
idempotency identity, and one or more immutable lines.

Before a transaction can write:

- money must be finite, positive, and no more precise than `NUMERIC(24,8)`;
- debtor and creditor must differ;
- currency and obligation type must use canonical codes;
- occurrence and due timestamps must be timezone-aware;
- due time cannot precede occurrence time;
- line numbers must be positive and unique;
- each line must satisfy `quantity × unit_amount = line_amount`; and
- the exact line sum must equal the obligation's original amount.

`TransactionalObligationEngine.create` reserves generic tenant-scoped
idempotency, inserts the obligation and every line, and completes the
reservation inside one savepoint. The caller owns the outer commit. Identical
replay returns the same obligation without new writes; changed content under
the same key fails with an idempotency conflict.

## Balance authority

There is no mutable balance column. `ObligationBalanceService` calculates:

`outstanding = original amount - allocations + allocation reversals`

Allocation reversals are pre-aggregated before allocation totals so multiple
reversals cannot multiply the original allocation in a join. Every lookup
requires tenant scope and returns not-found for another tenant. Negative active
satisfaction or negative outstanding value is treated as corrupt capacity and
fails closed.

## Lifecycle

Economic satisfaction states are projections:

- no active satisfaction → `open`;
- partial active satisfaction → `partially_satisfied`; and
- complete active satisfaction → `satisfied`.

`refresh_satisfaction_state` locks the obligation and increments its row
version only when the projected state changes.

Manual transitions are deliberately narrow:

- an unallocated open obligation may be cancelled;
- an open or partially satisfied obligation with positive outstanding value
  may be written off; and
- satisfied, cancelled, and written-off obligations are terminal.

Manual commands require an expected row version and their own idempotency
identity. They cannot manually assert a satisfaction state.

## Rehearsal and safety

The M3.1 verifier uses only
`xbos_track_b_m31_obligation_test`. It checks typed creation, stable replay,
changed-content conflict, exact line totals, open/partial/satisfied derived
balances, governed cancellation, tenant isolation, database immutability, outer
rollback, and empty development truth before and after the rehearsal. Failure
retains the named disposable database for inspection.

M3.1 does not authorize WND writer cutover. It does not activate allocation
commands, payment settlement, Party foreign keys, public routes, outbox
dispatch, cross-organization policy decisions, or development financial data.

## Next slice

M3.2 should implement allocation and reversal commands with deterministic lock
ordering, partial and split allocation, cumulative source and obligation
capacity, cross-organization policy evaluation, concurrency tests, and direct
SQL enforcement. It should call the M3.1 satisfaction projection only after an
allocation transaction has passed all capacity guards.
