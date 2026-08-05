# XBOS Track B-FIN — B2 Canonical Financial Authority Map and Legacy Disposition

**Record type:** Architecture and financial-authority decision draft
**Workstream:** Track B-FIN — Neutral Financial Spine
**Phase:** B2 — Canonical Financial Vocabulary and Target Model
**Status:** Approved architecture decision
**Date:** 5 August 2026
**B1 baseline:** `track-b-b1-characterization-20260804` at `56e3b19`
**B2 branch:** `track-b/b2-canonical-financial-model`

---

## 1. Purpose

This record identifies which XBOS concepts should own operational, commercial, payment, obligation, financial-event, accounting, and reconciliation truth.

It documents:

- current tables and write paths;
- duplicated and competing balances;
- the proposed canonical authority chain;
- the intended disposition of legacy fields and tables;
- required invariants and integrity rules;
- compatibility and migration principles;
- open decisions that must be resolved before implementation.

This is a design record. It authorizes no production-data changes, migrations, or behavioral refactoring by itself.

---

## 2. Evidence base

The authority analysis is based on:

- the B1 characterization suite;
- the parity database schema;
- PostgreSQL constraints and indexes;
- current model constructors;
- current balance/status mutation paths;
- POS settlement behavior;
- A/R repayment behavior;
- treasury-event emission;
- reconciliation persistence behavior.

The relevant current tables are:

```text
orders
order_items
sales
sale_items
payment_intents
payment_attempts
payments
accounts_receivable
accounts_receivable_repayments
treasury_logs
recon_sheets
inventory_items
inventory_movements
```

The current financial writers are substantially centralized:

| Record | Current creation/write path |
|---|---|
| PaymentIntent | `PaymentService` and `PaymentIntentRepository` |
| PaymentAttempt | `PaymentService` and `PaymentAttemptRepository` |
| AccountsReceivable | `AccountsReceivableService` |
| AccountsReceivableRepayment | `AccountsReceivableService` |
| TreasuryLog | `FinancialEventEmitter` → `TreasuryRepository.record()` |
| Reconciliation draft | `AccountingController` → `TreasuryRepository.upsert_reconciliation_rows()` |
| Reconciliation close | Direct SQL in `accounting_router.py` |

---

## 3. Executive authority decision

XBOS should use the following logical authority chain:

```text
Domain operation
    ↓
Commercial transaction and charge snapshot
    ↓
Financial obligation
    ↓
Payment intent
    ↓
Payment attempt
    ↓
Settlement
    ↓
Payment allocation
    ↓
Financial event
    ↓
Journal posting
    ↓
Reconciliation control
```

Each layer answers a different question:

| Layer | Authoritative question |
|---|---|
| Domain operation | What operational activity was requested and fulfilled? |
| Commercial transaction | What goods/services, quantities, prices and adjustments were commercially recognized? |
| Obligation | Who owes whom, how much, in which currency, and by when? |
| Payment intent | What collection or disbursement is being orchestrated? |
| Payment attempt | What tender/provider operation was attempted? |
| Settlement | What money movement was confirmed and is available? |
| Allocation | Which obligation did the settled value satisfy? |
| Financial event | What immutable economic fact occurred? |
| Journal posting | How is the economic fact represented in formal accounts? |
| Reconciliation | Does expected channel movement agree with controlled actuals? |

No record should silently answer two of these questions when doing so creates competing financial truth.

---

## 4. Canonical concepts

### 4.1 Domain operation

A pack-owned aggregate representing operational work.

Examples:

- Restaurant order;
- hotel reservation or stay;
- retail checkout;
- service engagement;
- delivery;
- healthcare encounter.

The domain aggregate owns operational state and fulfillment. It does not own payment settlement or accounting truth.

### 4.2 Commercial transaction

An immutable or controlled commercial snapshot of what was sold, returned, cancelled, or adjusted.

It records:

- tenant and operating location;
- customer/Party when known;
- lines and Atomic Unit snapshots;
- quantity and unit of measure;
- gross amount;
- taxes;
- discounts and complimentary allowances;
- fees, service charges and tips where applicable;
- net commercial amount;
- currency;
- commercial timestamps;
- responsible actors;
- originating domain reference.

Commercial transactions do not determine which payment method settled them.

### 4.3 Financial obligation

The canonical amount owed by one Party/account to another.

An obligation owns:

- creditor and debtor context;
- tenant and organization scope;
- source transaction/reference;
- original amount and currency;
- due date and payment terms where applicable;
- obligation type;
- lifecycle state;
- effective and recorded timestamps.

Outstanding balance is derived from valid allocations, reversals, write-offs and adjustments. A cached balance may exist for performance, but it is not independently editable truth.

Examples:

- sale payable immediately;
- hotel folio balance;
- customer invoice;
- accounts-receivable debt;
- supplier payable;
- deposit liability;
- refund payable to a customer.

### 4.4 Payment intent

The orchestration context for collecting or disbursing money.

It owns:

- requested amount and currency;
- payer/payee context when known;
- purpose and references;
- supported channels/methods;
- orchestration status;
- expiry and provider context;
- idempotent client reference.

It does not own the commercial obligation and it does not prove that money settled.

`total_paid` and `balance_due` may remain cached compatibility projections during migration, but their authoritative derivation is allocations against obligations.

### 4.5 Payment attempt

One try to perform a payment through a tender, provider or manual channel.

It owns:

- intent reference;
- method and provider;
- requested amount and currency;
- client/provider/callback references;
- attempt status;
- request and response evidence;
- timestamps and actor/device context.

An attempt is not automatically a settlement. In the current legacy system, a `succeeded` manual attempt also acts as settlement evidence. B2 must preserve this behavior through a compatibility rule while introducing the explicit target distinction.

### 4.6 Settlement

A confirmed movement of value through a payment channel or provider.

It owns:

- payment-attempt/provider relationship;
- settled amount and currency;
- settlement channel/account;
- provider settlement identity;
- settlement and availability timestamps;
- fees and net/gross settlement amounts where applicable;
- reversal/chargeback relationship;
- immutable provider evidence.

Manual cash settlement may be confirmed immediately. Asynchronous gateway settlement is confirmed only by an authenticated provider event or approved operator action.

### 4.7 Payment allocation

The missing canonical link between settled value and obligations.

It owns:

- settlement or available-funds source;
- obligation target;
- allocated amount and currency;
- allocation type;
- effective timestamp;
- actor/system reason;
- reversal/correction relationship;
- idempotency identity.

Allocations support:

- one payment to one obligation;
- one payment to many obligations;
- many payments to one obligation;
- partial settlement;
- deposits and unapplied funds;
- receivable repayment;
- mixed tenders;
- later allocation of standalone payments;
- refunds and reversals against original applications.

### 4.8 Financial event

An immutable economic fact used by treasury, reporting, reconciliation and accounting.

It owns:

- event type and version;
- amount, currency and direction/economic meaning;
- tenant and organization scope;
- source aggregate/reference;
- occurred and recorded timestamps;
- idempotency key;
- correlation and causation IDs;
- classification/accounting metadata;
- actor/service identity.

An idempotent replay returns the original event without mutating its historical evidence.

### 4.9 Journal posting

The formal accounting representation derived from approved financial events and posting rules.

It owns:

- journal entry and lines;
- debit/credit accounts;
- analytical dimensions;
- accounting period and posting date;
- source financial event;
- posting-rule version;
- reversal and adjustment relationships;
- approval and lock state.

Treasury events are not themselves a complete general ledger.

### 4.10 Reconciliation control

A persisted comparison between expected channel movements and controlled actual balances.

It owns:

- tenant, branch/property, shift/cycle, channel and window;
- opening control balance;
- expected movements derived from events;
- expected closing balance;
- actual counted/statement balance;
- variance, evidence, notes and approvals;
- close, reopen and correction state.

Reconciliation never rewrites the underlying commercial, settlement or event facts.

---

## 5. Current schema findings

### 5.1 Orders and order items

Current strengths:

- operational status and fulfillment are distinct from payment attempts;
- item name and price snapshots exist.

Current weaknesses:

- tenant and branch relationships are not database-enforced;
- `order_items.atomic_unit_id` lacks a foreign key;
- timestamps are naive;
- money and status invariants are not constrained.

Proposed authority:

```text
Operational request and fulfillment authority
```

### 5.2 Sales and sale items

Current strengths:

- commercial line snapshots exist;
- receipt number is unique by tenant and branch;
- one sale per non-null order is enforced.

Current weaknesses:

- `order_id` is unique but lacks a foreign key;
- `payment_method` cannot represent split or unpaid truth;
- `payment_summary` is untyped duplicated JSON;
- tendered, change and unpaid values duplicate payment/obligation state;
- status is unconstrained.

Proposed authority:

```text
Commercial transaction snapshot authority
```

Payment-related fields remain compatibility snapshots until consumers migrate.

### 5.3 Payment intents

Current strengths:

- tenant, branch, payable, currency and orchestration fields exist;
- intent creation is centralized;
- totals/status assignments use repository methods.

Current weaknesses:

- payable lookup is not unique;
- polymorphic payable references have no referential integrity;
- gateway intent identity is not unique;
- amount and balance invariants are not constrained;
- cached balances compete with A/R balances;
- JSON metadata repeats totals.

Proposed authority:

```text
Payment orchestration authority
```

Not obligation or allocation authority.

### 5.4 Payment attempts

Current strengths:

- positive amounts are constrained;
- attempt creation is centralized;
- succeeded-attempt sums are the practical basis of current POS and repayment totals;
- client and callback references have uniqueness protection.

Current weaknesses:

- client/callback uniqueness is global rather than explicitly tenant-scoped;
- callback uniqueness has overlapping indexes;
- gateway/provider references are non-unique;
- `sale_id` duplicates the intent payable link;
- currency is inherited rather than captured on the attempt;
- attempt success and settlement confirmation are conflated for manual flows.

Proposed authority:

```text
Tender/provider attempt authority
```

### 5.5 Legacy payments

Current weaknesses:

- substantially duplicates payment attempts;
- lacks tenant, branch, currency, idempotency and settlement-mode context;
- references and gateway IDs are not unique;
- contains minimal database integrity.

Proposed disposition:

```text
Compatibility-only legacy table, then retire
```

No new canonical behavior should be built on it.

### 5.6 Accounts receivable

Current strengths:

- provides current WND debt workflow and customer-facing balance;
- one receivable per non-null order is enforced;
- behavior is characterized.

Current weaknesses:

- payment-intent reference type mismatches the intent primary key;
- no currency, Party/customer ID, due date or payment terms;
- no foreign keys to order, sale, intent, tenant, branch or user;
- sale uniqueness is not protected;
- original, paid and balance values compete with intent state;
- timestamps are naive;
- monetary and status invariants are unconstrained.

Proposed disposition:

```text
Legacy A/R compatibility projection over canonical obligations and allocations
```

### 5.7 Accounts-receivable repayments

Current behavior creates:

- a legacy repayment row;
- a succeeded payment attempt;
- synchronized A/R totals;
- synchronized intent totals;
- a `DEBT_REPAYMENT` financial event;
- an idempotency record.

The service determines previous paid amount as the maximum of:

```text
accounts_receivable.paid_amount
payment_intents.total_paid
sum(succeeded payment attempts)
```

This prevents regression to a lower cached balance but masks divergence among competing authorities.

Proposed disposition:

```text
Compatibility repayment record linked to canonical settlement and allocation
```

### 5.8 Treasury logs

Current strengths:

- central emitter/repository path;
- tenant-scoped unique idempotency when a key exists;
- direction constraint;
- generic reference and event-time indexes;
- characterized event mappings.

Current weaknesses:

- idempotency key is nullable;
- specialized and generic references can disagree;
- references lack foreign keys;
- event types are unconstrained strings;
- no event version, correlation, causation or journal link;
- no positive-amount/currency integrity;
- replay currently may merge later metadata into the existing row.

Proposed authority:

```text
Legacy financial-event authority, to evolve behind a canonical event contract
```

### 5.9 Reconciliation sheets

Current strengths:

- correct unique identity for tenant, branch, shift, window and channel;
- opening, movements, expected, actual and variance are separated;
- draft and close persistence exist;
- behavior is characterized.

Current weaknesses:

- active close path uses direct SQL while controller/repository logic also exists;
- no constraint requires end after start;
- no status or arithmetic constraints;
- previous-close lookup omits shift;
- skipped middle windows are allowed;
- correcting a prior close does not cascade to persisted later openings.

Proposed authority:

```text
Reconciliation control-snapshot authority
```

All writes should move behind one reconciliation service/repository boundary.

---

## 6. Current balance algorithms

### 6.1 POS settlement

The ordinary POS flow currently calculates:

```text
cumulative tendered = sum(succeeded attempts for intent)
total paid          = min(net commercial total, cumulative tendered)
balance due         = max(0, net commercial total - total paid)
```

It then writes the calculated totals into:

- PaymentIntent columns;
- PaymentIntent metadata aliases;
- sale/payment receipt projections;
- A/R creation or status behavior when a balance remains.

### 6.2 A/R repayment

The repayment flow calculates:

```text
original amount = intent.amount, falling back to A/R original amount

previous paid = max(
    A/R paid amount,
    intent total paid,
    succeeded attempt sum
)

next paid    = min(original amount, max(previous paid + repayment, new attempt sum))
next balance = max(0, original amount - next paid)
```

It writes both A/R and intent aggregates.

### 6.3 Target calculation

The target calculation is:

```text
settled available amount = confirmed settlements - settlement reversals

allocated paid amount = valid allocations to obligation
                      - allocation reversals

obligation balance = original obligation amount
                   + approved obligation increases
                   - approved allowances/write-offs
                   - allocated paid amount
                   + refunded/reopened amounts where applicable
```

Cached projections are recalculated from these authoritative records and checked for drift.

---

## 7. Target flows

### 7.1 Fully paid sale

```text
Order fulfilled
  -> Sale snapshot
  -> Sale obligation
  -> Payment intent
  -> Succeeded attempt
  -> Confirmed settlement
  -> Allocation to sale obligation
  -> PAYMENT_RECEIVED financial event
  -> Sale obligation balance = 0
  -> Sale/payment projections = paid/succeeded
```

### 7.2 Partial payment and receivable

```text
Sale obligation = full net amount
  -> settlement for partial amount
  -> allocation for partial amount
  -> remaining obligation balance > 0
  -> A/R classification/projection
  -> DEBT_CREATED economic event for outstanding value under approved policy
```

The receivable is not a second debt amount copied from the sale; it is the outstanding customer obligation viewed through the A/R subledger.

### 7.3 Fully unpaid sale

```text
Sale obligation created
  -> no settlement
  -> no allocation
  -> entire balance remains outstanding
  -> A/R projection open
```

An `unpaid` tender line is not a payment attempt.

### 7.4 Split payment

```text
One obligation
  <- allocation from cash settlement
  <- allocation from mobile-money settlement
```

The sale does not need one `payment_method` value.

### 7.5 A/R repayment

```text
Outstanding obligation
  <- new payment intent/attempt or approved collection command
  <- confirmed settlement
  <- allocation to outstanding obligation
  -> DEBT_REPAYMENT transfer event
  -> A/R and intent compatibility projections refresh
```

### 7.6 Standalone payment or deposit

```text
Payment intent
  -> attempt
  -> settlement
  -> available/unapplied funds
  -> later allocation to one or more obligations
```

The settlement fact is not rewritten when later allocated.

### 7.7 Refund

```text
Original settlement/allocation
  -> approved refund request
  -> refund attempt/settlement
  -> reversal or reduction of original allocation
  -> REFUND_PAID financial event
  -> obligation/credit state recalculated
```

A refund must reference the original economic application. A dormant event-emitter helper is not a complete refund workflow.

---

## 8. Canonical invariants

### 8.1 Monetary invariants

```text
amounts use Decimal/numeric, never binary float as storage truth
currency is explicit on every monetary authority
settled amount >= 0
allocated amount >= 0
total active allocations from a settlement <= available settled amount
allocation currency matches settlement and obligation, unless an explicit FX record exists
obligation balance never becomes negative without an explicit credit/overpayment model
```

### 8.2 Allocation invariants

```text
every allocation references one valid source of available funds
every allocation references one valid obligation
allocation tenant matches both source and target tenant
allocation reversal references the original allocation
the same idempotent command cannot allocate twice
```

### 8.3 Payment invariants

```text
attempt does not imply settlement unless the channel policy explicitly confirms immediately
provider callback identity is unique in the correct tenant/provider scope
successful replay cannot create another attempt or settlement
provider amount/currency mismatch is rejected or quarantined
```

### 8.4 Commercial invariants

```text
commercial snapshot totals reconcile to lines, taxes and adjustments
payment method is not commercial transaction authority
completed documents retain historical item and price snapshots
```

### 8.5 Event invariants

```text
every canonical financial event has a non-null idempotency key
event replay does not mutate original evidence
corrections are new compensating or adjustment events
occurred_at and recorded_at are timezone-aware
source, correlation and causation are traceable
```

### 8.6 Reconciliation invariants

```text
window_end > window_start
window identity includes tenant, branch/property, shift/cycle and channel
previous closing is resolved within the same reconciliation series
middle required windows cannot be skipped
later actual counts are preserved when earlier openings are corrected
closed periods require controlled reopen/correction
```

---

## 9. Legacy-field disposition

| Legacy field/table | Target disposition |
|---|---|
| `orders.status` | Retain as operational status |
| `orders.total` | Retain as operational/commercial estimate or snapshot with explicit semantics |
| `sales.status` | Retain as commercial projection derived from transaction/obligation state |
| `sales.payment_method` | Deprecate as authority; expose derived method summary |
| `sales.payment_summary` | Replace with typed read projection |
| `sales.tendered_total` | Compatibility projection from attempts/settlements |
| `sales.change_amount` | Compatibility snapshot; formalize change/credit treatment |
| `sales.unpaid_amount` | Compatibility projection from obligation balance |
| `payment_intents.total_paid` | Cached projection from allocations |
| `payment_intents.balance_due` | Cached projection from obligation allocations |
| `payment_intents.meta` balance aliases | Stop adding new aliases; migrate consumers to typed fields/read models |
| `payment_attempts.sale_id` | Deprecate duplicate relationship after intent/obligation links are authoritative |
| `payments` | Freeze new writes, compatibility read, backfill/link, retire |
| `accounts_receivable` | Compatibility A/R projection |
| `accounts_receivable_repayments` | Compatibility history linked to settlement/allocation |
| `treasury_logs` | Preserve and evolve behind canonical FinancialEvent interface |
| `recon_sheets` | Preserve as control snapshots; centralize writer |

No legacy field is removed until all readers, reports, receipts and API contracts have a tested replacement.

---

## 10. Integrity requirements for the target schema

- Explicit foreign keys wherever the target is a real relational entity.
- Tenant-safe composite uniqueness for idempotency and external identities.
- Non-null currency and idempotency on canonical money/event records.
- Check constraints for allowed status, positive/non-negative amounts and valid windows.
- No cascading hard delete from tenant/branch into retained financial evidence.
- Soft closure, retention or archival rather than destructive deletion.
- Timezone-aware timestamps.
- Typed JSON only for provider evidence or extensible metadata, not core financial totals.
- One writer/service boundary per aggregate.
- Drift-detection queries for cached projections.

---

## 11. Migration principles

### Phase 1 — Additive target structures

- Add obligations, settlements and allocations without removing legacy structures.
- Introduce canonical services and typed read models.
- Preserve all B1 characterization tests.

### Phase 2 — Dual-write under controlled comparison

- Existing commands write canonical records and legacy compatibility projections in one database transaction.
- Compare legacy and canonical totals continuously.
- Reject or quarantine unexplained divergence.

### Phase 3 — Backfill and reconcile

- Backfill historical obligations, settlements and allocations using deterministic rules.
- Record provenance and exceptions.
- Reconcile totals by tenant, sale, intent, receivable, channel and day.

### Phase 4 — Read migration

- Move receipts, reports, APIs and frontend screens to canonical read models.
- Keep legacy fields available for compatibility until consumers are proven migrated.

### Phase 5 — Freeze and retire legacy writers

- Stop new writes to legacy `payments` and duplicated balance fields except through projection code.
- Remove direct reconciliation SQL and use one service boundary.

### Phase 6 — Contract cleanup

- Deprecate legacy API fields with versioned replacement contracts.
- Remove legacy tables/columns only after an approved retention and rollback plan.

---

## 12. Required B2 follow-up decisions

This authority map establishes direction but does not finalize physical schema names. B2 must still approve:

1. Whether the canonical obligation is named `financial_obligation`, `commercial_obligation`, or another neutral term.
2. Obligation types and state machine.
3. Settlement model and immediate/manual settlement rules.
4. Allocation types, reversals and adjustment model.
5. Deposit, overpayment, unapplied funds and customer-credit representation.
6. Refund, reversal, void, chargeback and cancellation vocabulary.
7. Gross sale, net sale, tax, discount, complimentary and tip semantics.
8. Financial-event catalog and versioning.
9. Journal-entry and posting-rule boundaries.
10. Party/customer linkage before the shared Party module is implemented.
11. Cross-currency and FX policy.
12. Reconciliation series, correction and continuity policy.
13. API compatibility and deprecation schedule.
14. Backfill rules for legacy `payments`, A/R and treasury records.

---

## 13. B2 design gate

B2 is ready to proceed to physical target modeling only when reviewers agree that:

```text
Order owns operations.
Sale owns the commercial snapshot.
Obligation owns what is owed.
Intent owns orchestration.
Attempt owns the payment try.
Settlement owns confirmed value movement.
Allocation owns application of value to debt.
Financial event owns immutable economic meaning.
Journal owns formal accounting representation.
Reconciliation owns control evidence.
```

The target must preserve current WND behavior while allowing Restaurant, Hospitality, Retail, Healthcare and future packs to create obligations and consume payment/financial services without embedding their domain tables in the financial kernel.

---

## 14. Approval record

| Field | Value |
|---|---|
| Record | B2 Canonical Financial Authority Map and Legacy Disposition |
| Version | 1.0 |
| Prepared | 5 August 2026 |
| Evidence baseline | B1 tag `track-b-b1-characterization-20260804` |
| Branch | `track-b/b2-canonical-financial-model` |
| Production changes authorized | No |
| Schema changes authorized | No |
| Review status | Approved |
| Approver | Project Owner |
| Approval date | 5 August 2026 |
| Notes | Approved as the authority baseline for the remaining B2 design work; implementation still requires separate approval. |
