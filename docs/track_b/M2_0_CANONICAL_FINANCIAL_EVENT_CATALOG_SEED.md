# XBOS Neutral Operating Kernel — M2.0 Canonical Financial Event Catalog Seed

**Record type:** Implementation and verification record

**Workstream:** Track B-FIN — Neutral Financial Spine

**Milestone:** M2 — Canonical Event Engine

**Slice:** M2.0 — Approved catalog seed

**Status:** Implementation candidate

**Date:** 6 August 2026

**Parent checkpoint:** `track-b-m1-canonical-persistence-20260806` at `8f8d973`

## 1. Outcome

M2.0 installs the twenty approved version-one financial event definitions into
the empty canonical persistence foundation. Each database row is derived from
the complete M0 event definition, carries a deterministic SHA-256 definition
hash, retains the full executable policy document, and remains immutable.

This slice seeds vocabulary and policy only. It does not emit financial facts,
write outbox messages, switch WND writers, or transform historical records.

## 2. Authority

The normative source is:

```text
contracts/finance/v1/financial_event_catalog.json
catalog_code       XBOS_CANONICAL_FINANCIAL_EVENTS
catalog_version    1
contract_revision  2
semantic_sha256    079cc4c6743c400bc6eb94302a1bf87f1211b8cde70c594043c8b9d15086487c
```

The migration refuses to seed if any catalog value changes without a new
approved contract and migration.

## 3. Installed event definitions

1. `COMMERCIAL_REVENUE_RECOGNIZED`
2. `TAX_LIABILITY_RECOGNIZED`
3. `DISCOUNT_GRANTED`
4. `COMPLIMENTARY_GRANTED`
5. `TIP_RECOGNIZED`
6. `COMMERCIAL_RETURN_RECOGNIZED`
7. `COST_OF_FULFILLMENT_RECOGNIZED`
8. `EXPENSE_RECOGNIZED`
9. `OBLIGATION_OPENED`
10. `OBLIGATION_WRITTEN_OFF`
11. `PAYMENT_SETTLED`
12. `PAYMENT_SETTLEMENT_REVERSED`
13. `PAYMENT_ALLOCATED`
14. `PAYMENT_ALLOCATION_REVERSED`
15. `CUSTOMER_CREDIT_RECOGNIZED`
16. `REFUND_SETTLED`
17. `VALUE_TRANSFERRED`
18. `PROVIDER_FEE_RECOGNIZED`
19. `PROVIDER_SETTLEMENT_ADJUSTED`
20. `FINANCIAL_FACT_REVERSED`

## 4. Definition hashing

Each event definition is canonicalized using:

```text
UTF-8
JSON keys sorted
compact separators
Unicode retained rather than ASCII-escaped
```

The SHA-256 digest of those bytes becomes `definition_hash`. The hash covers
the complete event item, including source-record restrictions,
classifications, account policy, reconciliation policy, and posting profiles.

The full source event definition is also stored in `metadata.event_definition`.
This makes the installed meaning independently inspectable and permits exact
database-to-contract verification.

## 5. Reconciliation vocabulary alignment

M1 intentionally created empty structural tables. Its original constraint used
the earlier coarse physical vocabulary. M0 later froze the executable set:

```text
inflow
outflow
movement
control_increase
control_decrease
control_reversal
commercial
account_adjustment
none
```

M2.0 replaces the empty-table constraint before inserting the catalog. This is
not a data conversion because the table is empty at the M1 exit gate.

For fixed policies, `reconciliation_effect` stores the exact approved effect.
For `PAYMENT_SETTLED`, it stores the effect of the default economic role while
retaining the complete role mapping. Policies resolved from an original event
or an event classification store `none` as their static default and retain the
complete dynamic policy for M2.1 event-time resolution.

## 6. Migration behavior

The canonical lineage becomes:

```text
m13_source_state_001
    -> m13_financial_foundation_002
    -> m20_event_catalog_003
```

Upgrade performs these operations in one transaction:

1. validate the catalog identity, approval state, event count, vocabulary, and
   semantic fingerprint;
2. align the reconciliation constraint with M0;
3. derive deterministic seed rows;
4. reject a conflicting pre-existing type/version identity;
5. insert exactly twenty immutable catalog rows.

Downgrade removes only the twenty known seed identities and restores the M1
constraint. PostgreSQL foreign keys prevent downgrade once a financial event
references a definition, which is the intended safety boundary.

## 7. Verification

The verifier proves:

- fresh canonical reconstruction reaches the M2.0 head;
- exactly twenty rows exist;
- every identity, definition, policy, metadata document, and hash matches M0;
- the approved reconciliation vocabulary is enforced;
- catalog updates are rejected by the immutable trigger;
- no financial event or outbox message is created;
- downgrade returns to M1 with zero catalog rows;
- a second upgrade reproduces the exact same result;
- the disposable rehearsal database is removed after success.

## 8. Safety boundary

M2.0 does not:

- call WND settlement, accounting, reconciliation, or inventory services;
- change existing WND tables or rows;
- expose a new API;
- accept provider callbacks;
- create accounting journals;
- create financial facts;
- create fulfillment commands;
- backfill historical data.

## 9. Next slice

M2.1 implements typed canonical event commands and builders. It will validate
the event envelope, source record, account policy, classification requirements,
actor, tenant scope, currency, and reversal relationship before performing one
immutable insertion. It remains isolated from WND transaction writers until a
later approved cutover.
