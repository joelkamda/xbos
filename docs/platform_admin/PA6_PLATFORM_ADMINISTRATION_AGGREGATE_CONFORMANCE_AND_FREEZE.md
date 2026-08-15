# PA6 — Platform Administration Aggregate Conformance and Freeze

## Purpose

PA6 freezes PA0-PA5 as one coherent Platform Administration and Merchant Lifecycle layer. It introduces no new administrative capability and no database migration. The accepted canonical migration head remains `pa45_support_recovery_health_040`.

The aggregate gate exists to prove that merchant administration, commercial subscriptions, usage/quota evidence, onboarding/readiness, delegated support, break-glass, recovery and derived health compose safely without taking authority away from Platform Core, Pack Platform, Shared Operations or Neutral Finance.

## Constitutional rule

**Platform Administration orchestrates public authorities; it does not redefine them.**

PA owns administrative progression, commercial plan/subscription intent, usage evidence, onboarding coordination, bounded support/recovery evidence and derived health snapshots. PC1 remains tenant lifecycle authority. PC4 remains effective configuration and entitlement authority. PC5 remains identity, authorization and audit authority. PK remains pack/template composition authority. Finance and Shared Operations retain their own transactional and operational truth.

## Aggregate proof

The PA6 gate proves a complete merchant administration journey on one disposable PostgreSQL database: merchant registration, plan/subscription activation, entitlement projection, usage/quota evaluation, onboarding/readiness, operational readiness, delegated support, recovery evidence, health observation and support closure.

The proof explicitly checks that:

- subscription entitlement projection is commercial intent rather than runtime entitlement truth;
- quota breach does not silently revoke entitlement or create a financial effect;
- onboarding readiness consumes PC1/PC4/PC5/PK evidence and does not itself provision, authorize or apply templates;
- delegated support remains tenant-scoped, time-bounded and PC5-authorized;
- break-glass remains stricter than ordinary delegated support;
- recovery records are evidence and coordination, never replacement source truth;
- merchant/platform health remains derived observation and cannot authorize mutation;
- PA persistence remains tenant-safe and exact-replay/idempotent;
- Finance, Shared Operations, Pack Platform and dependency authority remain unchanged.

## Migration and release boundary

PA6 adds no Alembic revision. The frozen PA migration prefix is:

`pk456_pack_conformance_templates_038 -> pa0123_merchant_lifecycle_subscriptions_onboarding_039 -> pa45_support_recovery_health_040`

Future milestones may add legal descendants, but may not rewrite or fork this frozen prefix.

## Handoff

After authoritative Windows/PostgreSQL acceptance and PA6 freeze, Platform Administration is complete. The next master-plan sequence is R0-R5. R0-R5 must consume the frozen public authorities rather than reopening PA, PK, SO, XA, PC or Finance without a proven invariant defect.
