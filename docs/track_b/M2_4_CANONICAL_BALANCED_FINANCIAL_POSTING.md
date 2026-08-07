# M2.4 — Canonical Balanced Financial Posting

**Track:** B — Neutral Financial Spine

**Parent checkpoint:** `59f3747` / `m23_reversal_capacity_005`

**Target revision:** `m24_balanced_posting_006`
**Status:** Executable implementation candidate

**Package revision:** 2

Revision 2 supersedes the original M2.4 delivery package. It makes joined
journal projections unambiguous, fixes account-binding result collection,
fails closed when duplicate primary journals are encountered, and constructs
persistence records from explicit fields. Contract tests lock these behaviors.

## 1. Purpose

M2.4 converts one accepted canonical financial event into a deterministic,
balanced, immutable journal entry. It is the first executable bridge between
the neutral event truth established in M2.0–M2.3 and formal double-entry
accounting.

The slice remains deliberately disconnected from WND writers. It proves the
neutral accounting mechanism without changing any current operational writer.

## 2. Authority chain

M2.4 executes three approved M0 contracts:

1. `financial_event_catalog.json` determines whether an event is posting
   eligible and which posting profiles are permitted.
2. `account_role_catalog.json` determines the account type, normal balance and
   operational-account-link policy allowed for each abstract role.
3. `posting_scenarios.json` fixes the expected debit/credit semantics.

The executable profile map is tested for exact parity with the event catalog.
The executable account-role policy is tested for exact parity with the role
catalog. A future catalog change therefore fails the M2.4 contract suite until
its executable interpretation is deliberately revised.

## 3. Structural additions

M2.4 installs six empty formal-accounting tables:

- `ledger_accounts`
- `accounting_periods`
- `ledger_account_role_bindings`
- `journal_entries`
- `journal_lines`
- `journal_entry_event_links`

The migration creates no tenant accounts, periods, role bindings, financial
events or journals. Those remain explicit tenant configuration and runtime
facts.

### 3.1 Ledger accounts

Ledger accounts belong to a tenant and legal-entity organization unit. Their
type, normal balance, currency policy and effective dates are explicit. They
are separate from operational financial accounts such as a particular till,
bank account or provider balance.

### 3.2 Account-role bindings

Posting profiles use neutral roles rather than hard-coded account IDs. A role
binding resolves:

```text
tenant
+ legal entity
+ account role
+ binding key
+ currency
+ business date
→ one ledger account
```

The default binding key is `default`. A tenant, country pack or industry pack
can select a more specific binding through:

```json
{
  "account_role_binding_keys": {
    "classified_revenue": "food-sales"
  }
}
```

This preserves the depth needed for restaurant categories, retail inventory,
negotiated free-standing merchandise, provider settlements, taxes and future
industry-specific classification without placing industry semantics in the
neutral engine.

Operational-link rules are enforced. For example,
`cash_bank_or_provider_asset`, `source_operational_asset` and
`target_operational_asset` must resolve through an operational account carried
by the event. Classified revenue and expense roles are forbidden from doing
so.

## 4. Posting profile selection

When an event type has exactly one approved profile, the engine may select it
automatically. When several profiles are permitted, the command must identify
one explicitly:

```json
{
  "posting_profile_code": "inbound_settlement"
}
```

The engine rejects a profile belonging to another event type. It also rejects
missing selection for multi-profile event types.

`OBLIGATION_OPENED` remains explicitly non-posting because the event catalog
marks it as a workflow fact rather than a posting fact.

## 5. Posting execution

For a template profile, M2.4:

1. locks the authoritative financial event;
2. returns the existing primary journal on replay;
3. resolves exactly one open accounting period covering the business date;
4. resolves each account role to one effective ledger binding;
5. validates account type, normal balance, currency and operational linkage;
6. inserts a draft journal header;
7. inserts debit and credit lines;
8. links the journal to the financial event;
9. marks the complete entry posted.

The engine never commits. Transaction ownership remains with the application
service.

## 6. Atomic event-and-posting boundary

`AtomicPostedFinancialEventEngine` composes the M2.2/M2.3 transactional event
engine and the M2.4 posting engine inside one savepoint. The following effects
therefore succeed or fail together:

- idempotency reservation/completion;
- immutable financial event;
- transactional outbox message;
- journal entry;
- journal lines;
- event-to-journal link.

If period resolution or account binding fails, no stranded event, outbox row or
idempotency completion may survive.

This new orchestrator is opt-in. Existing WND code continues using its present
writers until a later controlled cutover slice.

## 7. Corrections and reversals

M2.3 authorizes and limits original-linked corrections. M2.4 gives those
corrections accounting meaning.

An inverse-original profile:

- locks and loads the original event;
- requires an authoritative posted journal for that event;
- reuses the original ledger accounts;
- changes every debit to a credit and every credit to a debit;
- posts the correction amount, including an authorized partial correction.

M2.4 supports the approved two-line template shape. General proportional
multi-line reversal is deferred rather than guessed.

## 8. Database enforcement

Application validation is not the final authority. PostgreSQL also enforces:

- exactly one positive side per journal line;
- non-negative debit and credit values;
- same-tenant composite foreign keys;
- at least two lines for a posted entry;
- transaction-currency debit equals credit;
- base-currency debit equals credit;
- immutability of posted headers and lines.

Balance validation uses deferred constraint triggers so a transaction may build
a draft header and its lines before marking the entry posted. Direct SQL cannot
commit an unbalanced posted entry.

Corrections append new facts and journals. Posted accounting truth is never
edited in place.

## 9. M2.4 currency boundary

This slice intentionally proves same-currency posting only:

```text
transaction currency = base currency
fx rate = 1
```

Multi-currency translation, rate sourcing, realized/unrealized FX differences
and rounding-residual allocation require a separate approved contract. M2.4
fails closed when a different base currency is requested.

## 10. Disposable proof

The verifier uses only:

```text
xbos_track_b_m24_posting_test
```

It proves:

- clean upgrade from the canonical lineage;
- downgrade to M2.3 and re-upgrade;
- balanced commercial-recognition posting;
- balanced settlement posting;
- idempotent event and journal replay;
- partial inverse-original posting;
- rejection when no period is open;
- rejection when an account role is unbound;
- rollback of event, idempotency and outbox effects after posting failure;
- direct-SQL unbalanced-journal rejection;
- posted-line immutability;
- final atomic row counts.

The named database is retained on failure and dropped only after all proofs
pass.

## 11. Explicit deferrals

M2.4 does not introduce:

- WND writer cutover;
- development financial events;
- broker/outbox dispatch;
- tenant chart-of-accounts user interfaces;
- posting approval workflows;
- journal batching;
- arbitrary multi-line allocation templates;
- foreign-exchange translation;
- period-overlap exclusion extension;
- reporting projections.

These are later slices. Their absence does not weaken the M2.4 contract; it
keeps this checkpoint reviewable and reversible.

## 12. Acceptance

M2.4 is acceptable only when:

- Alembic has one head: `m24_balanced_posting_006`;
- the disposable verifier reports every proof as `PASS`;
- development remains at 20 event-catalog rows and zero event/outbox/journal
  facts before and after the structural migration;
- all contract and characterization tests pass;
- `git diff --check` reports no error;
- only the M2.4 implementation files are committed.
