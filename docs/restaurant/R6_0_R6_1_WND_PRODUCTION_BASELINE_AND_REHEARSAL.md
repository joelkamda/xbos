# R6.0 / R6.1 — 21 Aug WND reference-release baseline and disposable-clone adoption rehearsal

## 1. Frozen production reference release

R6.0 now fixes WND to the Track A reference release promoted and captured on 21 August 2026.

- release tag: `wnd-track-a-reference-release-20260821`
- backend release branch: `track-a/wnd-live-parity-reference-backend`
- frontend release branch: `track-a/wnd-ui-live-parity-responsive-frontend`
- live backend commit: `b60a71dcc06657bd407fac043f6f3922d5bfe32f`
- live frontend commit: `f47f574f6a2f2e2247ab7c491dc65c7800adbc9d`
- production database: `xbos`
- raw Alembic revision: `5c706797029a`
- PostgreSQL: 17.5
- production evidence: `WND_R6_0_SERVER_PRODUCTION_EVIDENCE_20260821_171736.zip`
- production evidence SHA-256: `5476210b011eac716a29dbfae1c9cac05155fd2061927f533729c321e7b7cf75`
- source evidence: `WND_TRACK_A_REFERENCE_RELEASE_EVIDENCE_20260821_171625.zip`
- source evidence SHA-256: `fc291ec6c43507a9312d032ce61d5d4aee8db874377481a114d6785456242cc0`
- snapshot backup: `WND_R6_0_SERVER_PRODUCTION_SNAPSHOT_20260821_171736.backup`
- snapshot backup SHA-256: `22c105224f65dec2bc09ef0335748a1db855ee59945c170b69526ee18f39dc16`
- snapshot backup size: `3679584` bytes

The production checkout branch name is operational context only. Release identity is the exact commit shared by production HEAD, the declared release branch, and the published release tag.

The only disclosed backend untracked utility is `scripts/wnd_taxonomy_tree_export.py`; it is not part of immutable committed release source. The frontend has no remaining untracked file in this capture.

This baseline supersedes all 19 August R6.0/R6.1 snapshot assumptions.

## 2. WND reference behavior that R6 must preserve

Track A is a production specimen and reference, not the architecture or capability ceiling of Restaurant.

R6 nevertheless must preserve the accepted WND behavior while moving authority into neutral Track B capabilities:

- WND-first responsive shell and operational UI;
- Dine In / Takeaway / Delivery order fulfillment evidence;
- historical unspecified fulfillment remains nullable evidence and must not be guessed;
- kitchen initial full bon plus semantic incremental additions/cancellations/mixed changes;
- non-semantic kitchen changes must not cause duplicate reprints;
- explicit Customer identity may link to Accounts Receivable;
- new A/R may use an existing Customer or a manual debtor;
- ambiguous/name-only historical A/R must remain unlinked rather than guessed together;
- A/R repayment remains settlement of an existing receivable, never new income;
- historical inventory cache/ledger differences remain evidence rather than being normalized;
- accepted reconciliation continuity remains authoritative.

At capture time the `customers` table exists but contains zero customer identities. This is valid: historical unlinked A/R debtors remain visible without unsafe automatic identity promotion.

## 3. Production controls frozen by the 21 Aug snapshot

Key counts:

- 7,745 sales / 16,566 sale items;
- 8,451 orders / 17,958 order items;
- 4,010 order-item modifiers;
- 240 A/R rows / 13 repayments;
- 8,115 payment intents / 7,807 payment attempts;
- 176 inventory items / 38,900 inventory movements;
- 791 reconciliation rows, all 791 closed;
- 17,490 treasury rows;
- 0 customer rows.

Control totals:

- sales and sale-item total: XAF 35,193,200;
- orders and order-item total: XAF 38,083,300;
- A/R original XAF 736,500; paid XAF 96,199; balance XAF 640,301;
- A/R equation mismatches: 0;
- orphan A/R repayments: 0;
- inventory quantity-on-hand aggregate: 1,997,976;
- inventory movement-ledger aggregate: 2,143;
- historical cache/ledger mismatch rows: 156;
- historical aggregate delta: 1,995,833;
- future-dated inventory movements: 0.

## 4. Legacy reference schema additions that must survive adoption

The live Track A schema remains stamped `5c706797029a`, but now contains additive WND reference extensions that are not represented by that legacy Alembic stamp.

R6.1 therefore explicitly proves these survive neutral lineage adoption unchanged:

1. `orders.fulfillment_mode`
   - nullable, so historical unspecified values stay unspecified;
   - default `DINE_IN` for new inserts when the column is omitted;
   - allowed values DINE_IN / TAKEAWAY / DELIVERY;
   - `ck_orders_fulfillment_mode`;
   - `ix_orders_tenant_branch_fulfillment_mode`.

2. `customers`
   - current row count 0;
   - context/name index and context/normalized-phone uniqueness.

3. `accounts_receivable.customer_id`
   - nullable foreign key to `customers(id)`;
   - tenant/branch/customer index;
   - zero linked rows at the captured baseline because no explicit customer identities had yet been promoted.

R6 must not turn any of these Track A tables into neutral architectural authority merely because they exist. They are compatibility/reference evidence to map deliberately in later R6 work.

## 5. Why R6.1 remains a disposable clone rehearsal

R6.1 does not touch production.

The gate restores the exact reference-release snapshot twice:

- `xbos_r6_1_source` — untouched source control;
- `xbos_r6_1_candidate` — migration/composition candidate.

Both names are hard-coded. The gate refuses any other database name and never targets `xbos`.

The candidate then:

1. proves the exact frozen counts, totals and legacy reference schema;
2. stamps `m13_source_state_001` without reconstructing legacy source;
3. upgrades canonical lineage to `r2_restaurant_menu_fulfillment_043`;
4. proves all legacy WND controls and reference schema are still unchanged;
5. registers/certifies `industry.restaurant@1.0.0`;
6. installs/activates it for existing tenant 2;
7. applies `restaurant.counter_service@1.0.0`;
8. materializes the accepted WND PC4 operating context;
9. proves the same WND controls again.

## 6. Existing WND tenant composition

R6.1 composes the existing WND tenant (`tenant_id=2`, `branch_id=1`). It does not provision `wnd-r5-proof`.

The PC1 legacy branch mapping is compatibility structure at this stage. R6.2 owns production-shaped semantic/data mapping and explicit Logpom refinement.

## 7. R6.1 non-actions

R6.1 does not:

- write `xbos`;
- stamp or migrate production;
- disable any WND writer;
- switch Finance, inventory, order, payment or customer routing;
- install the Restaurant pack in production;
- transform ambiguous historical finance;
- infer historical fulfillment mode;
- create customer identities from name-only debt;
- normalize historical inventory;
- cut over the frontend;
- cut over kitchen output.

A successful R6.1 authorizes R6.2 production-shaped mapping work on disposable clones only.
