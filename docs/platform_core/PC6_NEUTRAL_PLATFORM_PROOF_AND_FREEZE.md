# PC6 Neutral-Platform Proof and Freeze

PC6 covers PC6.1–PC6.12 as a proof milestone. It introduces no schema migration: both the previous and accepted canonical heads are `pc5_identity_policy_audit_025`.

The synthetic `NORTHSTAR` profile proves materially different tenant structure and operating context without a kernel fork: a Canadian cooperative, CAD/en-CA localization, a virtual primary location, Toronto time, a 04:30 business boundary, weekday service windows, appointment configuration, tenant terminology, and organization-scoped security. It is a bounded proof artifact, not a PK pack or template engine.

`core.platform.neutral_proof` orchestrates only the published PC1–PC5 authority facades. The profile and portable envelope reject credentials, secrets, sessions, tokens and financial data. Restore is driven by stable profile identity and public codes; database-local IDs are reference-only snapshots.

`requirements-prod.txt` is the canonical production Python dependency authority. Every entry is exactly pinned to the accepted Python 3.13.3 operator environment. Test dependencies remain separate. The acceptance gate constructs a clean disposable environment, installs production pins before test pins, and performs runtime import checks.

The PC6 verifier performs static proof in any source archive. Its acceptance mode uses only local disposable PostgreSQL databases, reconstructs the canonical lineage, bootstraps and restores the profile, attacks cross-tenant boundaries, verifies public authorization and audit, performs PostgreSQL backup/restore, checks source immutability, and drops disposable databases only after success. Development adoption, full regression and the final single-gate result remain operator-controlled.

Canonical `main:app` construction is database-state independent. Alembic alone owns schema installation, while PC5 owns canonical identity and authorization. The legacy `init_database()` and `seed_rbac()` helpers remain explicit compatibility utilities, but application import never executes DDL, seeds the legacy `roles` table, or assumes historical tenant state. The disposable entrypoint proof captures complete subprocess output on failure and verifies that importing the application changes neither the table inventory nor the legacy role-row count.

Canonical permission validation is deliberately quiet: it returns the validated registry size or raises deterministically and emits no decorative console output. The fresh-replay entrypoint subprocess replaces captured stdout with a strict ASCII writer before importing `main`, proving that application construction does not depend on UTF-8 console behavior without changing interpreter or console settings.

Platform Core remains separate from XA, Shared Operations, PK, WND cutover, frontend composition and Finance ownership. Neutral Finance fingerprints and effects remain unchanged.
