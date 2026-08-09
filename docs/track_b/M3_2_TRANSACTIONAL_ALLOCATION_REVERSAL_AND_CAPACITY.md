# M3.2 — Transactional Allocation, Reversal, and Capacity

## Outcome

M3.2 turns the M3.0 allocation tables into governed write authority. Typed
commands create value sources, allocate them to obligations, and append
original-linked reversals. M3.1 remains the balance and satisfaction-state
projection authority.

In business terms, one payment may settle several obligations and one
obligation may be settled by several payments. Partial settlement is native.
Neither an incoming value source nor an obligation can be used beyond its
remaining amount, even under concurrent requests or direct SQL.

## Transaction and idempotency

All three commands reserve the shared tenant-scoped idempotency identity and
write their fact inside a savepoint. The caller owns the outer commit.
Identical replay returns the original public identity; altered content under
the same key conflicts. Rolling back the caller transaction removes the
reservation and every fact together.

Every writer locks in the same order: value source, obligation, then the
specific allocation when a reversal is involved. Application checks provide
clear errors. PostgreSQL triggers repeat the authoritative checks while the
aggregate locks are held, closing direct-SQL and concurrency bypasses.

## Capacity formulas

- source available = source amount − allocations + allocation reversals;
- obligation outstanding = original amount − allocations + reversals; and
- reversible amount = allocation amount − prior reversals.

Allocation and reversal rows remain immutable. Corrections are additional
facts. Once a guarded fact is inserted, the engine invokes the M3.1 balance
service and refreshes the obligation's derived open, partial, or satisfied
state in the same outer transaction.

## Cross-organization policy

Same-organization allocation must not claim a cross-organization policy.
Cross-organization allocation requires an exact active policy version matching
tenant, source organization, target organization, currency, and business date.
Policy rows are immutable. A new version is appended when governance changes.

## Safety boundary

M3.2 adds no public route and does not switch legacy WND writers. It does not
create payment settlements, Party authority, deposits, unapplied-value flows,
outbox dispatch, or development financial facts. Those remain later slices.

## Next slice

M3.3 may build deposit, unapplied-value, and overpayment workflows on these
capacity-safe primitives. It should preserve the immutable allocation facts,
explicit policy versioning, and caller-owned transaction boundary established
here.
