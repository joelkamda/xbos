# M8.2 External-provider and infrastructure failure resilience

M8.2 is a schema-neutral adversarial proof over the accepted M2–M8.1 authorities. It adds no provider ledger, settlement authority, migration, live provider call, writer rerouting, or cutover authorization.

The gate proves that XafPay's representative adapter verifies the exact raw callback bytes with HMAC, rejects malformed or tampered input, scopes provider evidence to tenant/organization/account, deduplicates identical provider events, rejects conflicting bytes under the same event identity, and preserves terminal chronology when late evidence arrives.

Timeout, provider unavailability, retryable failure, and unknown outcomes remain explicit uncertainty. They are retryable but cannot settle. Only authoritative success evidence can drive the existing canonical settlement path.

The disposable PostgreSQL rehearsal injects a dependent settlement persistence failure after callback processing begins. The existing nested transaction must remove callback, attempt-transition, settlement, and idempotency residue. A subsequent authoritative retry must produce exactly one settlement. A separate canonical-event rollback proves event, idempotency, and transactional-outbox atomicity. The rehearsal also asserts that no journal or allocation is manufactured by provider uncertainty.

The legacy WND webhook characterization remains outside this milestone's redesign scope. M8.2 tests the accepted provider-neutral orchestration boundary; R6 continues to own live WND cutover.
