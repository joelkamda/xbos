# M5.4 Refunds, Corrections, and Loss Events

M5.4 completes the grouped corrective side of the financial lifecycle without adding schema. It uses the canonical event, posting, obligation, payment-settlement, and provider-financial authorities already approved through M4.6.

## Boundary

- Cancellation means abandoning a transaction before financial or final payment truth exists.
- Void means invalidating a non-final action before an irreversible external effect exists.
- Reversal means appending a linked financial correction; it never edits the original fact.
- Commercial returns use the catalog's dedicated return event. Generic reversal is reserved for event types without a dedicated correction type.
- Refund recognition requires a confirmed outgoing settlement and is capped by the active value of its confirmed incoming settlement.
- Chargebacks are provider loss adjustments. They do not rewrite the customer's gross settlement.
- A write-off must equal the exact outstanding obligation and atomically post and transition that obligation to `written_off`.

## Evidence and authority

Credit notes, correction notes, refund notices, reversal notices, chargeback notices, and write-off notices carry a bounded document number and lowercase SHA-256 evidence hash. The same document identity must be preserved by the authoritative source record (or provider component for chargebacks). Every lookup is tenant scoped and organization mismatches are rejected.

## Reliability

Financial operations use the established transactional idempotency, outbox, posting, original-link, and capacity controls. Replays return the completed result; changed payloads conflict; a failed paired write-off leaves no partial event, journal, outbox, or obligation transition.

## Acceptance

The disposable rehearsal proves disposition semantics, refund evidence and cumulative capacity, dedicated and generic reversals, provider chargeback delegation, receivable and payable write-offs, document preservation, tenant isolation, balanced posting, replay/conflict handling, rollback, and development-database emptiness. M5.4 intentionally creates no Alembic revision.
