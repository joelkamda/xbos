# XBOS M3.0 — Obligation, Value-Source, and Allocation Foundation

## Decision

M3 begins from the approved M2 release tag
`track-b-m2-canonical-event-engine-20260808` at commit `7f8fc3d`.
Its purpose is to establish neutral owed-value and value-application authority.
It does not activate a production writer or integrate WND.

M3.0 installs five empty canonical structures:

1. `financial_obligations` — the original amount owed by one party to another;
2. `financial_obligation_lines` — immutable component snapshots explaining the
   original obligation value;
3. `value_sources` — confirmed or otherwise governed value available for
   allocation;
4. `payment_allocations` — append-only applications of value to obligations;
5. `allocation_reversals` — append-only compensating reductions of allocations.

## Authority model

An obligation owns original owed value and its governed lifecycle state. It
does not own a mutable balance. Outstanding value is derived from original
value, active allocations, and later approved non-allocation satisfactions.

A value source owns original allocatable value. It does not own a mutable
available balance. Available value is derived from original source value and
active allocations.

An allocation is an immutable relationship between one value source and one
obligation. One-to-many and many-to-one behavior emerges from multiple
allocation records rather than special mutable fields. A reversal never edits
its original allocation.

## Party boundary

PC2 owns canonical Party authority. M3.0 therefore stores debtor, creditor, and
value-owner identities as opaque UUID references. It deliberately does not
create a `parties` table, attach a foreign key to a legacy customer/vendor
table, or redefine party semantics. PC2 will later activate governed Party
referential integrity without changing M3's financial authority.

## Payment boundary

M4 owns payment intents, attempts, settlement verification, payment rails,
provider orchestration, refunds, and operational movement of funds. M3.0 does
not create payment-settlement authority. A value source may retain an optional
settlement public identity so M4 can connect confirmed settlements later.

Deposits, unapplied funds, and overpayments are value-source/allocation states
and workflows planned for M3.3. They are not provider settlement workflows.

## Database enforcement

- All money uses `NUMERIC(24,8)` and an ISO-style three-character currency
  reference.
- Tenant and organization scope are enforced with composite foreign keys.
- Allocation foreign keys hard-bind tenant and currency across the source and
  obligation. A cross-tenant or cross-currency allocation cannot be persisted.
- Source and obligation organization units may differ only through the future
  M3.2 engine's explicit, versioned cross-organization policy. The allocation
  record already carries the policy identity needed for audit; M3.0 activates
  no writer that could bypass policy evaluation.
- Allocation reversals inherit the same scope from the original allocation.
- Debtor and creditor must differ.
- Original authoritative amounts must be positive.
- Every authoritative fact carries occurred/recorded time, business date,
  calendar-policy version, correlation, source identity, and a tenant-scoped
  user or service actor. This preserves offline replay and audit explanation.
- Obligation lines, value sources, allocations, and reversals reject update and
  delete operations.
- Obligation economic fields are immutable. Only lifecycle state and its
  monotonically incremented row version may change.
- Idempotency identities are unique per tenant.
- Deletes use `RESTRICT`.

Capacity enforcement that requires locking and aggregation is intentionally
deferred to the M3.2 allocation engine. M3.0 supplies the structural keys and
indexes required for that lock order.

## M2 release-checkpoint compatibility

M2.7 originally validated `m25_financial_dimensions_007` as though it must
remain the repository head forever. That is correct at M2 release time but
would reject the first legitimate M3 descendant.

M3.0 narrows the meaning without changing any M2 manifest, contract, semantic
hash, or release tag:

- M2's seven revisions remain an exact immutable lineage prefix;
- the repository must still have exactly one head;
- any later revision must descend linearly from the M2 checkpoint;
- a missing, altered, bypassed, or forked M2 prefix still fails closed.

The M2 development acceptance runner likewise accepts the M2 checkpoint or a
known linear descendant while continuing to verify the frozen M2 row counts.

## Migration and rehearsal

- Parent revision: `m25_financial_dimensions_007`
- Target revision: `m30_obligation_foundation_008`
- Disposable database: `xbos_track_b_m30_foundation_test`
- Required rehearsal: fresh upgrade, empty-schema inspection, downgrade to M2,
  re-upgrade to M3.0, and guarded disposal.

The development migration is empty-data only. After upgrade, the existing event
catalog remains at 20 rows and all existing M2 financial truth plus all five
new M3.0 tables remain empty.

## Deferred M3 work

- M3.1: typed obligation commands, obligation-line total validation, lifecycle,
  idempotency, and derived balance service;
- M3.2: allocation and reversal engine, partial allocation, one-to-many,
  many-to-one, locking, and cumulative capacity;
- M3.3: deposits, unapplied value, overpayments, release, and transfer;
- M3.4: pack-facing contracts, cross-industry conformance, trace integration,
  acceptance freeze, and milestone tag.

No M3.0 result authorizes WND writer cutover, outbox dispatch, tenant seed data,
public routes, provider integration, or historical transformation.
