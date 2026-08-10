# M5.2 — Commercial Terms, Taxes, and Fees

M5.2 groups the original discount, complimentary-value, service/provider-fee, and tax roadmap lines behind one atomic commercial-term boundary. It intentionally adds no migration and keeps the canonical head at `m46_provider_financials_015`.

## Financial meaning

The engine preserves gross sales and records each economic component separately:

`customer collectible = gross sales - discounts - complimentary value + customer service fees + output tax`

- Discounts reduce consideration through `DISCOUNT_GRANTED`.
- Complimentary value uses an explicit tenant policy: contra-revenue, promotion, or service recovery.
- A customer-facing service fee is commercial revenue, never a payment-provider charge.
- Output tax is a separately stated liability, not tenant revenue.
- Provider fees remain exclusively under the M4.6 provider-financial authority.

## Controls

Each component requires an existing tenant-scoped source record of the catalog-approved kind. The group is validated before any write and runs inside one savepoint. Canonical events, transactional outbox messages, and balanced journals therefore succeed or fail together. Replays use the frozen M2 idempotency authority.

The engine creates no alternate commercial tables and does not mutate upstream operational facts. Component events retain the gross and collectible amounts as immutable explanatory metadata.

## Acceptance

The disposable rehearsal proves the formula, all complimentary profiles, source-kind and tenant isolation, allowance capacity, provider-fee separation, replay/conflict handling, atomic rollback, balanced posting, and a clean development database. The full regression remains mandatory.
