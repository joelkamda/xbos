# SO8 — Communications, Notifications, Integration Delivery and Offline Support

SO8 is the provider-neutral operational delivery authority defined prospectively by the frozen SO0 constitution. It owns operational command idempotency, delivery jobs, attempts/retries, inbound integration evidence, notification/integration envelopes, and offline synchronization queues. It does not own the business truth being communicated.

## Authority boundary

- PC5 remains identity, authorization, protected-action approval and audit authority.
- SO6 remains workflow/task/operational-approval truth.
- SO7 remains logical-document, file-version and evidence authority; SO8 stores only optional public version references.
- Neutral Finance retains financial idempotency, provider financial callbacks, the transactional financial outbox, settlement and posting truth.
- SO9 remains operational reporting/read-model automation; SO10 remains scheduling/reservation/service-execution authority.

A notification is not workflow completion. A webhook/integration delivery is not source-domain acceptance. A delivery receipt is not financial settlement. An offline queue is not canonical business state.

## Delivery jobs and attempts

A delivery job is a tenant-scoped operational envelope with neutral kind/channel codes, destination reference, optional subject and SO7 version references, JSON payload evidence, canonical payload hash, availability time, bounded maximum attempts and explicit lifecycle. Dispatch workers claim a job through an optimistic row version and lease. Each attempt is append-only. Retry timing is supplied explicitly by resolved policy/adapter behavior; SO8 does not invent one universal backoff policy.

Lifecycle is `pending -> in_progress -> delivered | retry_wait | dead_letter`; cancellation is allowed only before active dispatch. Retryable failure returns the job to `retry_wait` only while attempt capacity remains.

## Inbound integration evidence

Inbound envelopes are immutable and uniquely keyed by tenant, source code and external event key. A redelivery with the same external identity and evidence is deduplicated even if transported under a different command key; changed evidence under the same external identity conflicts. Recording the envelope does not execute source-domain transitions.

## Offline synchronization

SO8 records tenant-scoped offline command intent tied to a PC5 device public identity, client sequence, operation code, target public authority/reference, payload hash and optional base version. The queued command remains pending server revalidation. Resolution records only `applied`, `conflict`, or `rejected` evidence and result reference; SO8 does not bypass the target module public contract or make client state canonical. Queue and resolution history is append-only.

## Compatibility

Legacy `core.shared.idempotency`, `idempotency_keys`, and the `core.events.event_dispatcher` stub remain compatibility-only. New SO8 operational commands use exact tenant-scoped command fingerprints. Financial `idempotency_records` and `outbox_messages` remain frozen Finance authority and are never reused as generic SO8 persistence.

## Storage, providers and dependencies

Providers are adapters. SO8 does not hard-code Twilio, WhatsApp, SendGrid, Firebase, Kafka, S3 or another provider/runtime. No production dependency is added. Documents remain SO7 references, not duplicated attachment stores.

## Neutrality

The same contracts support field-service dispatch/offline capture and clinical communications/offline notes without changing SO8 source. Industry terminology and provider choices belong in packs/configuration/adapters.
