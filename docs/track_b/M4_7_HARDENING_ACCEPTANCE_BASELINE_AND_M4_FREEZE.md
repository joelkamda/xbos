# M4.7 — Hardening, acceptance baseline, and M4 freeze

M4.7 freezes the provider-neutral payments, settlement, and orchestration milestone. It adds no migration and no runtime payment capability.

## Frozen capability chain

- M4.0 establishes provider-neutral payment requests, intents, tenders, attempts, callbacks, settlements, and reversals while retaining legacy coexistence.
- M4.1 supplies typed, idempotent payment requests and intents, including standalone and obligation-linked payments.
- M4.2 preserves every payment attempt, failure, timeout, retry, and provider reference.
- M4.3 preserves settlement evidence, value dates, finality, failure, and reversals.
- M4.4 supports cash, MTN Mobile Money, Orange Money, banks, cards, split tender, payment links, standalone payments, and delayed settlement.
- M4.5 keeps XafPay protocol translation outside the finance kernel and enforces signed callback replay, conflict, ordering, and tenant scope.
- M4.6 records provider fees, reserves, releases, chargeback adjustments, net position, canonical events, outbox messages, and balanced journals without rewriting gross payment truth.

## Acceptance strategy

Historical capability exercises run in isolated clones of the current linear M4 head. This avoids treating an earlier milestone revision as the permanent development head while still executing its behavioral verifier against the released descendant schema. M4.0 separately rehearses upgrade/downgrade/upgrade from the M3 parent.

Release hardening also removes wall-clock dependencies from the M4.3 value-date and M4.4 delayed-settlement rehearsals. The verifiers now prove their fixed contractual value dates directly and separately prove that recording dates exist, so the gate remains deterministic even when those dates happen to be equal.

The aggregate verifier also proves:

- callback replay is stable and altered replay conflicts;
- invalid signatures and cross-tenant callbacks fail closed;
- an injected provider timeout propagates without fabricating success;
- mixed tender totals equal the intent and cash works without provider authority;
- development stays at `m46_provider_financials_015` with all payment and financial fact tables empty;
- all seven named disposable databases are absent before the run and dropped after success; and
- M2, M3, and M4 manifests and the complete single migration lineage remain valid.

## Release boundary

M4.7 does not call a live gateway, dispatch the outbox, seed development payment data, add public routes, modify WND writers, or introduce a migration. Successful acceptance is committed and tagged `track-b-m4-payments-settlement-orchestration-20260810`.
