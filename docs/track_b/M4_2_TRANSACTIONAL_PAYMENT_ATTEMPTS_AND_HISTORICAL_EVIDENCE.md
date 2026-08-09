# M4.2 — Transactional Payment Attempts and Historical Evidence

## Outcome

M4.2 activates payment attempts as the execution-history boundary beneath a canonical payment intent. One intent may have several attempts, and every retry remains a new row linked to the unsuccessful attempt that authorized it.

In plain language, XBOS can now remember each try separately: who tried, how it was routed, which provider reference was received, why it failed, when it timed out, and which later attempt retried it. A later success never erases an earlier failure.

## Attempt authority

`CreatePaymentAttemptCommand` binds an attempt to one tenant, organization, intent, amount, currency, method, rail, and orchestrator. Provider account and underlying-provider identity are optional routing dimensions, but an underlying provider cannot be asserted without a tenant-owned provider account.

The command rejects an amount above the intent amount, a method outside the intent policy, a terminal or expired intent, mismatched scope or currency, inactive provider configuration, and timeout beyond the intent expiry.

## State and evidence

An attempt begins in `pending`. Governed transitions support:

- processing and provider-required action;
- authorization;
- success;
- preserved failure with a failure code;
- cancellation; and
- expiration after an explicit timeout.

Every transition appends a row to `canonical_payment_attempt_transitions`. It captures the old and new states, reason, failure code, provider-reference snapshot, evidence payload, occurrence time, actor, and source identity. Completed transition replays resolve the historical transition snapshot rather than pretending the current attempt state was the earlier response.

## Database enforcement

The M4.2 migration adds retry, timeout, terminal, and failure fields to the existing canonical attempt table. Database triggers enforce contiguous transition sequences, valid state paths, timeout authority, immutable routing identity, append-only transition evidence, and consistency between the current attempt state and its latest evidence row.

Direct updates without matching evidence and deletes of attempts or transition history are rejected.

## Retry semantics

A retry is another canonical attempt. Its `retry_of_attempt_id` must reference a failed, cancelled, or expired attempt for the same intent, organization, and currency. Routing may change on the retry, permitting later provider fallback without rewriting the original attempt.

## Deliberately deferred

M4.2 does not compose mixed tenders, call provider adapters, capture callbacks, confirm settlements, create value sources, emit financial events, dispatch outbox messages, add routes, or switch WND writers. Those remain assigned to later approved M4 segments.

## Verification

The single gate verifies the migration through upgrade–downgrade–upgrade before writing test facts. Its disposable database then proves multiple attempts, provider references, failed-attempt preservation, replay and conflict behavior, timeout rejection, retry chaining, external-reference immutability, tenant isolation, append-only evidence, direct-SQL guards, exact atomic counts, and zero downstream side effects.

The development migration is applied only after the disposable rehearsal passes. Development remains empty at `m42_payment_attempts_012`.

## Next milestone

M4.3 introduces settlement authority: inbound and outbound settlement state, evidence, value date versus recorded date, and provider transaction identity. Attempt success must remain distinct from confirmed movement of value.
