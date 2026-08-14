# ADR 0019 — SO8 operational delivery is separate from the financial outbox

## Status
Accepted for SO8 candidate implementation.

## Decision
SO8 owns provider-neutral operational delivery jobs, append-only delivery attempts, immutable inbound integration evidence, exact operational command idempotency and offline synchronization intent/history. Neutral Finance continues to own `idempotency_records`, `outbox_messages`, provider financial evidence, settlement and transactional posting atomicity.

SO8 therefore uses its own persistence and public contracts. It may carry a source-domain public reference or SO7 document-version public reference, but it does not query or mutate another module's private tables. Providers are adapter implementations, not kernel authority.

Offline intent is never canonical source-domain truth. Server-side revalidation and target-module public contracts remain mandatory before any target operation is considered applied.

## Consequences
This resolves the SO0 constitutional compatibility note that older PC0/XA artifacts named SO9 as the future delivery/offline owner. SO8 is the canonical delivery/retry/offline authority; SO9 remains reporting/read-model automation. Legacy helpers are preserved until controlled convergence and no Finance bytes or dependencies change.
