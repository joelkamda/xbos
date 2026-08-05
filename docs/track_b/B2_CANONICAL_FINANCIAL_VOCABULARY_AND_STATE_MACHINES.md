# XBOS Track B-FIN — B2 Canonical Financial Vocabulary and State Machines

**Record type:** Architecture vocabulary and lifecycle decision draft
**Workstream:** Track B-FIN — Neutral Financial Spine
**Phase:** B2 — Canonical Financial Vocabulary and Target Model
**Status:** Approved architecture decision
**Date:** 5 August 2026
**Authority baseline:** `a73a474` — Canonical Financial Authority Map
**B1 behavior baseline:** `track-b-b1-characterization-20260804` at `56e3b19`
**Track A reconciliation reference:** WND Reconciliation R2, tag `wnd-reconciliation-r2-live-20260805`
**Branch:** `track-b/b2-canonical-financial-model`

---

## 1. Purpose

This record defines one financial language and a set of non-overlapping state machines for XBOS.

It separates:

- operational progress;
- commercial recognition;
- obligation condition;
- payment orchestration;
- payment-rail attempts;
- confirmed settlement;
- allocation of funds;
- refunds and reversals;
- financial events;
- journal posting;
- reconciliation control.

The design must preserve current WND behavior through compatibility projections while allowing Restaurant, Hospitality, Retail, Healthcare, Professional Services and future packs to use the same financial kernel.

This document is design-only. It authorizes no migration, runtime change or API break.

---

## 2. Evidence from the deployed legacy system

### 2.1 Persisted statuses in parity

| Record | Status | Count |
|---|---:|---:|
| Accounts receivable | `open` | 156 |
| Accounts receivable | `partial` | 27 |
| Accounts receivable | `settled` | 2 |
| Order | `cancelled` | 534 |
| Order | `paid` | 6,172 |
| Order | `pending_payment` | 3 |
| Order | `receivable` | 185 |
| Payment attempt | `succeeded` | 6,372 |
| Payment intent | `pending` | 226 |
| Payment intent | `processing` | 64 |
| Payment intent | `succeeded` | 6,438 |
| Reconciliation | `closed` | 665 |
| Sale | `paid` | 6,172 |
| Sale | `pending_payment` | 187 |

The legacy `payments` table produced no grouped status rows and appears empty in the parity data. Its count must be verified before retirement planning.

### 2.2 Declared code statuses

```text
Legacy Payment:
    pending, paid, failed, cancelled

PaymentIntent:
    pending, processing, succeeded, failed, cancelled

PaymentAttempt:
    pending, succeeded, failed

Sale:
    pending_payment, paid, cancelled

Order:
    unconstrained string

AccountsReceivable:
    unconstrained string

Reconciliation:
    unconstrained string
```

### 2.3 Legacy coupling

Current settlement behavior sets:

```text
full payment:
    order.status = paid
    sale.status = paid
    intent.status = succeeded

partial or unpaid:
    order.status = receivable
    sale.status = pending_payment
    intent.status = processing or pending
    A/R.status = partial or open
```

`OrderRepository.list_pending()` uses `order.status == pending_payment` as a cashier-queue filter. Moving an order to `receivable` removes it from that queue.

Therefore the current `order.status` simultaneously represents:

- queue placement;
- payment condition;
- A/R routing;
- cancellation.

The current `sale.status` similarly represents both commercial and payment condition.

### 2.4 Legacy payment calculation

Ordinary POS settlement uses succeeded payment-attempt sums:

```text
cumulative tendered = sum(succeeded attempts)
total paid          = min(net total, cumulative tendered)
balance due         = max(0, net total - total paid)
```

A/R repayment takes the maximum of:

```text
A/R paid amount
PaymentIntent total paid
sum(succeeded attempts)
```

and writes the result back to both A/R and PaymentIntent aggregates.

The target replaces this synchronization with explicit settlements and allocations.

### 2.5 Proven WND Reconciliation R2 behavior

Track A completed and deployed a production stabilization of WND reconciliation on 5 August 2026.

Reference checkpoints:

```text
Backend commit:  53cb987
Frontend commit: 28b49b1
Tag:             wnd-reconciliation-r2-live-20260805
```

The following behaviors are proven in the live WND iteration and are adopted as Track B platform invariants:

- Expected closing equals opening plus inflows minus outflows plus adjustments.
- Variance equals actual closing minus expected closing.
- New drafts may prefill actual closing from the final recomputed expected closing.
- A prefilled actual remains semantically different from an operator-confirmed actual.
- Zero variance does not mean the workflow is closed.
- Reconciled means formally closed, not merely balanced.
- Missing or unclosed required predecessor windows can block closure.
- The next opening comes from the previous actual closing in the same reconciliation series.
- A/R and A/P are control accounts and are excluded from treasury totals.
- Commercial Settlement explains sales economics and is not a treasury balance.
- Summary totals are recomputed from included treasury rows.
- A parent aggregate and its children are never counted simultaneously.
- Variance investigation evidence appears only when a variance exists.
- Shift attribution is policy-driven and tenant-specific.
- Financial reconciliation releases require production-like arithmetic, workflow, visual and operator-interpretation acceptance.

Track B adopts these behaviors, not the current Track A table names, endpoints, hard-coded channels, WND shift assumptions or simplified persistence model.

---

## 3. Vocabulary rules

### 3.1 One term, one meaning

Every canonical term has one meaning throughout backend, frontend, APIs, events, reports and packs.

Display labels may be localized or adapted by tenant and industry pack. Stable semantic codes do not change.

### 3.2 State versus condition

A **state** is part of an aggregate lifecycle and changes only through an authorized transition.

A **condition** is derived from facts at a point in time.

Examples:

- `order.fulfilled` is an operational state;
- `payment_condition=partially_paid` is derived from obligation allocations;
- `aging_condition=overdue` is derived from due date and remaining balance;
- `refund_condition=partially_refunded` is derived from refund allocations.

Derived conditions must not be persisted as competing, independently editable truth.

### 3.3 Status names are scoped

Bare labels such as `pending`, `paid`, `closed` or `cancelled` are ambiguous without their aggregate.

Use explicit forms in contracts and events:

```text
order_state
commercial_transaction_state
obligation_state
payment_condition
payment_intent_state
payment_attempt_state
settlement_state
allocation_condition
refund_state
journal_entry_state
reconciliation_state
reconciliation_readiness  # derived: blocked or ready_to_close
variance_condition        # derived: balanced or variance
actual_provenance         # system_prefilled/operator_confirmed/external_confirmed
```

### 3.4 Terminal does not mean deleted

Terminal financial records remain retained and auditable. Cancellation, expiry, failure, reversal and write-off never imply destructive deletion.

---

## 4. Canonical vocabulary

### 4.1 Tenant

A legally or operationally isolated XBOS customer and the primary data, policy and idempotency boundary.

### 4.2 Organization scope

A company, legal entity, branch, property, outlet, department, warehouse, cost center or other governed operating location within a tenant.

### 4.3 Party

A person or organization participating as customer, guest, supplier, employee, payer, payee, debtor, creditor, guarantor or other role.

### 4.4 Atomic Unit

The smallest independently identifiable good, service, fee, resource or operational unit that can be sold, bought, stocked, consumed, scheduled, classified or measured.

### 4.5 Domain operation

An industry-pack-owned operational aggregate, such as a restaurant order, hotel stay, retail checkout, service engagement or healthcare encounter.

### 4.6 Commercial transaction

A controlled snapshot of the commercial fact: what was supplied or adjusted, to whom, at what quantity, price, tax, discount and net value.

### 4.7 Transaction line

A priced or adjusted component of a commercial transaction, including its Atomic Unit and classification snapshots.

### 4.8 Charge

A component that increases or decreases the amount of a commercial transaction or obligation.

Examples include item price, service fee, tax, discount, complimentary allowance, surcharge, tip and approved write-off.

### 4.9 Obligation

An amount one Party/account owes another in a specified currency under defined terms.

### 4.10 Receivable

The customer-facing or accounting-subledger view of an outstanding obligation owed to the tenant.

A receivable is not a second independently calculated debt.

### 4.11 Payable

The subledger view of an outstanding obligation owed by the tenant.

### 4.12 Payment intent

An orchestration request to collect or disburse a defined amount. It coordinates attempts but does not prove settlement or allocation.

### 4.13 Payment attempt

One interaction with a tender, payment rail or provider.

### 4.14 Authorization

A provider or operator confirmation that a payment may be captured or completed. Authorization is not settlement.

### 4.15 Settlement

A confirmed movement of value through a payment channel or provider.

### 4.16 Available funds

Settled value that remains available for allocation after reversals, fees or other explicitly modeled reductions.

### 4.17 Payment allocation

An application of available settled value to one obligation.

### 4.18 Unapplied funds

Settled value that has not yet been allocated to an obligation.

### 4.19 Deposit or advance

Funds received before final performance or before allocation to a final obligation. Accounting classification may be a liability until earned.

### 4.20 Overpayment

Settled value exceeding the amount that may be allocated to the target obligation. It becomes unapplied funds, customer credit, or refundable value under policy; it does not make the obligation balance negative.

### 4.21 Customer credit

A recognized amount available to satisfy future customer obligations. It is not revenue when created merely from excess or returned value.

### 4.22 Change

Tendered cash returned to the payer as part of the same cashier settlement. Only retained value is collectible financial movement.

### 4.23 Tip

Value voluntarily designated for staff, service or another configured beneficiary. Its revenue/liability treatment is controlled by country and tenant policy.

### 4.24 Discount

A commercial allowance reducing the amount charged before or at confirmation, classified by explicit reason and policy.

### 4.25 Complimentary allowance

A non-cash commercial allowance where the tenant intentionally charges the customer zero or less than normal value for specified goods/services.

### 4.26 Refund

A first-class authorized process returning value previously settled or allocated.

### 4.27 Reversal

A compensating action that neutralizes all or part of an earlier settlement, allocation, event or journal effect while preserving the original record.

### 4.28 Void

Cancellation of an operation before final settlement or commercial finalization. A post-settlement return is a refund or reversal, not a void.

### 4.29 Chargeback

A provider-initiated or externally imposed reversal/dispute of previously settled value.

### 4.30 Write-off

An approved non-payment resolution reducing an obligation without collection. It creates an explicit financial event and posting; it is not a payment.

### 4.31 Financial event

An immutable statement of an economically meaningful fact, with stable type, version, lineage, amount, currency and occurrence time.

### 4.32 Journal entry

A balanced accounting representation generated from one or more financial events under versioned posting rules.

### 4.33 Reconciliation session

A controlled comparison between expected channel/account balances and actual counted or external balances for one governed time window.

### 4.34 Reconciliation class

The aggregation semantics of a reconciliation line or window.

Canonical classes:

```text
treasury
control_account
commercial_settlement
```

- **Treasury** represents directly controlled liquid channels such as cash, mobile money and bank accounts.
- **Control account** represents non-liquid balances such as A/R and A/P.
- **Commercial settlement** explains the relationship among sales, allowances, receivables and attributable collections.

Classes may appear in one experience but never share aggregation semantics.

### 4.35 Reconciliation series

The ordered sequence of reconciliation windows sharing tenant, organization, class, channel/account and shift/cycle policy.

Continuity and previous-closing lookup occur only inside one series.

### 4.36 Reconciliation evidence

Structured evidence explaining a variance, correction, reopening or approval.

Recommended fields include reason code, note, supporting reference/attachment, actor, reviewer and timestamps.

### 4.37 Actual-closing provenance

The source and confirmation condition of the actual closing value.

Canonical conditions:

```text
system_prefilled
operator_confirmed
external_confirmed
```

A value may numerically equal expected closing while still being only system-prefilled.

### 4.38 Receipt

A read-only presentation assembled from commercial, obligation, payment, allocation and tenant-document facts. It has no independent financial authority.

### 4.39 Idempotency key

A stable caller/provider identifier for one logical command within an explicit tenant and operation scope.

### 4.40 Correlation ID

An identifier connecting the entire end-to-end business flow.

### 4.41 Causation ID

The identifier of the command or event that directly caused another event.

### 4.42 Business date

The tenant/branch accounting or operating date determined by the configured business calendar, which may differ from the UTC calendar date.

---

## 5. Separation of lifecycle and financial condition

The target exposes separate fields rather than overloading one `status`:

```text
operational_state
commercial_state
obligation_state
payment_condition         # derived
collection_condition      # derived
refund_condition          # derived
```

Example:

```text
Hotel stay:
    operational_state = checked_out
    commercial_state  = confirmed
    obligation_state  = partially_satisfied
    payment_condition = partially_paid
    collection_condition = current
```

Example:

```text
Restaurant order:
    operational_state = fulfilled
    commercial_state  = confirmed
    obligation_state  = open
    payment_condition = unpaid
    collection_condition = not_due
```

Operational completion does not require immediate payment when tenant policy allows credit.

---

## 6. Domain-operation lifecycle

Domain operation states are pack-owned. The kernel requires only a small interoperable condition set.

Recommended neutral operational states:

```text
draft
confirmed
in_progress
fulfilled
cancelled
closed
```

### 6.1 Meaning

| State | Meaning |
|---|---|
| `draft` | Editable and not yet committed to fulfillment |
| `confirmed` | Accepted for operational execution |
| `in_progress` | Fulfillment has started |
| `fulfilled` | Required operational delivery is complete |
| `cancelled` | Stopped under an authorized cancellation policy |
| `closed` | Operational follow-up is complete and record is administratively closed |

### 6.2 Typical transitions

```text
draft → confirmed → in_progress → fulfilled → closed
  └──────────────→ cancelled
confirmed ───────→ cancelled
in_progress ─────→ cancelled       # only under pack policy
```

Packs may use richer internal states—such as `checked_in`, `ready_for_pickup`, `served` or `discharged`—and map them to neutral conditions.

Payment does not drive these transitions unless a pack policy explicitly blocks an operational command pending payment.

---

## 7. Commercial-transaction lifecycle

Canonical states:

```text
draft
confirmed
cancelled
reversed
```

### 7.1 Meaning

| State | Meaning |
|---|---|
| `draft` | Commercial details may still be edited; no final obligation is asserted |
| `confirmed` | Commercial snapshot is committed and obligations/events may be created |
| `cancelled` | Draft or eligible confirmed transaction cancelled under policy before irreversible performance/settlement |
| `reversed` | A confirmed transaction has been economically neutralized through explicit compensating records |

### 7.2 Transitions

```text
draft → confirmed
draft → cancelled
confirmed → reversed
confirmed → cancelled              # only when cancellation policy permits
```

There is no `paid` commercial state. Payment is a derived condition of the obligation.

Returns and refunds do not rewrite the original transaction. They create related adjustment/return transactions and compensating financial records.

---

## 8. Obligation lifecycle

Canonical states:

```text
open
partially_satisfied
satisfied
cancelled
written_off
```

### 8.1 Meaning

| State | Meaning |
|---|---|
| `open` | Positive amount remains and no valid allocation has fully satisfied it |
| `partially_satisfied` | Valid allocations/allowances satisfy part, but not all, of the obligation |
| `satisfied` | Remaining collectible balance is zero |
| `cancelled` | Obligation is voided before collectible performance under approved policy |
| `written_off` | Remaining amount is resolved through approved non-collection treatment |

### 8.2 Transitions

```text
open → partially_satisfied → satisfied
open → satisfied
open → cancelled
open → written_off
partially_satisfied → satisfied
partially_satisfied → written_off
satisfied → partially_satisfied/open   # only through explicit refund/reversal effect
```

The final transition is a recalculated condition caused by compensating records, not an unaudited status edit.

### 8.3 Derived collection conditions

These are not obligation lifecycle states:

```text
not_due
current
overdue
in_collection
disputed
on_hold
```

They derive from due dates, collection actions, disputes and policy.

### 8.4 Derived payment conditions

```text
unpaid
partially_paid
paid
overpaid
partially_refunded
refunded
```

`overpaid` means excess funds exist outside the obligation as unapplied funds, credit or refund payable. The obligation itself remains satisfied at zero balance.

---

## 9. Payment-intent lifecycle

Canonical states:

```text
pending
processing
partially_succeeded
succeeded
failed
cancelled
expired
```

### 9.1 Meaning

| State | Meaning |
|---|---|
| `pending` | Active intent with no attempt currently awaiting an outcome |
| `processing` | One or more attempts or provider actions are awaiting final outcome |
| `partially_succeeded` | Confirmed settlements are below the requested amount and more collection is allowed |
| `succeeded` | Confirmed settlement target has been reached under intent policy |
| `failed` | Orchestration concluded unsuccessfully and no automatic retry remains |
| `cancelled` | Authorized cancellation ended collection before success |
| `expired` | Intent validity period ended before success |

### 9.2 Transitions

```text
pending → processing
pending → cancelled
pending → expired
processing → pending                 # retry allowed after non-terminal attempt
processing → partially_succeeded
processing → succeeded
processing → failed
processing → cancelled
processing → expired
partially_succeeded → processing
partially_succeeded → succeeded
partially_succeeded → cancelled      # retains already-settled facts
partially_succeeded → expired        # retains already-settled facts
```

A failed attempt does not automatically fail the intent if retry remains possible.

Intent success describes the collection target, not allocation to an obligation. Standalone or deposit intents may succeed while funds remain unapplied.

---

## 10. Payment-attempt lifecycle

Canonical states:

```text
pending
processing
requires_action
authorized
succeeded
failed
cancelled
expired
```

### 10.1 Meaning

| State | Meaning |
|---|---|
| `pending` | Attempt created but not yet submitted or accepted for processing |
| `processing` | Rail/provider is processing the attempt |
| `requires_action` | Additional payer/operator action is required |
| `authorized` | Amount authorized but not yet captured/settled |
| `succeeded` | Rail/provider accepted completion under its contract |
| `failed` | Attempt ended unsuccessfully |
| `cancelled` | Attempt was explicitly cancelled before completion |
| `expired` | Attempt exceeded its validity window |

### 10.2 Transitions

```text
pending → processing
pending → succeeded                   # immediate cash/manual confirmation
pending → cancelled
pending → expired
processing → requires_action
requires_action → processing
processing → authorized
authorized → succeeded
authorized → cancelled                # provider-dependent release/void
processing → succeeded
processing → failed
processing → cancelled
processing → expired
```

Terminal attempt states:

```text
succeeded
failed
cancelled
expired
```

A succeeded attempt is not universally equivalent to settlement. Channel policy defines whether it produces immediate confirmed settlement or awaits a separate provider settlement event.

---

## 11. Settlement lifecycle

Canonical states:

```text
pending
confirmed
failed
partially_reversed
reversed
```

### 11.1 Meaning

| State | Meaning |
|---|---|
| `pending` | Settlement initiated but confirmation/availability is incomplete |
| `confirmed` | Value movement is confirmed under channel policy |
| `failed` | Settlement failed and contributes no available funds |
| `partially_reversed` | A compensating settlement has reversed part of the confirmed amount |
| `reversed` | Confirmed amount has been fully neutralized by traceable reversals |

### 11.2 Transitions

```text
pending → confirmed
pending → failed
confirmed → partially_reversed
confirmed → reversed
partially_reversed → partially_reversed
partially_reversed → reversed
```

Reversal states are derived from separate reversal records. Original settlement evidence remains immutable.

Availability date may differ from confirmation date. Availability should be modeled explicitly where providers settle later.

---

## 12. Allocation lifecycle and condition

Allocations and their reversals are append-only records.

Derived allocation conditions:

```text
active
partially_reversed
reversed
```

### 12.1 Commands

```text
create allocation
partially reverse allocation
fully reverse allocation
```

### 12.2 Rules

- An allocation references exactly one available-funds source and one obligation.
- Allocation amount is positive.
- Cumulative active allocations cannot exceed available settled funds.
- Cumulative active allocations cannot exceed allocatable obligation balance unless explicit overpayment policy redirects the excess.
- A reversal references the original allocation.
- Original allocation amount is never overwritten.
- Tenant and currency must agree unless an explicit FX conversion record bridges them.

---

## 13. Refund lifecycle

A refund is a first-class workflow linked to original settlement and allocation evidence.

Canonical states:

```text
requested
approved
processing
succeeded
failed
rejected
cancelled
```

### 13.1 Meaning

| State | Meaning |
|---|---|
| `requested` | Refund request recorded with amount, reason and source references |
| `approved` | Authorized under permission and policy |
| `processing` | Refund attempt/provider action is underway |
| `succeeded` | Return settlement is confirmed and related allocation reversal recorded |
| `failed` | Refund attempt ended unsuccessfully; original facts remain |
| `rejected` | Authorized reviewer declined the request |
| `cancelled` | Request withdrawn before successful processing |

### 13.2 Transitions

```text
requested → approved
requested → rejected
requested → cancelled
approved → processing
approved → cancelled
processing → succeeded
processing → failed
failed → processing                     # explicit retry/new attempt
```

Partial refunds are multiple or partial refund allocations against the original application. Refund totals may not exceed refundable active value.

---

## 14. Receivable and collection lifecycle

A/R is a projection over obligations, allocations and collection activity.

Legacy-to-canonical mapping:

| Legacy A/R status | Canonical obligation state | Payment condition |
|---|---|---|
| `open` | `open` | `unpaid` |
| `partial` | `partially_satisfied` | `partially_paid` |
| `settled` | `satisfied` | `paid` |

Collection workflow may use a separate state machine:

```text
not_started
active
promise_to_pay
disputed
escalated
resolved
```

Collection workflow never changes paid balance directly. Only allocations, reversals, allowances or write-offs change the obligation balance.

A repayment is not new revenue. It is confirmed settlement allocated to an existing obligation and represented as an A/R-to-channel transfer event.

---

## 15. Financial-event lifecycle

A committed financial event has no mutable business lifecycle.

```text
recorded
```

Corrections create new events with:

- original-event reference;
- correction/reversal type;
- reason;
- causation and correlation;
- actor and approval evidence.

Publication and delivery state belongs to an outbox message, not to the financial event.

Recommended outbox states:

```text
pending
published
retrying
dead_letter
```

---

## 16. Journal-entry lifecycle

Canonical states:

```text
draft
pending_approval
posted
reversed
```

### 16.1 Transitions

```text
draft → pending_approval
draft → posted                         # when policy permits automatic posting
pending_approval → draft               # returned for correction before posting
pending_approval → posted
posted → reversed                      # through a separate reversing entry
```

Posted journal lines are immutable. Corrections use reversing and replacement entries.

Per-currency journal entries must balance:

```text
sum(debits) = sum(credits)
```

---

## 17. Reconciliation lifecycle

Reconciliation must not compress workflow, arithmetic, readiness and observation provenance into one ambiguous status.

Track B uses four backend-authoritative axes.

### 17.1 Workflow states

Canonical workflow states:

```text
draft
closed
approved
reopened
superseded
```

| State | Meaning |
|---|---|
| `draft` | Counts and notes may be entered; window remains open |
| `closed` | Operator finalized the window; changes require reopen/correction authority |
| `approved` | Reviewer approved the closed control result |
| `reopened` | Authorized correction cycle is active |
| `superseded` | An immutable prior revision was replaced by a later approved revision |

Workflow transitions:

```text
draft → closed
closed → approved
closed → reopened
approved → reopened                    # elevated permission and reason required
reopened → closed
closed/approved → superseded            # when revision records are introduced
```

### 17.2 Closure-readiness conditions

Canonical readiness conditions:

```text
blocked
ready_to_close
```

`blocked` means closure is prohibited because a required predecessor or another continuity/control requirement is unmet.

`ready_to_close` means blocking requirements are satisfied. It does not mean the window is balanced or closed.

Readiness is derived and backend-authoritative. It may change without changing the workflow state.

### 17.3 Variance conditions

Canonical variance conditions:

```text
balanced
variance
```

```text
balanced  when actual_closing - expected_closing = 0
variance  when actual_closing - expected_closing != 0
```

Variance condition does not determine workflow closure.

### 17.4 Actual-closing confirmation conditions

Canonical actual conditions:

```text
system_prefilled
operator_confirmed
external_confirmed
```

For a new draft:

```text
actual_closing_default = finalized(expected_closing)
actual_provenance      = system_prefilled
```

The default eliminates misleading initialization variance while preserving the distinction between system expectation and observed truth.

Closing the window must explicitly confirm the actual value, even when the user accepts the prefilled number unchanged.

### 17.5 Presentation labels

UI labels are deterministic projections of the four backend axes.

| Presentation | Required conditions |
|---|---|
| `BALANCED DRAFT` | Workflow `draft`, readiness `ready_to_close`, variance `balanced` |
| `VARIANCE` | Workflow `draft`, readiness `ready_to_close`, variance condition `variance` |
| `BLOCKED` | Workflow `draft`, readiness condition `blocked`; variance remains visible separately |
| `RECONCILED` | Workflow `closed` or `approved` |
| `REOPENED` | Workflow `reopened`; readiness and variance remain visible separately |

Zero variance alone never produces `RECONCILED`.

The backend returns the underlying axes and may also return a canonical presentation label. The frontend must not infer closure from arithmetic alone.

When one primary label is required, precedence is:

```text
closed/approved → RECONCILED
reopened        → REOPENED
draft+blocked   → BLOCKED
draft+variance  → VARIANCE
draft+balanced  → BALANCED DRAFT
```

Secondary variance and blocking indicators remain visible where relevant.

### 17.6 Arithmetic

For each reconciliation line:

```text
expected_closing = opening_balance
                 + inflows
                 - outflows
                 + adjustments

variance = actual_closing - expected_closing
```

For the treasury summary:

```text
treasury_opening = sum(included treasury opening balances)
treasury_expected_closing = sum(included treasury expected closings)
treasury_actual_closing = sum(included treasury actual closings)
treasury_variance = treasury_actual_closing - treasury_expected_closing
```

The server independently recomputes and validates summary totals from included rows.

### 17.7 Reconciliation classes and aggregation

Canonical reconciliation classes:

```text
treasury
control_account
commercial_settlement
```

Treasury includes directly controlled liquid channels such as:

- cash;
- mobile-money accounts;
- named bank accounts;
- other configured liquid settlement channels.

Control accounts include balances such as:

- accounts receivable;
- accounts payable.

Commercial Settlement explains:

- gross sales;
- allowances;
- receivable movement;
- collections attributable to sales;
- related commercial differences.

A/R, A/P and Commercial Settlement values are excluded from treasury opening, expected closing, actual closing and variance totals.

### 17.8 Parent and child aggregation

Aggregation metadata must declare whether a row is:

```text
leaf
parent_aggregate
presentation_only
```

When a parent such as `Bank` expands into named accounts, the summary includes either:

```text
the parent aggregate
```

or:

```text
the included child accounts
```

never both.

This is enforced through aggregation metadata and validation, not channel naming conventions.

### 17.9 Continuity and dependency

Each window belongs to one reconciliation series scoped by:

- tenant;
- organization/branch/property;
- reconciliation class;
- channel/account;
- shift or cycle policy.

Rules:

- Reconciliation series is scoped by tenant, organization, shift/cycle and channel/account.
- Window end must be after start.
- Required middle windows cannot be skipped.
- The previous close comes from the same series.
- Next opening equals previous actual closing.
- A missing or unclosed required predecessor sets readiness to `blocked` and disables closure.
- Correcting an earlier opening carries forward without overwriting later actual counts.
- Reconciliation corrections never rewrite financial events to force agreement.

Dependencies and corrections should be explicit and auditable rather than inferred solely from timestamps.

### 17.10 Variance evidence

When variance is non-zero, the line supports structured evidence:

```text
reason_code
free_text_note
supporting_reference
attachment_reference
entered_by
entered_at
reviewed_by
reviewed_at
```

Balanced rows do not require permanent investigation controls. Variance controls appear when variance exists or when policy requires evidence.

### 17.11 Shift and business-calendar policy

Shift attribution is configured from:

- tenant timezone;
- shift schedule;
- business-day boundary;
- payment recognition time;
- operational attribution rules;
- channel-specific timing policy where required.

WND's rule that payments after 6:00 p.m. belong to Night Shift is tenant/Restaurant configuration, not neutral-kernel code. Waiter or service attribution may remain independent from payment-entry shift.

### 17.12 Required acceptance scenarios

#### Zero-activity balanced draft

```text
Opening = 350,300
Inflows = 0
Outflows = 0
Expected = 350,300
Prefilled Actual = 350,300
Variance = 0
Workflow = draft
Presentation = BALANCED DRAFT
```

#### Activity with correct actual

```text
Opening = 350,300
Net Movement = 286,000
Expected = 636,300
Actual = 636,300
Variance = 0
Presentation = BALANCED DRAFT until formally closed
```

#### Real shortage

```text
Expected = 636,300
Actual = 606,300
Variance = -30,000
Variance condition = variance
Investigation evidence enabled
```

#### Blocked predecessor

```text
Current variance = 0
Required predecessor = missing or unclosed
Readiness = blocked
Presentation = BLOCKED
Close command rejected
```

#### Formal closure

```text
Readiness = ready_to_close
Actual value explicitly confirmed
Authorized close succeeds
Workflow = closed
Presentation = RECONCILED
```

#### Reopen

```text
Previously closed/approved window
Authorized reopen with reason/evidence
Workflow = reopened
Presentation = REOPENED
Audit event recorded
```

#### Treasury and control-account separation

```text
Treasury includes Cash, MTN, Orange and Bank
Treasury excludes A/R and A/P
Commercial Settlement remains explanatory
```

#### Bank hierarchy

```text
Bank parent plus named child accounts
Summary counts parent or included children, never both
```

### 17.13 Financial UX acceptance

Automated correctness is necessary but insufficient. Reconciliation release gates include:

- restored production-like data;
- arithmetic cases;
- workflow and authorization validation;
- server/client summary agreement;
- visual hierarchy review;
- operator-interpretation review;
- controlled live acceptance.

The UI prioritizes financial truth, hierarchy, difference visibility, workflow state and operator confidence over generic table density.

---

## 18. Cancellation, void, reversal and refund distinctions

| Term | Timing | Economic effect |
|---|---|---|
| Cancellation | Before final commercial/operational commitment under policy | Stops the process; may release reservations |
| Void | Before settlement finality/capture | Prevents value movement or releases authorization |
| Reversal | After a financial fact exists | Creates an opposite traceable financial effect |
| Refund | Customer-facing return of previously collected value | Creates return settlement and reverses/reduces allocations |
| Chargeback | Provider/external reversal or dispute | Removes or contests settled value under provider rules |
| Write-off | Approved resolution without collection | Reduces obligation through explicit allowance/loss event |

These terms are not interchangeable in APIs, events, reports or UI labels.

---

## 19. Legacy compatibility mapping

### 19.1 Orders

| Legacy `orders.status` | Compatibility interpretation |
|---|---|
| `pending_payment` | Operational state remains derived from order/fulfillment; payment condition is `unpaid` or `partially_paid`; include in cashier work queue |
| `receivable` | Operational state remains unchanged; positive obligation balance exists; remove from immediate cashier queue under WND policy |
| `paid` | Payment condition is `paid`; operational state remains independently derived |
| `cancelled` | Operational/commercial cancellation projection |

Target cashier queues query explicit work-queue and payment conditions rather than overloading order state.

### 19.2 Sales

| Legacy `sales.status` | Compatibility interpretation |
|---|---|
| `pending_payment` | Commercial transaction is confirmed; obligation condition is open/partial |
| `paid` | Commercial transaction is confirmed; obligation payment condition is paid |
| `cancelled` | Map only after validating whether commercial cancellation or pre-settlement void occurred |

Target commercial status never toggles between confirmed and pending because of repayment progress.

### 19.3 Payment intents

| Legacy state | Canonical mapping |
|---|---|
| `pending` | `pending` |
| `processing` with positive collected amount | `partially_succeeded` |
| `processing` with asynchronous attempt | `processing` |
| `succeeded` | `succeeded`, subject to settlement backfill evidence |
| `failed` | `failed` |
| `cancelled` | `cancelled` |

The legacy `processing` state requires amount/attempt context during migration.

### 19.4 Payment attempts

| Legacy state | Canonical mapping |
|---|---|
| `pending` | `pending` or `processing` based on provider evidence |
| `succeeded` manual/cash | `succeeded` plus immediate confirmed settlement |
| `succeeded` asynchronous provider | `succeeded` plus settlement backfill only when confirmation evidence exists |
| `failed` | `failed` |

### 19.5 Accounts receivable

Legacy A/R rows become compatibility projections linked to canonical obligations. Legacy repayment rows link to settlements and allocations.

### 19.6 Reconciliation

Legacy `draft`, `closed`, `approved` and `reopened` map directly to workflow state where present. Existing closed rows become revision zero under any future revision model.

WND R2 presentation maps as follows:

| WND R2 presentation | Canonical mapping |
|---|---|
| `BALANCED DRAFT` | Workflow `draft`, readiness `ready_to_close`, variance `balanced` |
| `VARIANCE` | Workflow `draft`, readiness `ready_to_close`, variance condition `variance` |
| `BLOCKED` | Workflow `draft`, readiness `blocked`; variance remains a separate condition |
| `RECONCILED` | Workflow `closed` or `approved` |
| `REOPENED` | Workflow `reopened`; readiness and variance remain separate conditions |

The R2 status words remain valid UI semantics. Track B represents them through separate authoritative axes so arithmetic, workflow and continuity cannot contradict one another.

---

## 20. Pack-facing contract

Industry packs may:

- create or amend domain operations;
- confirm commercial transactions and charges;
- request creation of obligations;
- request payment intents;
- consume payment/allocation conditions;
- request refunds, cancellations or write-offs through authorized commands;
- subscribe to versioned financial events;
- contribute taxonomy, documents and reports.

Industry packs may not:

- write payment, allocation, treasury or journal tables directly;
- invent pack-specific meanings for canonical states;
- mark commercial transactions paid through a status assignment;
- calculate receivable balances independently;
- mutate financial events;
- close reconciliation windows outside the reconciliation service.

---

## 21. Required context on canonical records

Every canonical financial authority must carry or reliably derive:

- tenant;
- legal/organization scope;
- currency;
- exact decimal amount;
- UTC occurrence and recorded timestamps;
- business date and calendar policy;
- source component and source record;
- correlation and causation IDs;
- actor, device or service identity;
- idempotency scope and key;
- provider/external references where applicable;
- classification and posting-rule version where material.

---

## 22. Transition enforcement

State changes must occur through commands and aggregate services, not arbitrary field assignment.

Each transition command must validate:

- current state;
- requested target state;
- actor permission;
- tenant and organization scope;
- amount and currency invariants;
- required reason/evidence;
- idempotency;
- concurrent version;
- emitted events and compatibility projections.

Recommended service behavior:

```text
load aggregate with tenant scope
lock or version-check
validate transition
append authoritative records/events
update derived projection in the same transaction
write outbox message
commit
```

Database check constraints should enforce allowed state codes. Application services enforce context-dependent transition rules.

---

## 23. Open decisions for physical modeling

Approval of the vocabulary does not yet resolve:

1. Final physical table and column names.
2. Whether commercial transaction is a new neutral aggregate or a canonical interface over pack-owned snapshots.
3. Whether one intent may target several obligations directly or only through later allocations.
4. Provider authorization/capture detail required in the first implementation.
5. Settlement availability and fee representation.
6. Immutable allocation/reversal physical structure.
7. Refund request versus refund transaction table boundaries.
8. Journal account and analytical-dimension model.
9. Reconciliation revision and carry-forward implementation.
10. Party/customer references before the shared Party module is delivered.
11. FX conversion and multi-currency settlement policy.
12. Which compatibility fields remain in existing API versions.

---

## 24. Acceptance criteria

This record is ready for approval when:

- every canonical term has one meaning;
- operational, commercial and financial states no longer overlap;
- partial payment is modeled without calling a commercial transaction pending;
- standalone payments can settle before allocation;
- A/R repayment is settlement plus allocation, not new revenue;
- refunds, reversals, voids and chargebacks are distinct;
- WND legacy statuses have deterministic compatibility mappings;
- WND Reconciliation R2 formulas, class separation, continuity and status semantics are preserved;
- zero variance cannot imply closure;
- system-prefilled actual and operator-confirmed actual remain distinguishable;
- treasury summaries exclude control and commercial-settlement classes;
- parent and child aggregates cannot be double-counted;
- hospitality folios and other packs fit without special financial semantics;
- transitions are enforceable and auditable;
- no runtime or schema change is necessary to understand the model.

Approval authorizes the next B2 artifact:

> **Logical Entity Model, Relationships and Invariants**

It does not authorize migration or runtime implementation.

---

## 25. Approval record

| Field | Value |
|---|---|
| Record | B2 Canonical Financial Vocabulary and State Machines |
| Version | 1.0 |
| Prepared | 5 August 2026 |
| Authority baseline | `a73a474` |
| Production changes authorized | No |
| Schema changes authorized | No |
| Review status | Approved |
| Approver | Project Owner |
| Approval date | 5 August 2026 |
| Notes | Approved with proven WND Reconciliation R2 invariants and acceptance scenarios incorporated; implementation remains separately gated. |
