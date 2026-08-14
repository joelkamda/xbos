# SO6 — Workflows, Tasks and Operational Approvals

SO6 establishes neutral operational execution primitives without duplicating Platform Core security or downstream scheduling/document/delivery authorities.

## Authority equation

- PC5 decides whether an actor is authorized and owns security/control approvals.
- SO5 owns operational resources and assignments.
- SO6 owns operational workflow instances, tasks, task assignment references, and business-operational approval decisions.
- SO7 owns documents/files/evidence lifecycle later.
- SO8 owns communications and notification delivery later.
- SO9 owns operational reporting/read-model automation later.
- SO10 owns scheduling, appointments and reservations later.
- Neutral Finance remains canonical for economic truth.

Operational approval never grants permission. Workflow completion never creates a financial event, obligation, journal, settlement or payment.

## Core model

A workflow is tenant-scoped operational context around a stable subject reference. Tasks are explicit work items within a workflow. Tasks may reference an SO5 resource, but assignment is not an auth role. Operational approvals are append-only decision facts within the workflow and remain distinct from PC5 protected-action approval.

All mutation commands are exact-replay idempotent. The same command key with changed content fails. Workflow/task/approval state uses optimistic versions and PostgreSQL row locks on the canonical mutable row. History is append-only.

## Lifecycle

Workflow: `open -> completed | cancelled`.

Task: `pending -> in_progress | completed | cancelled`, and `in_progress -> completed | cancelled`.

Operational approval: `pending -> approved | rejected`; workflow cancellation may explicitly cancel pending approval work.

A workflow cannot complete while active tasks or pending operational approvals remain.

## Boundaries

Due dates and priority are execution metadata, not a calendar engine. Evidence is a bounded external reference, not a file store. SO6 exposes no notification transport, generic automation runtime, security role writer, PC5 approval writer or financial writer.

## Neutrality

The same SO6 source supports field-service work cases and clinical review cases. Industry terms are profile/pack concerns and are not active defaults in SO6 source.
