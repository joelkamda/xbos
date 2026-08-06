# XBOS M0 Canonical Posting Golden Contracts

**Record type:** Executable neutral-finance contract

**Workstream:** Track B-FIN — M0 Executable Neutral Contracts

**Contract version:** Finance v1, posting-scenario revision 1

**Status:** Approved baseline candidate

**Date:** 6 August 2026

## Purpose

This increment turns the approved canonical financial event vocabulary into
executable accounting examples. It does not implement the future persistence
model or mutate WND behavior. It establishes exact, testable expectations for
posting, balances, allocation and workflow gating before implementation begins.

The contracts answer four questions for each representative financial flow:

1. Which canonical events must occur, and in what order?
2. Which governed account roles must each event debit and credit?
3. What exact balances must result?
4. May the commercial workflow confirm and request fulfillment?

## Files

- `account_role_catalog.json` governs every abstract account role referenced by
  the canonical event catalog.
- `posting_scenarios.json` defines nine balanced golden scenarios, their role
  bindings, journal lines, ending balances and expected workflow state.
- `tests/contracts/test_financial_posting_scenarios.py` cross-checks both files
  against `financial_event_catalog.json` and proves the accounting outcomes.

## Golden scenarios

| Scenario | Contract proved |
|---|---|
| `FULLY_PAID_SALE` | Recognition, inbound settlement and receivable allocation |
| `PARTIAL_PAYMENT_RECEIVABLE` | Residual A/R and blocked full-payment workflow |
| `AR_REPAYMENT` | Later settlement and allocation without duplicate revenue |
| `FULLY_COMPLIMENTARY_TRANSACTION` | Non-cash consideration clearing without fake collection |
| `OVERPAYMENT_CUSTOMER_CREDIT` | Excess settlement recognized as a liability |
| `PARTIAL_REFUND` | Return, deallocation and outbound refund remain separate facts |
| `OPERATIONAL_VALUE_TRANSFER` | Asset-to-asset transfer creates neither income nor expense |
| `XAFPAY_EXTERNAL_ORDER_PAYMENT` | Provider evidence becomes canonical settlement before confirmation |
| `PROVIDER_FEE_AND_RESERVE_ADJUSTMENT` | Provider economics do not rewrite customer-payment truth |

## Accounting convention

Scenario account balances use a signed convention:

- debit balances are positive;
- credit balances are negative;
- debits increase the signed balance;
- credits decrease the signed balance.

Every posting event must balance independently. A scenario must also reproduce
its declared ending balances exactly from its opening balances and journal
lines. Non-posting control events, such as `OBLIGATION_OPENED`, have no journal
lines and cannot silently move value.

## Account-role neutrality

The account-role catalog contains abstract semantic roles rather than WND chart
of account IDs. Tenant, country and industry-pack configuration will later bind
these roles to real ledger accounts. This preserves a stable kernel contract
while allowing restaurants, hospitality businesses, retailers, service
businesses and future packs to configure different charts and classifications.

The executable test requires the account-role catalog to match the complete
role vocabulary used by the event catalog—no missing roles and no unexplained
extras.

## External payment and XafPay boundary

`XAFPAY_EXTERNAL_ORDER_PAYMENT` intentionally represents separate dimensions:

- payment method: `mobile_money`;
- payment rail: `mtn_mobile_money`;
- orchestrator: `xafpay`;
- provider account: the integration credential/configuration boundary;
- operational account: the financial custody/reconciliation boundary.

XafPay is therefore one pluggable orchestrator, not a kernel synonym for all
external payments. Other orchestrators, gateways and direct providers can be
added by configuration and adapters while producing the same canonical events.

The scenario also fixes the workflow boundary:

1. provider evidence is authenticated and deduplicated;
2. the payment reaches configured finality;
3. XBOS records canonical `PAYMENT_SETTLED`;
4. XBOS records `PAYMENT_ALLOCATED` against the obligation;
5. the commercial confirmation policy is evaluated;
6. fulfillment is requested through a transactional outbox.

A raw provider success callback is explicitly not the order-confirmation
trigger. That distinction protects the system from duplicate callbacks,
premature fulfillment and provider-specific business logic.

## Running the contracts

From the XBOS repository root:

```bash
python -m py_compile tests/contracts/test_financial_posting_scenarios.py
python -m pytest tests/contracts/test_financial_posting_scenarios.py -q
python -m pytest -q
git diff --check
```

The contract test is database-free. The full suite may still require the local
PostgreSQL test database because the characterization tests are integration
tests.

## Scope boundary

This increment approves vocabulary and expected outcomes. It does not yet:

- create canonical financial database tables;
- implement a posting engine;
- implement provider adapters or webhook ingestion;
- replace current settlement code;
- migrate WND data;
- introduce tenant chart-of-account bindings;
- dispatch real fulfillment messages.

Those implementation slices must conform to these contracts rather than alter
them opportunistically. A deliberate contract revision is required when an
approved accounting meaning changes.
