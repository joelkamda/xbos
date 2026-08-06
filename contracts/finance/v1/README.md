# XBOS Finance Contract v1

This directory contains machine-readable, database-independent contracts for the neutral XBOS financial kernel.

The event catalog remains semantic version `1`. Contract revision `2` adds integration-boundary requirements discovered while testing the approved model; it does not add or rename financial event types.

## Authority

The contract implements the approved Track B B2 design set at tag:

```text
track-b-b2-canonical-model-20260805
```

The current WND implementation is discovery and historical-transformation evidence. Its API names, table names and combined financial behaviors are not compatibility requirements for this contract.

## Files

### `financial_event_catalog.json`

Defines the twenty approved canonical financial-event types and their version-one semantics:

- amount policy;
- allowed economic roles;
- posting eligibility;
- original-event requirements;
- required classification roles;
- allowed authoritative source-record kinds;
- operational-account requirements;
- reconciliation policy;
- posting profiles expressed through account roles.

It also defines:

- the universal immutable financial-event envelope;
- external settlement evidence requirements;
- the distinction between payment method, rail, orchestrator, provider account and operational account;
- the boundary between financial settlement and order/fulfillment workflow.

### `tests/contracts/test_financial_event_catalog.py`

Validates the catalog with Python's standard library and pytest. It does not import the XBOS application, read `.env` or connect to PostgreSQL.

## Reconciliation-policy refinement

The B2 physical blueprint summarized reconciliation effect as one scalar catalog field. Executable translation showed that a scalar is insufficient for events whose effect depends on direction or evidence.

Version one therefore uses a typed `reconciliation_policy` object with one of four modes:

| Mode | Meaning |
|---|---|
| `fixed` | One declared effect applies to the event type |
| `by_economic_role` | Effect is selected by the event's allowed economic role |
| `classification_dependent` | Effect is selected by a governed classification |
| `inverse_original` | Effect exactly reverses the linked original event |

This is a physical-schema refinement, not a change to approved financial meaning. When the catalog is implemented in PostgreSQL, `financial_event_type_versions` must store the complete policy, not force direction-dependent events into a false scalar effect.

## External payment and fulfillment boundary

An authenticated provider callback is evidence, not a financial event. A successful payment attempt is not automatically a final settlement. `PAYMENT_SETTLED` may be created only after provider evidence and finality are verified by the canonical settlement authority.

For externally initiated commerce—including WhatsApp, web, mobile, kiosk or partner channels—the payment path is:

```text
provider evidence
-> verified settlement
-> allocation
-> configured confirmation policy satisfied
-> commercial transaction confirmed
-> fulfillment requested through the transactional outbox
```

Order confirmation and fulfillment requests are workflow events. They are intentionally excluded from the financial-event catalog.

The catalog does not hard-code XafPay. XafPay can be recorded as the orchestrator while MTN, Orange, card or bank remains the payment rail and the tenant's XafPay merchant account remains a separately configured provider account.

## Posting profiles

Posting profiles contain account roles, not tenant ledger-account identifiers. Tenant, country and industry-pack configuration later resolves roles to versioned ledger accounts.

The executable catalog does not post journals and does not authorize schema or runtime changes.
