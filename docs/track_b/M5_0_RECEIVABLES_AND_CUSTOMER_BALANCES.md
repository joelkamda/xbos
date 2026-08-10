# M5.0 — Receivables and Customer Balances

## Purpose

M5.0 closes the customer-side value lifecycle without introducing a parallel
ledger. It composes the canonical obligations, value sources, allocations,
allocation reversals, and deterministic aging authority delivered in M3.

This grouped package covers the original roadmap lines M5.0, M5.1, M5.2,
M5.5, and M5.6, plus overpayment and unapplied-value interoperability.

## Authority map

- A receivable is a `trade_receivable` or `customer_receivable` in
  `financial_obligations`.
- A payment, customer credit, deposit, or advance is immutable value in
  `value_sources`.
- Satisfaction is derived from `payment_allocations` less
  `allocation_reversals`.
- Open, partial, and satisfied states remain governed by the existing
  obligation engine and append-only state-transition history.
- Aging remains an as-of reconstruction from immutable facts.

No M5.0 migration is added. The canonical head remains
`m46_provider_financials_015`.

## Lifecycle semantics

Opening a receivable delegates to the typed obligation engine. Receiving a
payment creates one value source and applies it to one or more receivables in
the caller's transaction. A later receipt uses the same path. Value beyond the
target's outstanding amount stays unapplied and may later satisfy another
receivable belonging to the same customer and currency.

Customer credits, deposits, and advances are distinct value-source types.
They cannot claim payment-settlement identity. Applying any customer-held value
requires matching tenant, customer owner/debtor, and currency.

The customer financial position is derived as:

`net_customer_due = receivable_outstanding - customer_value_available`

The read model includes unapplied payment residuals, customer credits,
deposits, and advances. It never rewrites source facts.

## Acceptance

The single fail-fast gate proves:

- partial payment and later repayment;
- replay-safe receipt and application;
- overpayment residual and later application;
- customer credit, deposit, and advance issuance/application;
- deterministic receivable-only as-of aging;
- tenant, customer, organization, and currency boundaries;
- direct-SQL immutability and failed-command rollback;
- an unchanged canonical migration head;
- an empty development database before and after the disposable rehearsal;
- the full XBOS regression suite.

The disposable target is `xbos_track_b_m50_receivables_test`. It is dropped on
success and retained on failure for inspection.
