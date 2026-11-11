# SOF ? Local authoritative Finance protocol (S0?S2 source qualification)
A locally committed cash transaction has PG17 ledger readback, tenant/branch,
writer-node epoch, PC5 authorization and idempotency. SO8 queued device intent
is **not** ledger truth. Provider PAID requires independent finality.
NodeSync consumes N's signed AuthorityEpoch via injected validation port;
SOF may not define a competing epoch or writer. Actual PostgreSQL commit,
WAL replay, sync and restore are NOT certified under this source wave.
