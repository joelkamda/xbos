# M3.3 — Deposits, Unapplied Value, and Overpayments

## Outcome

M3.3 composes the M3.2 value-source and allocation primitives into customer
receipt workflows. It introduces no migration: the canonical head remains
`m32_allocation_engine_009`.

A deposit or unidentified receipt is a value source with no allocation. An
overpayment is not a separate mutable balance. It is the remaining available
amount on a value source after applying up to an obligation's outstanding
amount. That residual can be applied later without rewriting the receipt.

## Derived balance

`ValueSourceBalanceService` calculates:

- active applied = allocations − allocation reversals; and
- available = source amount − active applied.

The resulting disposition is unapplied, partially applied, or fully applied.
Negative active or available amounts indicate corrupt capacity and fail closed.
Every lookup requires tenant scope.

## Typed workflows

`TransactionalValueApplicationEngine.receive` creates a value source and may
apply it in the same caller-owned transaction. With no applications, the whole
receipt remains unapplied. `apply_existing` later applies any remaining value.

Application instructions support:

- exact amount: the requested amount must fit all M3.2 capacities;
- up to outstanding: apply the lesser of source availability and obligation
  outstanding; and
- split application: one source may target several obligations atomically.

The batch processes obligations by sorted public ID. Each write delegates to
M3.2's idempotency → value-source → obligation lock order. M3.2 repeats
capacity and policy validation for every immutable allocation, and PostgreSQL
remains the final concurrency authority.

## Idempotency and corrections

The receipt and each allocation use the existing M3.2 tenant-scoped command
identities. Identical replay returns the same public facts; altered replay
conflicts. Allocation reversal reopens available value automatically because
balances are derived from the append-only fact chain.

## Boundaries

M3.3 adds no public API and does not switch WND writers. It does not create a
payment settlement, refund-disbursement workflow, Party authority, outbox
dispatcher, or development financial data.

## Next slice

M3.4 should add deterministic obligation aging and as-of balance reporting,
including due buckets, tenant/business-calendar context, and reproducible
historical snapshots derived from the immutable obligation and allocation
facts.
