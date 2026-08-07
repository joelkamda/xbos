# M2.2 — Transactional Idempotency and Outbox

**Status:** approved implementation candidate

**Date:** 7 August 2026

**Parent:** M2.1 at `6acd76c`

**Parent migration:** `m20_event_catalog_003`

**New migration:** `m22_transactional_delivery_004`

## Decision

M2.2 makes one canonical financial-event command a single database unit:

1. reserve the command identity in `idempotency_records`;
2. append one immutable `financial_events` fact;
3. append one immutable, pending `outbox_messages` envelope;
4. complete the idempotency record with both stable public IDs;
5. leave commit or rollback to the caller.

The engine does not publish to a broker and does not commit. If the caller rolls
back, all three writes disappear. An internal savepoint also prevents a caller
that translates a validation error from accidentally committing a stranded
`processing` reservation.

## Why the migration is required

The empty M1 physical foundation predated the approved executable reliability
contract in two details:

- its coarse idempotency check allowed `failed` and `expired`; the approved
  states are `processing`, `completed`, `failed_retryable`, and
  `failed_terminal`;
- its outbox payload could hold the approved envelope, but the logical identity
  `(tenant_id, topic, message_key)` and organization/time dimensions were not
  first-class constrained columns.

M2.2 aligns those details before production writers exist. No historical rows
are rewritten.

## Compatibility boundary

`CanonicalFinancialEventEngine` from M2.1 is deliberately unchanged so the
M2.1 contract remains executable. New callers use:

```python
TransactionalCanonicalFinancialEventEngine.emit(session, command)
```

The return value contains the financial event, outbox message, completed
idempotency record, and replay flag. WND writers remain untouched in M2.2.

## Idempotency decisions

Identity is `(tenant_id, idempotency_scope, idempotency_key)`. The request
fingerprint is the M2.1 SHA-256 canonical command fingerprint.

- Absent identity: reserve `processing`, execute, complete atomically.
- Completed plus same fingerprint: return the same event and message IDs; add
  no row.
- Same identity plus different fingerprint: raise `idempotency_conflict`.
- Processing plus same fingerprint: return `idempotency_in_progress` under the
  bounded lease rule.
- Retryable or terminal failure states are recognized, but retry authorization
  is deferred. M2.2 does not invent an automatic retry policy.

The repository inserts through a savepoint and locks the winning row after a
uniqueness race. It never rolls back the caller's outer transaction.

## Outbox envelope

Every financial event gets one message on topic
`finance.financial-events.v1`. The event public ID is the message key. The
canonical JSON envelope contains:

- message, tenant, organization-unit, topic, and message-key identity;
- event type and version;
- correlation and causation;
- occurred and recorded timestamps;
- a versioned financial-event payload.

`payload_hash` is SHA-256 over canonical JSON bytes. Content and identity are
immutable; delivery state, lease, attempts, and error details remain mutable.
The database now rejects deletes as well as content-changing updates.

## Transaction and failure semantics

The caller owns the transaction. There is no internal commit, broker request,
HTTP request, or WND side effect. A command is externally observable only after
the caller commits. Publishing before commit is structurally absent.

The disposable verifier proves:

- fresh upgrade, downgrade, and re-upgrade;
- one command yields exactly one idempotency row, event, and outbox row;
- identical replay keeps both public IDs and all counts stable;
- altered replay conflicts;
- forced outer rollback leaves none of the three writes;
- cross-tenant references leave no reservation;
- payload hash and required envelope are exact;
- outbox content is immutable while delivery state may advance.

## Explicitly deferred

- broker dispatcher, claims, retry scheduling, and acknowledgements;
- consumer inbox/deduplication;
- provider inbox and callback authentication;
- authorized resumption from `failed_retryable`;
- reversal-capacity aggregation;
- WND writer cutover and historical transformation.

These belong to later M2/M3 slices and must not be smuggled into this atomic
persistence boundary.
