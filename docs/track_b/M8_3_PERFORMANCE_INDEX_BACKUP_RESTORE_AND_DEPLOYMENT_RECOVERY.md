# M8.3 — Performance, indexing, backup/restore and deployment recovery

Revision 2 keeps payment authority unchanged and corrects the rehearsal fixture so
high-valued stable payment identities do not double as elapsed-minute offsets.
Every generated intent, attempt, transition, settlement and confirmation now uses
a deterministic bounded lifecycle timeline.

Revision 3 corrects the plan specimen to use M2.4's accepted
`journal_entry_event_links` relation. The trace query is tenant-scoped and exercises
the existing `(tenant_id, financial_event_id, journal_entry_id)` index; the same
canonical table is included in backup/restore equivalence fingerprints.

M8.3 is a schema-neutral hardening package at checkpoint `7f240cb` and canonical head `m64_reconciliation_controls_020`. It introduces no financial authority and no Alembic revision.

The disposable rehearsal creates bounded production-shaped facts across events, journals, obligations, allocations, payments, settlements and reconciliation controls. It records fixture sizes and observed write/query times without declaring a machine-dependent universal latency threshold. Representative tenant-scoped PostgreSQL plans must expose usable indexes; index evidence comes from the accepted schema, not column-name guesswork.

The source database is backed up with `pg_dump` and restored with `pg_restore` into a different clean database. Equivalence requires the same migration head, row counts, deterministic row digests, balanced journals and financial control totals. A merely successful restore is insufficient.

Deployment rollback is rehearsed on a financially empty candidate database across the accepted M64-to-M63 boundary and back to M64. Populated financial history is not destructively downgraded. Application-code rollback, schema rollback, database restore and append-only financial correction remain distinct operations.

The development database is inspected read-only and must remain financially empty. Temporary backup and disposable databases are removed only after the full evidence workflow succeeds. R6 retains ownership of live WND cutover.
