# XBOS Track B — M2.6 Deterministic Financial Trace and Explanation

## Outcome

M2.6 adds a read-only explanation boundary over the canonical financial event
engine. Given an authenticated tenant scope and a financial-event public UUID,
the service returns one deterministic trace from operational source through
idempotency, outbox delivery, posting, dimensions and corrections.

M2.6 does not add a table or migration. The canonical Alembic head remains
`m25_financial_dimensions_007`.

## Why this boundary exists

The kernel must be able to answer five questions without reconstructing truth
from mutable application screens:

1. What financial fact was recorded?
2. Which operational record caused it?
3. How was duplicate execution contained and delivery represented?
4. Which accounts and immutable dimension snapshots received the posting?
5. Which original or correcting facts belong to the same lineage?

The trace is derived. It does not become a second financial authority and it
cannot update any authoritative row.

## Query boundary

`FinancialEventTraceQuery` requires both `tenant_id` and `event_public_id`.
Every repository statement contains the tenant predicate. A missing event and
an event owned by another tenant produce the same not-found result.

At an eventual HTTP boundary, `tenant_id` must be supplied by authenticated
authorization context—not accepted as an untrusted request-body choice. HTTP
routing and RBAC policy are intentionally deferred until the neutral query
service is frozen.

## Returned sections

- `event`: approved catalog definition plus immutable event snapshots.
- `source`: registered operational aggregate provenance.
- `idempotency`: command identity and terminal processing state.
- `outbox`: durable message identity and current delivery state.
- `posting`: primary journal, period, posted ledger accounts, roles, amounts and
  immutable line dimension snapshots.
- `correction_lineage`: ancestors, selected event and descendant corrections.
- `correlation_peers`: other events sharing the explicit correlation UUID.
- `integrity`: recomputed balance, cardinality and linkage checks.
- `explanation`: deterministic plain-language summaries derived from the above.

## Important honesty boundary

M2.4 persisted the resolved ledger account and account role on each journal
line, so M2.6 reports those as authoritative posting truth. It does not pretend
to reconstruct the exact historical role-binding configuration when that
binding row was not snapshotted on the journal line. M2.5 dimension snapshots
are persisted and are therefore reported exactly.

## Determinism

The trace contains no request-time `generated_at` value. UUIDs, decimals,
dates and timestamps use canonical representations. Keys are sorted before
SHA-256 hashing. Repeating the same query over unchanged authoritative records
therefore yields the same `trace_fingerprint`.

## Integrity behavior

The trace reports `PASS` only when:

- the catalog and source record resolve;
- idempotency is completed and an outbox message exists;
- primary-journal cardinality is valid;
- posting presence agrees with the catalog;
- transaction and base amounts balance when posting is required;
- correction lineage contains exactly one selected event; and
- any original-event link resolves to a public event identity.

A failed integrity report is diagnostic evidence. It never repairs, deletes or
rewrites an event, journal or message.

## M2.6 scope exclusions

This slice does not expose a public FastAPI route, generate prose with an AI
model, export reports, search across events, dispatch messages, switch WND
writers or create development financial records. Those boundaries require
separate authorization and release decisions.
