# R6.2 — WND production-cutover rehearsal

## Decision

R6.1 proved that the immutable 21 Aug 2026 WND production snapshot can be restored into disposable clones, structurally adopted from the legacy WND Alembic head `5c706797029a` through the neutral lineage to `r2_restaurant_menu_fulfillment_043`, and composed onto the existing WND tenant without changing legacy row counts or control totals.

R6.2 rehearses the **authority transition data mechanics**, still without any production write or production writer-routing change.

## Fixed source

- R6.1 freeze commit: `0f4c72ff297b580c9a2572fe6a0068d814b22267`
- R6.1 freeze tag: `restaurant-r6-1-wnd-reference-clone-adoption-20260821`
- R6.2 branch: `restaurant/r6-2-wnd-production-cutover-rehearsal`
- source archive SHA256: `9c789845bf8f2a68ab0de9d87707eac492e109a8e646c4533e915e181e6a1c94`
- WND reference release: `wnd-track-a-reference-release-20260821`
- WND backup SHA256: `22c105224f65dec2bc09ef0335748a1db855ee59945c170b69526ee18f39dc16`

## Disposable databases only

R6.2 may create, drop, restore, stamp, upgrade and compose only:

- `xbos_r6_2_source`
- `xbos_r6_2_candidate`

`xbos` is never a writable R6.2 target.

## Financial rehearsal rule

Every M7 control must satisfy:

`legacy source = canonical mapped shadow + explicit withheld`

The eight frozen M7 controls are:

1. commercial revenue;
2. customer allowances;
3. cash collections;
4. receivables opened;
5. receivables satisfied;
6. refunds;
7. fulfillment cost;
8. financial documents.

A canonical-only variance is therefore not hidden. It must equal the explicit withheld ledger exactly.

## Mapping policy

R6.2 executes the frozen M7.1 mapping **services**, not production canonical writers.

A source record is mapped only when its captured WND evidence is sufficient for the canonical command contract. Otherwise it is withheld with a deterministic reason and fingerprint.

Important examples:

- A historical sale whose WND gross/discount/complimentary data cannot satisfy the canonical commercial equation is withheld whole.
- Non-cash settlement evidence without an external settlement identity is withheld.
- Explicit A/R repayment rows are mapped as settlement of an existing receivable and never as revenue.
- Historical `paid_amount` not backed by explicit repayment rows remains a withheld historical satisfaction amount.
- Ambiguous/name-only customer identity is never synthesized.

## Inventory/COGS

WND has no trustworthy historical cost basis that R6 may promote into universal canonical costing.

R6.2 therefore proves the M7.2 missing-cost behavior against real WND movement evidence. No historical COGS event is created from a missing or unreliable cost basis.

A mapped fulfillment-cost control of zero means **no verified historical cost was executed**. It does not mean the economic cost was zero.

The known WND cache-vs-ledger mismatch remains historical evidence and is not normalized.

## Documents

Historical receipt identities remain visible as WND evidence. R6.2 does not regenerate historical documents as originals when immutable historical content hashes are unavailable.

## Dual read

R6.2 uses the M7.4 mode:

`legacy_primary_canonical_shadow`

Legacy and canonical projections are compared at the same tenant, organization, currency and as-of scope. Any difference remains visible.

## Recovery

The candidate is deliberately destroyed after the first mapping pass, restored from the exact immutable WND backup, re-adopted and recomposed, and the mapping/readiness fingerprints are reproduced.

This is a rehearsal of rollback/recovery mechanics, not a live rollback.

## Writer retirement

R6.2 can prepare the reversible M7.4 writer-retirement plan for R6 review.

It cannot execute that plan. `execution_allowed` remains false and production writer routing remains unchanged.

## Exit

`R6_2_SINGLE_GATE=PASS` means the data-transition rehearsal is deterministic, source-complete by mapped-or-withheld classification, recovery-safe, and ready for R6.3 application compatibility/frontend UAT.

It does **not** authorize live WND cutover.
