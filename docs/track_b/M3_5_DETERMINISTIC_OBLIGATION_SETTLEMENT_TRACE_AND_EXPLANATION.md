# M3.5 — Deterministic Obligation Settlement Trace and Explanation

## Outcome

M3.5 adds a tenant-scoped, read-only explanation service for a single
obligation. It reconstructs what was originally owed, how value was applied,
what was reversed, the state at a current or historical cutoff, and what
supporting financial-event and journal evidence shares the same correlation
identity.

No schema, writer, route, or outbox behavior changes. The canonical Alembic
head remains `m34_obligation_aging_010`.

## Authority boundary

The obligation, line, allocation, reversal, value-source, and lifecycle rows
are authoritative persisted facts connected by governed keys. Financial events
and journals selected only by correlation identity are supporting evidence.
Their presence is useful, but correlation alone is not represented as proven
causation.

The trace itself is derived. It acquires no locks, commits no transaction,
updates no projection, and exposes no internal database identifiers.

## Current and historical answers

A current query supplies tenant and obligation public identity. A historical
query additionally supplies both a timezone-aware timestamp and a business
date. The pair prevents the technical clock and business calendar from being
silently conflated.

The balance is reconstructed as:

`outstanding = original - allocations at cutoff + reversals at cutoff`

Lifecycle state is the final append-only transition at the same cutoff.

## Integrity checks

Each result states whether:

- evidence remained tenant-scoped;
- obligation lines sum to the original amount;
- lifecycle history exists;
- active satisfaction and outstanding value are nonnegative;
- reversals remain within their allocation facts; and
- every correlated journal included in the result is balanced.

An empty correlation-evidence set is valid. It does not weaken the authoritative
obligation/allocation lineage and is reported plainly rather than invented.

## Acceptance strategy

The installer supplies one fail-fast acceptance command. It validates the
contract, compiles the implementation, confirms the unchanged migration head,
runs contract and regression tests, proves the development database is still
empty, and performs a disposable current/as-of rehearsal. If that gate fails,
the failing command is printed and only then should the segmented diagnostic
commands be used.
