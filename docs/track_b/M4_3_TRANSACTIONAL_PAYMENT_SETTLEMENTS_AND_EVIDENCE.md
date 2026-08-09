# M4.3 — Transactional payment settlements and evidence

M4.3 activates the settlement tables installed structurally in M4.0. It does not add payment-method adapters, mixed tender orchestration, XafPay behavior, fees/reserves accounting, public routes, or downstream financial posting.

## Authority boundary

A payment attempt records an effort to move value. A settlement records when value is recognized against an operational financial account. External rails require a matching successful attempt; cash and internal credit are explicitly permitted without provider-attempt authority.

Every settlement begins `pending`. A governed command may move it to `confirmed` or `failed`. Reversal facts subsequently move confirmed value to `partially_reversed` or `reversed`. State evidence is append-only and sequence-controlled.

## Time and identity

- `occurred_at` is the business occurrence timestamp.
- `value_date` is the provider or cash value-effective date.
- `recorded_at` is the kernel persistence timestamp.
- External confirmation requires an immutable provider transaction identity.

These facts are intentionally distinct so delayed settlement and provider reporting cannot rewrite transaction history.

## Reversal capacity

Settlement reversals are compensating facts. Their cumulative amount cannot exceed the original gross settlement amount. Database triggers enforce capacity, state transitions, immutable monetary truth, and transition evidence even when application services are bypassed.

## Side-effect boundary

M4.3 creates no value source, allocation, financial event, journal entry, journal line, or outbox message. Later milestones will connect confirmed settlement truth to payment patterns and orchestration without weakening this boundary.

## Acceptance

The disposable rehearsal proves inbound settlement, outgoing cash settlement, confirmed and failed evidence, provider identity, distinct value and recorded dates, replay/conflict behavior, tenant isolation, partial/full reversal, over-capacity rejection, append-only evidence, direct-SQL guards, and upgrade/downgrade/upgrade safety.
