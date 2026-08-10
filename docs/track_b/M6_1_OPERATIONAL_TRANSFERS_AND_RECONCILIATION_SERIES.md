# M6.1 — Operational Transfers and Reconciliation Series

M6.1 activates the already-approved neutral `VALUE_TRANSFERRED` financial-event type as the canonical treasury movement between two M6.0 operational accounts. A transfer is not revenue or expense: it credits the source operational asset and debits the destination operational asset in one caller-owned transaction.

## Transfer authority

`TransactionalOperationalTransferEngine.record` resolves and locks both accounts in deterministic database order, verifies tenant, organization, currency, leaf eligibility and account lifetime, then delegates to the canonical event, idempotency, outbox and balanced-posting engines. One immutable event carries both account identifiers; source-only or destination-only persistence is therefore impossible through this authority.

Commands require positive exact amount, occurred/value/business time, provenance, evidence, correlation/causation, actor, source record and idempotency identity. Identical replay resolves the same event, outbox and journal. Changed content under the same identity fails closed.

Corrections use the existing append-only `FINANCIAL_FACT_REVERSED` authority. Accounts invert exactly, cumulative reversal capacity is locked, and the original event and journal remain unchanged.

## M6.0 expected-balance integration

No balance table or competing balance projection is introduced. The accepted transfer is already visible to M6.0 through canonical `financial_events`: the source is an outflow and the destination is an inflow. A reversal carries inverse accounts and compensates directionally.

## Ordered reconciliation series

`operational_account_reconciliation_series` is a read-only explanatory view over M6.0 anchors and actual observations plus transfer and transfer-reversal events. Queries are tenant, organization and account scoped and ordered by fact time, kind rank, recorded time, public identity and direction. The view never creates, closes or reconciles a window and never replaces event or balance authority.

## Deferred

Windows, predecessor continuity, shift/calendar attribution, correction cascading, close/reopen protection, bank/A/R/A/P reconciliation and reports remain M6.2–M6.4 scope.
