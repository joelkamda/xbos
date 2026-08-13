# ADR 0009 — PC6 proof profile, portability, and dependency authority

Status: accepted for operator verification.

PC6 uses a deterministic tenant profile as a proof input, not as a new business authority. The profile is executed through PC1–PC5 public services and cannot declare industry semantics, credential material, financial transactions, binary assets or pack lifecycle.

Portable state is classified explicitly. The profile is `PORTABLE`; current database snapshots are `REFERENCE_ONLY`; audit is `HISTORICAL_EVIDENCE`; credentials and secrets are `SECRET`; sessions and Finance are `EXCLUDED`. Restore recreates authority using stable profile codes and public identifiers instead of preserving local integer primary keys.

PC6 creates no Alembic revision because PC1–PC5 already supply the necessary persistence. The canonical head therefore remains `pc5_identity_policy_audit_025`.

Canonical application construction is persistence-side-effect free. Alembic is the only implicit schema installation authority and PC5 is the canonical authorization authority. Legacy ORM schema creation and legacy role seeding remain explicitly callable compatibility operations; `main:app` import does not execute them or assume prior tenant/application rows.

Application construction is also console-encoding independent. Permission-registry validation is silent and deterministic; human-readable diagnostics belong only to explicitly invoked operational utilities. PC6 proves `main:app` import with strict ASCII captured stdout and does not alter `PYTHONUTF8`, `PYTHONIOENCODING`, or the Windows console code page.

The initial production dependency baseline is `requirements-prod.txt`, exact-pinned to the accepted operator environment. No second package-management system is introduced. E5 owns future approved maintenance rather than establishment of the baseline.
