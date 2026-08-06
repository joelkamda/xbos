# XBOS M0.3 — Canonical Financial Entity and Lifecycle Contracts

**Workstream:** Track B-FIN — M0 Executable Neutral Contracts

**Slice:** M0.3

**Contract version:** v1, revision 1

**Status:** Approved executable design candidate

**Date:** 6 August 2026

## Purpose

M0.3 converts the approved B2 logical entity model and state machines into database-free, machine-testable contracts. It freezes what the canonical financial records mean and which transitions are legal before M1 introduces tables, SQLAlchemy models, services or Alembic migrations.

This slice deliberately contains no production implementation.

## Files

- `entity_contracts.json` — 20 canonical entity contracts covering ownership, required fields, money fields, mutation policy, idempotency identity, relationships and invariants.
- `lifecycle_contracts.json` — 10 state machines, six derived-condition vocabularies, the universal transition-command boundary and ten cross-machine rules.
- `tests/contracts/test_financial_entity_lifecycles.py` — 26 contract tests.

## Entity boundaries frozen by this slice

The contract covers:

1. commercial transaction and line snapshots;
2. obligations;
3. payment intents, attempts, provider accounts and callbacks;
4. operational accounts, settlements and value sources;
5. allocations and append-only reversals;
6. refunds;
7. immutable financial events;
8. journal entries and lines;
9. reconciliation series, windows and lines; and
10. transactional outbox messages.

Each authoritative record is tenant-scoped, organization-scoped, time-aware, source-traceable and correlation-aware. Money uses exact decimal strings plus an ISO currency code. Committed facts are corrected through compensating records rather than destructive edits.

## Lifecycle boundaries frozen by this slice

The state-machine catalog defines:

- Commercial Transaction;
- Financial Obligation;
- Payment Intent;
- Payment Attempt;
- Payment Settlement;
- Payment Allocation condition;
- Payment Refund;
- Journal Entry;
- Reconciliation Window; and
- Transactional Outbox Message.

State changes occur only through commands that validate tenant scope, organization scope, actor permission, evidence, idempotency and concurrent version.

## Critical rules

### Lifecycle and financial condition are separate

A commercial transaction has no `paid` state. Payment and collection conditions derive from obligations, settlements, allocations, reversals, allowances and excess value.

### Provider success is evidence, not automatic accounting

A provider callback is immutable evidence. A succeeded payment attempt is not universally equivalent to confirmed settlement. External settlement requires authenticated evidence and channel-specific finality.

### Settled value must precede allocation

Only confirmed available value may be allocated. Allocation cannot exceed the available value source or the obligation balance. Reversals are append-only.

### Refund is a multi-record workflow

A successful refund requires a confirmed outgoing settlement, refund applications and allocation reversal when the returned value had been allocated. The original settlement and allocation remain immutable.

### Journals are formal projections

Posted journal entries balance per currency, link to canonical financial events and become immutable. Corrections use separate reversing and replacement entries.

### Reconciliation has four independent axes

Reconciliation keeps these distinct:

1. workflow state;
2. closure readiness;
3. variance condition; and
4. actual-closing provenance.

Zero variance does not mean closed. A blocked window cannot close. Required middle windows cannot be skipped. The next opening equals the previous actual close within the same series. Correcting an earlier window carries forward without overwriting later observed counts.

## Verification

After extracting the bundle at the repository root, run:

```bat
python -m py_compile tests\contracts\test_financial_entity_lifecycles.py
python -m pytest tests\contracts\test_financial_entity_lifecycles.py --collect-only -q
python -m pytest tests\contracts\test_financial_entity_lifecycles.py -q
python -m pytest --collect-only -q
python -m pytest -q
git diff --check
git status --short
```

Expected results on the current branch:

- 26 M0.3 tests collected and passing;
- 80 tests in the complete suite: 18 characterization + 18 M0.1 + 18 M0.2 + 26 M0.3;
- no database is required for the 62 contract tests;
- the 18 characterization tests continue to use the isolated PostgreSQL test database.

## M0.3 exit gate

M0.3 is complete when:

1. both JSON contracts parse;
2. all 26 new contract tests pass;
3. all 80 repository tests pass;
4. entity relationships and state-machine references resolve;
5. canonical financial emissions resolve to the approved event catalog;
6. no production model, migration or service has been introduced; and
7. the reviewed files are committed, pushed and checkpointed.

## Next slice

M0.4 will make idempotency, replay, concurrency, provider inbox/outbox and workflow-trigger boundaries executable. It must consume these M0.3 entities and commands rather than inventing parallel meanings.
