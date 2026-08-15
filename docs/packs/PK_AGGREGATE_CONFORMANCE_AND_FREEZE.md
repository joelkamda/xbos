# PK Aggregate Conformance and Freeze

## Purpose

This milestone freezes PK0-PK6 as one coherent Pack / Template Platform. It introduces no new pack capability and no database migration. The accepted canonical head remains `pk456_pack_conformance_templates_038`.

The aggregate gate exists to prove that the individually accepted PK0123 and PK456 packages compose safely across their shared lifecycle, conformance, template, tenant, Finance, Shared Operations, XA and Platform Core boundaries.

## Constitutional rule

**Pack = composition. Pack != authority.**

A pack may declare dependencies, configuration, semantic references, XA composition metadata, connector capabilities, templates and permitted merchant overrides. It may not redefine canonical financial, Party, inventory, workflow, document, reporting, scheduling, authorization or semantic truth owned elsewhere.

## Aggregate proof

The gate proves all PK0-PK6 coverage, immutable pack and template versions, tenant-scoped exact replay, dependency and lifecycle preconditions, immutable certification evidence, deterministic template plans, explicit tenant application, explicit upgrade acceptance, merchant divergence through allowlisted overrides, and one linear migration head.

It also proves that Pack Platform production repositories write only Pack Platform persistence. PC3 semantics remain references, PC4 configuration remains a public application-plan target rather than a private-table write, PC5 remains authorization authority, SO remains source-domain authority, and XA remains presentation/composition metadata.

## Payments-only neutrality proof

The Payments-only template intentionally exposes Payments while hiding Sales, Inventory, Procurement and the Accounting workspace. The neutral Finance kernel remains required and active. "Accounting workspace OFF" therefore means presentation/workspace composition only; it never means Finance is disabled.

Outbound provider payout execution remains a product/integration adapter concern. Provider-specific routing and execution evidence may be typed and retained under edge contracts, but expense/payable/settlement/allocation/journal truth stays in frozen Finance. Existing canonical `PaymentAttempt` is not assumed reusable outside its documented PaymentIntent relationship. Provider acceptance or generic "success" does not automatically equal settlement: canonical outgoing settlement may be confirmed only at the configured provider-finality threshold. Ambiguous outcomes are fail-closed and never blindly resubmitted.

## Migration and release boundary

PK Aggregate adds no Alembic revision. Fresh reconstruction must still produce exactly one head: `pk456_pack_conformance_templates_038`. The frozen Finance prefix, Platform Core descendants, Shared Operations descendants, PK0123 and PK456 remain intact.

## Handoff

After authoritative Windows/PostgreSQL acceptance and the aggregate freeze commit/tag, the Pack Platform is ready for PA. PA may build authoring, linting, validation, compatibility and assurance workflows on top of these frozen contracts; it may not acquire source-of-truth authority from the capabilities it describes.
