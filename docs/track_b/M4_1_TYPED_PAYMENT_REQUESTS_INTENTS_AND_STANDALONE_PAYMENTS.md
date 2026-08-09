# M4.1 â€” Typed Payment Requests, Intents, and Standalone Payments

## Outcome

M4.1 activates the first write-capable application layer over the neutral M4.0 payment foundation. It accepts typed commands for canonical payment requests and payment intents while preserving the canonical migration head at `m40_payment_foundation_011`.

In plain language, XBOS can now record that value has been requested and that a payer intends to provide a specific amount. It still does not contact a payment provider, collect a tender, confirm settlement, or create accounting value.

## Command boundary

`CreatePaymentRequestCommand` records a tenant-scoped request for a positive amount and currency. `CreatePaymentIntentCommand` records one of three explicit origins:

- a canonical payment request;
- a financial obligation; or
- a standalone payment with no fabricated request or obligation.

Every command carries occurrence and business dates, calendar-policy authority, correlation, actor, source identity, metadata, and a tenant-scoped idempotency identity. Canonical SHA-256 fingerprints make semantically identical replays deterministic and distinguish conflicting content.

## Provider neutrality

The payment-method policy contains only `allowed_methods`, `allow_mixed_tender`, and `max_tenders`. Provider, rail, orchestrator, and provider-account configuration is rejected at this layer. Method execution belongs to later M4 capabilities.

## Transactional guarantees

- The shared `idempotency_records` table is reserved in the same transaction as the domain write.
- A completed replay returns the original canonical record.
- Reusing the same identity with different command content is rejected.
- A failed command rolls back both its domain write and its idempotency reservation.
- Payment-request capacity is calculated while the request row is locked.
- Obligation-linked intent amount cannot exceed the current obligation outstanding amount.
- Tenant, organization, currency, lifecycle, and expiry mismatches are rejected.

## Deliberately deferred

M4.1 creates no tenders, attempts, callback events, settlements, reversals, value sources, financial events, or outbox messages. It adds no public route, calls no provider adapter, and does not switch any WND writer.

## Verification

The development verifier is read-only and requires `xbos_track_b_dev` at `m40_payment_foundation_011` with the M4 foundation and downstream side-effect tables empty.

The disposable rehearsal clones that empty canonical development target, then proves request creation, linked and standalone intents, replay, conflict rejection, cumulative request capacity, tenant isolation, rollback cleanliness, exact atomic counts, and zero downstream side effects. The clone is dropped on success and retained on failure.

## Next-step considerations

M4.2 may introduce governed tender composition and intent lifecycle transitions. It should continue using the M4.1 command fingerprints and idempotency authority, keep provider-specific execution behind an adapter boundary, and preserve the distinction between intent, attempted collection, confirmed settlement, and created value.
