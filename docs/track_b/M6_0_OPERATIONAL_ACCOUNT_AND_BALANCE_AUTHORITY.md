# M6.0 — Operational-account and balance authority

M6.0 consolidates original roadmap items M6.0-M6.3: operational-account authority, expected balance, actual balance with provenance, and variance. It establishes the first treasury-control boundary without implementing transfers, reconciliation windows, formal close, or matching.

## Operational-account authority

`operational_financial_accounts` remains the canonical account registry introduced by the neutral foundation. M6.0 adds an idempotent authority record for accounts created through the typed engine and database protection for stable identity:

- tenant and organization scope;
- parent hierarchy;
- account class and type;
- code and currency;
- aggregation role; and
- opening timestamp.

A parent must be an active `parent_aggregate` account in the same tenant, organization, and currency. Expected and actual balance facts bind only leaf accounts. Provider accounts remain credentials/orchestration identities and cannot substitute for operational financial accounts.

## Expected balance

Every leaf account receives at most one immutable opening anchor. The deterministic expected balance at a cutoff is:

`anchor balance + canonical target-account inflows - canonical source-account outflows`

Only immutable `financial_events` through the requested `occurred_at` cutoff supply movement authority. Journal rows, payment-settlement rows, provider components, and operator observations are not alternative movement ledgers. Corrections already represented as canonical counter-events therefore affect expectation without rewriting history.

The opening anchor is a starting control fact, not a receipt, payment, transfer, revenue event, or journal posting. It requires provenance and hashed evidence.

## Actual balance and provenance

An actual balance is an append-only observation with one of three explicit provenance classes:

- `operator_counted`;
- `external_statement`; or
- `provider_confirmed`.

Every observation requires evidence, actor identity, tenant/organization/account/currency scope, and a timezone-aware observation timestamp. Multiple observations are retained. As-of queries select the latest observation at or before the cutoff.

## Variance

Variance is always derived:

`actual balance - expected balance`

It is never entered by an operator. When no actual observation exists at the cutoff, actual and variance are `null`, not zero. Zero variance is not a close state and creates no authority to close a period; formal workflow belongs to M6.3.

## Transaction and replay behavior

Account, anchor, and observation commands use tenant-scoped idempotency identities. Identical replay returns the original record. Changed content conflicts. Account creation and its authority record share one transaction. Outer rollback removes uncommitted M6.0 facts. Anchors, observations, and account authority records reject update and delete.

## Deferred scope

M6.0 does not implement operational transfers, reconciliation series/windows, predecessor continuity, shift attribution, close/reopen, bank/A/R/A/P matching, or reconciliation reports. It adds no public route, dispatches no outbox message, and creates no financial event in the development database.

## Acceptance evidence

`scripts/verify_m60_operational_balance_authority.py create-and-verify` clones the empty development target, rehearses upgrade/downgrade/upgrade, account hierarchy, immutable anchors, event-derived expectation, actual provenance, cutoff behavior, variance, replay/conflict, scope isolation, direct-SQL mutation rejection, rollback, and exact disposable cleanup.
