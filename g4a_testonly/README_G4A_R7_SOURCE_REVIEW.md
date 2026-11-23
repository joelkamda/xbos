# XCOMP G4-A — R7 canonical source admission (TEST only)

**CEO authorization:** November 22, 2026; bounded TEST-only G4-A; source PR/CI, never live WND / real payment / production write.

**Canonical branch:** `platform/neutral-vnext-vn2-pc0-discovery-successor` (live GitHub HEAD `376547f7c037814ab2b19a1df8fd6c7aec08f864` at source admission).

## What is in this PR

- `source/backend/`: SHA-preserved **R7 actual FastAPI/PG17 synthetic rehearsal** for N, PA, PK, SOF and W, with native stock/order/kitchen/AR/finance/readmodels, atomic CAS and TEST authorization/receipt custody. Source is **not** the operative neutral XBOS kernel.
- `source/frontend/`: React R7 merchant/operator UI and pinned NPM sources, with an additive minimal preview entrypoint. No production route or build installed.
- `source/integration/`: bounded owner integration acceptance harness source.
- `R7_SOURCE_MANIFEST.json`: SHA-256 of **every copied accepted original file** and accepted evidence counts, explicitly all operational permissions false.
- `restaurant/g4a_source_admission.py`: canonical importable SOURCE-ONLY gate with exact manifest integrity and fail-closed production admission.
- `tests/contracts/test_g4a_r7_canonical_source_admission.py`: canonical PR review contract. New source-only CI workflow runs source integrity + TypeScript + React.
- **No** import or router registration from `startup.py`, `main.py`, `core.api.kernel_router`, or any live WND route. No Alembic changes or Finance postings.

## Test evidence, correctly scoped

Previously independently accepted R7 on Pavilion: **123 native PostgreSQL17/FastAPI + 38 Chromium/React = 161/161 PASS** in isolated synthetic TEST (tenant 920002, branch 1, loopback port 55449), separate from V23 historical WND G3 protected 2/2 restorations, 87/87 rehearsal. Those original receipts are preserved; these numbers are **not re-proven by merely transferring the source to a GitHub branch**.

This new canonical worktree is checked by hash and no-mount contract, and its preview UI compiles. The source-only CI is separate from existing protected required checks, and does not change their enforcement. **A green source check is not production release clearance.**

## Known mismatch to be solved in G4-A before operative candidate acceptance

The canonical repository already includes PC3 taxonomy, PK, PA/PC5, shared operations and restaurant r6/neutral APIs. Detached R7 uses separate `v3r_*` and `v24_*` synthetic PostgreSQL schema, special synthetic `v3r_sessions`, fake pack and tax policy readbacks, and a standalone merchant React app.

The source-transfer patch cannot be merged as a production runtime without explicitly replacing all synthetic pieces with actual owner-versioned canonical services and mappings:

1. **N + PK + PA**: bind source revision CAS to canonical tenant/branch product repository, signed PC3 taxonomy/policy, PK9-axis certification and genuine PC5 least-privilege actors. R7 synthetic publisher's `realPc5` and `realPackCertification` are deliberately false.
2. **SOF + W**: canonical auditable double-entry Finance/A/R and protected source balance reconciliation. The accepted historical shadow contains 479 source A/R records totaling 1,144,801 XAF; 465 lack structured customer ID and 14 are unverified, so no auto-merge or invented debtor identity.
3. **FE**: integrate accessible EN/FR merchant composer, cashier/kitchen/stock/Finance/receipt flows with canonical XBOS frontend, not with the standalone R7 login and receipt preview. Finish role-specific keyboard/ARIA testing.
4. **N + W + Gateway**: original D7 first-write recovery, late provider-callback finality, real controlled 80mm printer, rollback and independent off-device RPO/RTO. D7-19 payments remain separately certified.
5. **Governance:** the protected branch ruleset (26809892) requires `xcomp-neutral-pr-integrity` and `xcomp-d1d2-integration-regression`. The second workflow's November D1 head-branch allowlist excludes this new G4-A branch. This PR **must stay DRAFT/UNMERGED** until owners deliberately review and extend CI source admission; do NOT bypass, weaken, or impersonate the frozen D1 checks.

## G4-A next executable canonical integration (November 23)

A **new** `restaurant/g4a_canonical_product_publication.py` now implements a
typed transaction/authorization path for merchant product review and
MAIN/VIP/BAR price revisions. It invokes the actual canonical
`SecurityAuthority.authorize` (PC5), `SemanticAuthority.resolve` (PC3),
`PackAuthority.state` (PK), and `SO1Authority.atomic_unit` (SO1), and
requires an explicit trusted SOF account/tax binding. It rejects publisher
equals creator, stale source/zone revisions, revoked access, inactive packs,
unknown semantics, unverified Finance and duplicate idempotency.

`restaurant/g4a_canonical_product_pg_repository.py` supplies a genuine
PostgreSQL row-locked candidate transaction and audit CAS. **Its connection
factory is hard-fenced to one synthetic local TEST database**
(`g4a_v24_native_product_test`, loopback 127.0.0.1:55449). The temporary
database is explicitly provisioned, tested and dropped; there is NO Alembic
migration or canonical production route.

- Focused canonical PC5/PC3/PK/SO1 source contract: **27/27 PASS**.
- Actual new PostgreSQL17 candidate table, concurrent row locks, denial,
  rollback and no duplicate audit: **22/22 PASS**.
- These are a meaningful canonical service boundary, **not yet actual
  production PC5 issuance or canonical SO1 catalogue publication**.
- A real source-backed account mapper/PK registry, production
  migrations, canonical UI API and genuine PC5 actor commissioning
  remain required before the new service can be mounted.

## Local, test-only source checks

From the canonical source worktree:

```shell
python -m pytest -q -p no:cacheprovider tests/contracts/test_g4a_r7_canonical_source_admission.py
```

The opt-in React source can be compiled without deployment:

```shell
cd g4a_testonly/source/frontend
npm ci --ignore-scripts
npx tsc --noEmit
npm run build
```

To run the native R7 regression again, use a separately provisioned **no-egress PostgreSQL17 TEST** harness and the R7 source in `source/backend`; never import or launch it under canonical `main:app`, never point it to WND databases. The previous Pavilion R7 rehearsal remains independently available.

## Delivery / decision

This is **G4-A source transfer and canonical admission stage**, not G4-A operative software closure.

- New canonical review source: READY for a draft PR, independent CTO review and CI.
- Genuine canonical kernel/React runtime mapping: **OPEN**.
- Real PC5, official SOF ledger, authentic historical balance mapping, physical printer, off-device DR, PSP finality: **HOLD, not waived**.
- G3 accepted rehearsal: preserved, **no repeat**.
- Live WND, protected GitHub branch, Render services, real payment or first live write: **NOT TOUCHED**.

This is a reviewable path out of detached tests, without pretending that a copied TEST bundle is the final merchant product.
