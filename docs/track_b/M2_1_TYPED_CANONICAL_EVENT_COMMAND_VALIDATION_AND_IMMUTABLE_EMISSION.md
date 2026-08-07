# XBOS Neutral Operating Kernel — M2.1 Typed Canonical Event Command, Validation and Immutable Emission

**Record type:** Implementation and verification record

**Workstream:** Track B-FIN — Neutral Financial Spine

**Milestone:** M2 — Canonical Event Engine

**Slice:** M2.1 — Typed command and immutable emission

**Status:** Implementation candidate

**Date:** 6 August 2026

**Parent commit:** `49315ae` — M2.0 approved catalog seed

## 1. Outcome

M2.1 introduces the first executable service capable of appending a canonical
financial fact to `financial_events`. The service accepts a typed neutral
command, generates a byte-stable semantic fingerprint, validates the command
against the effective catalog and tenant-scoped source records, and performs an
immutable insert without committing the caller's transaction.

Identical replay returns the original event. Reuse of the same idempotency
identity for altered semantic content is rejected.

This engine is exercised only in a disposable neutral-kernel database. WND
writers remain unchanged.

## 2. Components

### 2.1 Pure event contract

`core/domain/finance/event_contract.py` defines:

- `CanonicalFinancialEventCommand`;
- `CatalogEventPolicy`;
- deterministic decimal, timestamp and JSON canonicalization;
- the SHA-256 command fingerprint;
- typed validation failures with stable codes;
- catalog amount, economic-role, original-event, classification and account
  presence rules.

The pure contract has no database, HTTP, provider, WND or industry-pack
dependency.

### 2.2 Repository

`core/domain/finance/event_repository.py` performs:

- effective catalog lookup;
- tenant, organization, currency-policy and source-record checks;
- actor and operational-account checks;
- original-event tenant, organization and currency checks;
- replay lookup;
- immutable insert with `RETURNING`;
- nested-transaction recovery for a concurrent duplicate insert.

The repository neither commits nor rolls back the caller's outer transaction.

### 2.3 Application service

`CanonicalFinancialEventEngine.emit(session, command)` owns the validation
order but not the database transaction. This permits a later aggregate service
to commit its authoritative business record, financial event, idempotency
result and outbox message atomically.

## 3. Canonical fingerprint

The fingerprint covers every semantically material command field. It excludes
server-assigned `recorded_at` and transport-only retry or tracing information.

Canonicalization rules:

```text
JSON keys                 sorted
JSON separators           compact
Unicode                   preserved
decimal                   normalized plain string
occurred_at               UTC ISO-8601 ending in Z
UUID                      lowercase canonical string
business_date             ISO date
algorithm                 SHA-256
```

Equivalent JSON key order, decimal scale and timezone representation therefore
produce the same fingerprint. Any change to amount, currency, source,
classification, correlation, actor or another material field changes it.

## 4. Idempotency behavior

Identity:

```text
(tenant_id, idempotency_scope, idempotency_key)
```

The first successful insert stores its command fingerprint under the reserved
`metadata._kernel` namespace.

- Same identity and same fingerprint: return the original ID and public ID,
  with `replayed=true`; no second write.
- Same identity and different fingerprint: raise
  `FinancialEventIdempotencyConflict` with code `idempotency_conflict`.
- Concurrent duplicate insert: isolate the unique-constraint race in a savepoint
  and then apply the same replay decision to the winning row.

M2.2 will add the broader `idempotency_records` command reservation and atomic
outbox message.

## 5. Validation boundary

M2.1 rejects an event before insertion when any of these conditions fail:

- required IDs and strings;
- finite decimal amount;
- timezone-aware occurrence time;
- actor user or actor service;
- approved and effective event type/version;
- catalog amount and economic-role policy;
- original-event presence policy;
- required classification roles;
- source/target account presence policy;
- tenant existence;
- active organization unit under the same tenant;
- active currency plus effective tenant currency policy;
- non-retired, same-tenant source of an allowed aggregate type;
- same-tenant active actor user when supplied;
- same-tenant, same-organization, same-currency operational accounts active at
  the event occurrence time;
- same-tenant, same-organization and same-currency original event.

Cross-organization behavior remains forbidden unless a later explicit policy
permits it.

## 6. Database authority

Application validation provides clear domain errors. PostgreSQL remains the
last authority through:

- tenant-scoped foreign keys;
- unique public and idempotency identities;
- catalog foreign key;
- amount-policy trigger;
- JSON, actor, account and evidence constraints;
- immutable update/delete trigger.

The engine does not duplicate or weaken those protections.

## 7. Disposable verification

The M2.1 verifier reconstructs a fresh canonical database, installs two neutral
tenants and neutral source/account fixtures, then proves:

- deterministic fingerprint storage;
- one commercial recognition insert;
- identical replay returns the original row;
- altered replay is rejected;
- a cross-tenant source is rejected;
- missing classification is rejected;
- inbound settlement requires its target account;
- value transfer requires distinct source and target accounts;
- exactly three valid events commit;
- direct update is rejected by PostgreSQL;
- no outbox message is created;
- the disposable database is dropped after success.

## 8. Deliberate exclusions

M2.1 does not yet implement:

- full command reservation in `idempotency_records`;
- transactional outbox creation;
- reversal-capacity aggregation;
- taxonomy bridge insertion;
- journal posting;
- WND integration;
- provider callback handling;
- historical transformation.

## 9. Next slice

M2.2 will make authoritative command reservation, event insertion and outbox
creation one transaction. It will prove that rollback leaves none of the three
records partially committed and that identical replay returns the same result
without duplicating an outbox message.
