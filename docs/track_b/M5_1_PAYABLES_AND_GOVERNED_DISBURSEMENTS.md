# M5.1 — Payables and Governed Disbursements

## Purpose

M5.1 closes the supplier-side obligation lifecycle by composing the existing
obligation, settlement, value-source, and allocation authorities. It covers
the original roadmap items M5.3 (payable lifecycle) and M5.4 (disbursements).

No parallel ledger or migration is added. The canonical head remains
`m46_provider_financials_015`.

## Authority

- A payable is a `trade_payable`, `supplier_payable`, or `expense_payable` in
  `financial_obligations`.
- Cash movement authority is a confirmed outgoing `payment_settlement`.
- The corresponding `disbursement` value source must reference that settlement
  and equal its active gross amount.
- Satisfaction remains the sum of immutable allocations less reversals.
- Supplier balances are derived; they are never stored or edited in place.

## Payer and payee identity

The value-source owner is the payer and must equal every target payable's
debtor. Immutable value-source metadata records `payee_party_id`, which must
equal every target payable's creditor. This permits a single disbursement to
satisfy several obligations for one supplier while preventing residual value
from being redirected to another supplier.

Tenant, organization, currency, payer, and payee must all match. Pending,
failed, incoming, reversed, wrong-amount, or cross-supplier settlements are not
valid disbursement authority.

## Acceptance

The single fail-fast gate proves:

- payable creation, partial satisfaction, later satisfaction, and replay;
- one disbursement applied across multiple payables for one supplier;
- confirmed outgoing settlement authority and amount matching;
- rejection of pending and failed settlements;
- payer, payee, tenant, organization, currency, and capacity boundaries;
- derived supplier balances;
- rollback of rejected commands and direct-SQL immutability;
- an unchanged canonical migration head;
- an empty development database before and after the disposable rehearsal;
- the full XBOS regression suite.

The disposable database is `xbos_track_b_m51_payables_test`. It is dropped on
success and retained on failure for inspection.
