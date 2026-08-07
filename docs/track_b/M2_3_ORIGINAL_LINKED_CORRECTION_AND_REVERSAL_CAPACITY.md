# M2.3 — Original-Linked Correction and Reversal Capacity

**Status:** approved implementation candidate

**Date:** 7 August 2026

**Parent:** M2.2 at `8056fbb`

**Parent migration:** `m22_transactional_delivery_004`

**New migration:** `m23_reversal_capacity_005`

## Decision

Every financial correction remains a new immutable fact linked directly to one
original event. The original is never edited. Across every committed direct
correction, the cumulative corrected amount may not exceed the original
amount.

M2.3 applies this rule to all four catalog types that require an original:

- `COMMERCIAL_RETURN_RECOGNIZED` corrects
  `COMMERCIAL_REVENUE_RECOGNIZED`;
- `PAYMENT_SETTLEMENT_REVERSED` corrects `PAYMENT_SETTLED`;
- `PAYMENT_ALLOCATION_REVERSED` corrects `PAYMENT_ALLOCATED`;
- `FINANCIAL_FACT_REVERSED` corrects a posting-eligible event only when no
  dedicated correction type exists.

## Capacity invariant

For one `(tenant_id, original_event_id)`:

```text
sum(committed direct correction amounts) + requested amount
    <= original event amount
```

Partial corrections and an exact final correction are valid. Any amount above
remaining capacity is rejected. Remaining capacity is derived and never stored
as mutable authority.

Corrections cannot be chained: a correction cannot itself become an original.
Undoing a mistaken correction therefore requires an explicitly designed future
policy rather than an uncontrolled correction-of-correction chain.

## Type and lineage controls

The correction and original must share tenant, organization unit, and currency.
The correction timestamp cannot precede the original event. Dedicated
correction types must match their designated original type.

Generic reversals are intentionally narrower than “reverse anything.” They
require a posting-eligible original and are rejected when a dedicated
commercial-return, settlement-reversal, or allocation-reversal type exists.

For `inverse_original` catalog modes, operational accounts must exactly swap
sides:

```text
correction.source_account = original.target_account
correction.target_account = original.source_account
```

Commercial returns and allocation reversals permit no operational accounts, as
already specified by the catalog.

## Concurrency

The application selects the original financial event `FOR UPDATE`, then sums
existing direct corrections. The original row is the serialization key.
Concurrent correction attempts therefore cannot both calculate against stale
capacity under `READ COMMITTED`.

The lock remains held until the caller commits or rolls back the M2.2 outer
transaction. Idempotency reservation, correction event, and outbox message
remain one atomic unit.

## Defense in depth

`FinancialEventReversalPolicy.validate_and_lock` provides typed failure codes
before insertion. Migration `m23_reversal_capacity_005` installs a
`BEFORE INSERT` database trigger that independently locks the original and
enforces the same type, lineage, account, chain, and capacity invariants.

This second guard is essential: direct SQL, a future adapter bug, or a new
application service cannot bypass financial capacity simply by omitting the
policy call.

## Verification

The disposable verifier proves:

- fresh upgrade, downgrade, and re-upgrade;
- a partial correction followed by an exact-capacity correction;
- stable idempotent replay of a correction;
- rejection of sequential over-capacity correction;
- rejection of a dedicated type mismatch;
- rejection of a correction chain;
- serialization of concurrent 700 and 400 corrections against an original of
  1000, with only 700 committed;
- rejection of a direct SQL over-capacity insert;
- atomic final counts across idempotency, event, and outbox tables.

## Deferred

M2.3 does not implement refund capacity across settlements and allocations,
formal journal reversal entries, taxonomy bridges, outbox dispatch, WND writer
cutover, or historical transformation. These remain separate controlled
slices.
