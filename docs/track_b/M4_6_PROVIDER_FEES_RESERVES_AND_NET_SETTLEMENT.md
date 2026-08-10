# M4.6 — Provider fees, reserves, adjustments, and net settlement

M4.6 adds append-only provider-side economics without changing the confirmed customer-payment fact.

## Authority model

The confirmed `payment_settlements` row remains the gross customer-payment truth. A provider fee, reserve hold, reserve release, or chargeback loss is recorded as an immutable `provider_settlement_components` row linked to that settlement and provider account. Each governed component atomically produces:

1. a kernel source record;
2. an approved canonical financial event;
3. an outbox message; and
4. a balanced posted journal entry.

The component insert trigger requires the M4.6 engine authorization setting, locks the confirmed settlement, verifies tenant/organization/currency/provider/account scope, and enforces gross capacity. Updates and deletes are rejected.

## Component semantics

- `provider_fee` recognizes an evidenced provider charge using `PROVIDER_FEE_RECOGNIZED` and the `provider_fee` posting profile.
- `reserve_hold` records value retained by the provider using `provider_reserve_hold`.
- `reserve_release` must link the original hold. Cumulative releases cannot exceed that hold and use `provider_reserve_release`.
- `chargeback_loss` records a later evidenced provider adjustment using `provider_chargeback_loss`.

The deterministic provider position is:

`expected net = gross settlement - fees - active reserve holds - chargeback losses`

where active reserve holds equal holds less linked releases. This is a projection; it never rewrites `gross_amount`, `fee_amount`, or `net_amount` on the original settlement.

## Transaction and replay behavior

The component, source authority, event, outbox, and journal share the caller transaction. A rollback removes all of them. Identical idempotency replay resolves the existing component and event; changed content conflicts. Provider event references are unique within a tenant/provider account.

## Deferred scope

M4.6 does not dispatch outbox messages, call provider APIs, rewrite XafPay evidence, add public routes, or perform payout reconciliation. M4.7 freezes the complete M4 acceptance baseline.

## Acceptance evidence

`scripts/verify_m46_provider_financials.py create-and-verify` rehearses migration upgrade/downgrade/upgrade, fee/hold/release/chargeback flows, net projection, gross immutability, replay/conflict, capacity, tenant isolation, direct-SQL denial, balanced posting, and outer rollback in the named disposable database.
