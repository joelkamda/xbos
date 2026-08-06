# XBOS M0.4 — Execution Reliability and Workflow Boundary Contracts

**Record type:** Executable neutral-kernel contract
**Workstream:** Track B-FIN — Neutral Financial Spine
**Phase:** M0.4 — Reliability, Integration, and Payment-to-Fulfillment Boundaries
**Status:** Approved contract candidate
**Date:** 6 August 2026
**Depends on:** M0.1 financial events, M0.2 posting scenarios, and M0.3 canonical entities and lifecycles

## 1. Purpose

M0.4 specifies how XBOS executes financially significant commands safely when requests are retried, callbacks are duplicated, workers run concurrently, connections fail, messages are delivered more than once, or devices reconnect after working offline.

It also fixes the boundary between payment and operational fulfillment. A provider or payment orchestrator may supply evidence that value moved, but it cannot directly confirm a commercial transaction or dispatch work to an industry-pack queue.

These are database-free executable contracts. They define the behavior that later application services, persistence models, adapters, migrations, and end-to-end tests must implement.

## 2. Included files

| File | Authority |
|---|---|
| `reliability_contracts.json` | Idempotency, concurrency, provider inbox, outbox, consumer inbox, offline replay, and observability rules |
| `workflow_contracts.json` | Payment-to-confirmation and confirmation-to-fulfillment workflows, policy variants, and adapter boundaries |
| `test_financial_reliability_workflows.py` | Executable structural and cross-catalog assertions |
| `RELIABILITY_AND_WORKFLOW_CONTRACTS.md` | Human-readable scope, decisions, verification, and exit gate |

## 3. Reliability authority

### 3.1 Idempotency

Every financially significant command is identified by:

```text
(tenant_id, idempotency_scope, idempotency_key)
```

The same identity and request fingerprint returns the original result without another side effect. The same identity with a different fingerprint is an idempotency conflict. The idempotency result and authoritative business writes must commit atomically.

This prevents retries from duplicating settlements, allocations, refunds, reconciliation closes, inventory-affecting commands, or downstream fulfillment requests.

### 3.2 Concurrency

M0.4 defines explicit concurrency strategies for:

- payment-intent creation;
- provider-callback processing;
- settlement confirmation;
- payment allocation and reversal;
- refund success;
- reconciliation closing.

The contract establishes a common lock order, bounded retries for transient database failures, optimistic version checks, and operation-specific invariants. Automatic retry must retain the same idempotency identity.

### 3.3 Provider inbox

Provider callback ingress is publicly reachable because an external provider must call it, but it is not authenticated using an XBOS user bearer token. It uses provider-specific authentication such as signatures or mutual TLS, configured provider accounts, and timestamp or nonce policies.

The inbox durably captures raw evidence, authenticates it, resolves the tenant from trusted configuration or authoritative references, deduplicates it, and then routes it. XBOS must never trust an unsigned tenant identifier, guess a tenant, or let raw callback code write financial events directly.

### 3.4 Transactional outbox and consumer inbox

An authoritative state change and its outgoing message commit in the same database transaction. Delivery is at least once, so every consumer must deduplicate before applying a side effect. Delivery state is operational evidence; it is not financial truth.

### 3.5 Offline replay

Offline commands use versioned envelopes, device and tenant identity, monotonic device sequencing, idempotency keys, aggregate-version expectations, and distinct occurrence and recording times. Money and stock conflicts are explicit; they do not use silent last-write-wins behavior.

### 3.6 Observability

Correlation, causation, trace, tenant, organization-unit, actor, command, idempotency, and provider references must be traceable without exposing secrets or sensitive payloads. Replay and retry must preserve semantic lineage.

## 4. Workflow authority

### 4.1 Payment does not equal commercial confirmation

The canonical external-payment flow is:

1. create the commercial transaction, obligation, and payment intent;
2. submit a payment attempt through an adapter;
3. authenticate, deduplicate, and route provider evidence;
4. verify finality and commit the settlement and value source;
5. allocate confirmed value to the obligation;
6. evaluate the tenant's confirmation policy;
7. confirm the commercial transaction;
8. deliver a fulfillment request through the outbox;
9. let the industry pack accept and route fulfillment.

A successful attempt alone cannot bypass settlement verification, allocation, confirmation policy, or pack-owned fulfillment.

### 4.2 Confirmation policies

The contract supports:

| Policy | Meaning |
|---|---|
| `payment_required` | Confirm only after sufficient confirmed value is allocated |
| `credit_allowed` | Confirm after authorized credit terms create a valid obligation |
| `complimentary_zero_value` | Confirm a properly authorized zero-collectible transaction without a fake payment |
| `deposit_threshold` | Confirm after a configured deposit and valid treatment of the remaining balance |
| `approval_only` | Confirm after authorized non-payment approval and recorded financial treatment |

This makes the kernel usable across restaurant, hospitality, retail, service, and future industry packs without embedding one industry's queue logic in finance.

### 4.3 Orchestrator neutrality

XafPay is one supported payment-orchestrator adapter. XBOS may also support other orchestrators and direct-provider adapters. All adapters normalize provider evidence into the same canonical payment contracts.

No adapter may:

- write canonical financial events directly;
- confirm a commercial transaction directly;
- dispatch fulfillment directly;
- collapse payment method, rail, orchestrator, underlying provider, provider account, and XBOS operational account into one field.

### 4.4 Financial and workflow events remain distinct

Financial events record durable economic facts such as settlement and allocation. Workflow events coordinate activity such as callback authentication, payment-condition satisfaction, commercial confirmation, fulfillment requests, and customer notifications.

Both use immutable, versioned envelopes and transactional delivery, but workflow events must not masquerade as financial postings.

## 5. Covered scenarios

The executable workflow catalog covers:

- externally orchestrated payment-required orders;
- immediate cash payment-required orders;
- authorized credit orders;
- fully complimentary orders;
- duplicate provider callbacks;
- offline command replay.

The contracts deliberately support external channels such as WhatsApp ordering. An external channel may read tenant-authorized catalog availability, submit a command, receive payment instructions, and observe status, while the kernel retains authority over commercial confirmation and the industry pack retains authority over fulfillment.

## 6. Forbidden shortcuts

M0.4 explicitly rejects:

- raw callback to financial event;
- raw callback to commercial confirmation;
- successful attempt to fulfillment;
- payment-intent status used as a universal “paid” assignment;
- adapter writes to canonical financial tables;
- adapter dispatch directly to a restaurant, hotel, retail, or other pack queue;
- message publication before the business commit;
- consumer side effects without deduplication;
- offline last-write-wins for money or stock;
- reconciliation correction by rewriting historical financial events.

## 7. Verification

After extracting the bundle into the repository root, run:

```bat
python -m py_compile tests\contracts\test_financial_reliability_workflows.py
python -m pytest tests\contracts\test_financial_reliability_workflows.py --collect-only -q
python -m pytest tests\contracts\test_financial_reliability_workflows.py -q
python -m pytest --collect-only -q
python -m pytest -q
git diff --check
git status --short
```

Expected result at this checkpoint:

- 38 M0.4 tests collected and passing;
- 118 total tests collected and passing when the preceding M0 contracts and B1 characterization suite are present;
- no whitespace errors;
- exactly four new M0.4 files before staging.

## 8. Exit gate

M0.4 is complete when the executable contracts prove that:

```text
Retries, concurrency, duplicated delivery, provider callbacks, asynchronous messaging,
and offline replay cannot duplicate or bypass canonical financial authority; and
payment can unlock, but never impersonate, commercial confirmation and pack fulfillment.
```

## 9. Next checkpoint

M0.5 will consolidate and freeze the full executable neutral financial contract baseline. It will add cross-catalog conformance checks, run the complete suite, record the approved implementation authority, and create the M0 baseline tag before schema and service implementation begins.
