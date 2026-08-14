# SO9 — Reporting, Read Models and Report Automation

SO9 is the neutral Shared Operations authority for derived operational read models, reports, metrics and bounded report automation. It consumes canonical source-domain truth through approved public/read contracts and produces rebuildable projections. It does not become a write authority for the domains it reports on.

## Authority boundary

- PC5 remains identity, authorization and generic audit authority.
- SO6 remains workflow/task/operational-approval truth.
- SO8 remains communication, notification and delivery authority; SO9 hands report-delivery intent to SO8 through a public adapter boundary.
- SO10 remains operational scheduling, appointment, reservation and service-execution authority.
- Neutral Finance retains financial events, journals, obligations, settlement, reconciliation and Finance-owned report/read-model semantics.

A report is not source truth. A dashboard is not a command surface. A metric is not a financial posting. A scheduled report is report automation, not operational resource/service scheduling.

## Read models

A read-model definition names a neutral projection and its source authority. Refresh creates an immutable, tenant-scoped projection snapshot carrying an explicit source fingerprint, as-of time, optional source watermark, canonical payload hash and monotonically increasing revision number.

Snapshots are derived and rebuildable. Deleting every SO9 projection must not erase canonical source-domain facts. SO9 does not query another module's private tables through its public service contract; source adapters are responsible for supplying authorized derived rows.

## Metrics

Metric definitions are tenant-scoped, read-model-bound derived calculations. SO9 supports neutral count, sum, average, minimum and maximum aggregation over snapshot rows. Metric values are projections only. A financial-looking metric does not acquire accounting authority merely because SO9 can display it.

## Reports and run history

A report definition references one read model, optional derived metrics and a parameter schema. A report run binds to one immutable projection snapshot and stores the exact parameters, deterministic result payload, SHA-256 and generation time. Runs are append-only.

Legacy `core.domain.reports.ReportsService` and `/kernel/reports` remain compatibility surfaces. Their tenant-specific TreasuryLog, Sale, branch and taxonomy assumptions are not promoted to neutral SO9 law.

## Report automation

Automation rules bind a report to a neutral trigger code/configuration and may request delivery through SO8. SO9 stores automation definition and immutable execution history. It does not implement a general workflow engine, message provider or operational scheduling engine.

When delivery is enabled, SO9 calls a provider-neutral handoff adapter with a deterministic idempotency key derived from tenant + automation identity + execution identity. Distinct SO9 command keys therefore cannot duplicate delivery for the same logical automation execution. SO8 remains canonical delivery/retry authority.

## Finance boundary

Finance-owned statements, traces, reconciliation reports and financial projections remain Finance authority. SO9 may consume an explicitly approved financial read contract as one source authority, but it may not query private Finance tables to reconstruct accounting truth and may never write financial events, journal entries, obligations, settlements or payments.

## Neutrality

The same SO9 contracts support field-service operational performance reporting and clinical quality reporting without changing SO9 source. Industry terminology, source adapters, report composition and dashboard labels belong in packs/configuration/XA.
