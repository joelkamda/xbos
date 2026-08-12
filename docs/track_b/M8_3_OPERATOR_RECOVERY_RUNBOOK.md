# M8.3 operator recovery runbook

Always stop or fence financial writers before database recovery. Record the incident, application version, database name, migration revision, backup identity, operator and timestamps. Never edit financial truth manually.

## Failed deployment before migration

Roll back only the application deployment. Confirm `alembic current`, release manifests and health against the unchanged database. Do not run a database downgrade.

## Failed deployment after migration

Keep writes fenced. Determine whether the approved downgrade is lossless for the actual database. The M8.3 M64↔M63 schema rehearsal is performed only on a financially empty candidate. For populated history, restore the known pre-deployment backup into a clean database and prove financial equivalence before promotion.

## Interrupted verification

Run `python scripts\verify_m83_performance_recovery.py status`. Retained databases are limited to `xbos_track_b_m83_volume_test`, `xbos_track_b_m83_restore_test` and `xbos_track_b_m83_rollback_test`. Inspect them first; drop only one exact name with `drop --confirm-database-name <name>`, then rerun the single gate. Temporary backup location is printed by the failed verifier.

## Restore from a known backup

Create a different clean local database and use `pg_restore --exit-on-error --no-owner --no-privileges`. Never restore over the development or production database. Validate the Alembic head, release manifests, row-count/digest fingerprint, journal balance, control totals, tenant scope, representative reports and replay/idempotency state.

## Recovery verification before writes

Keep writes closed until the restored financial fingerprint equals the approved pre-backup fingerprint, the canonical head and manifests pass, journals balance, closed-period controls remain present, and an authorized operator signs the evidence. Reopen traffic through the operational release process only after those checks.

## Financial correction is not technical retry

Retry a rolled-back technical command only through its existing idempotency identity. If an accepted economic fact is wrong, append an authorized linked correction; never mutate or delete history. Provider timeout or uncertainty remains uncertain until authoritative evidence arrives.

R6 owns live WND cutover. M8.3 recovery evidence does not authorize writer rerouting, legacy retirement or production cutover.
