# XBOS VN0 neutrality — N2-R2 source conformance

Authority: `XBOS-NEUTRAL-F-R1-B1-R1-N2-R2` (2026-10-10)
Accepted start backend: `93198dafff6f1e0809e6dba2b9e4352d8a6037a8`.
Frontend is frozen at `3b30b47d0936e0a6a7a6f1397627c11c067dfcfc`.

## Scope and limits

The VN0 scanner `scripts/verify_vn0_neutrality.py` is a read-only AST-based source-conformance check. It detects known executable authority shortcuts; it does **not** claim to prove the absence of every possible dynamically constructed business rule. Golden and binding regressions supply the complementary runtime proof.

Shared runtime zones scanned:
`core/api/orders`, `core/domain/orders`, `core/domain/inventory`, `core/platform`, `core/integrations`, and existing root boot/composition files `main.py`, `app.py`, `startup.py`, `database.py`, `settings.py`.

The checker flags direct Core imports of WND policy/binding, WND profile literals in shared Core, tenant identity branches including hard-coded ID 2, restaurant fulfillment constants in generic orders, WND menu alias keywords in generic inventory, and implicit kitchen-based negative-stock decisions.

Excluded/allowed: `restaurant/`, WND pack/adapters and R6 compatibility, migrations, tests, fixture goldens, documentation, and `core/platform/neutral_proof/` (the independent frozen PC6 conformance implementation). Mere WND mentions and error diagnostic text are not automatically business-policy authority.

`python scripts/verify_vn0_neutrality.py` emits deterministic JSON, returning 0 for PASS and 1 for detected source authority. `python -m unittest tests.contracts.test_vn0_neutrality_scanner -q` covers the existing source, accepted pre-cleanup N2-R1 source, injected authority failures, CLI nonzero failure, and allowed zones.

## N2-R2 behavioral firewall

Only neutral-runtime nomenclature changed: inventory file header comment, inventory negative-stock helper docstring, and XafPay V2 unsupported-currency message (to `XafPay V2 checkout requires XAF`). The `XAF` validator, emitted error code, order/inventory behavior and PC4 policy-selection contracts are unchanged.

No change to immutable `industry.restaurant@1.0.0`; no WND hosted source or DB mutation, no session/migration 051, no finance/payment logic, no publication or deployment.

## Verified local evidence

| Gate | Result |
|---|---|
| VN0 semantic scanner current source | PASS, 0 findings |
| VN0 semantic scanner accepted N2-R1 source hotspots | PASS |
| VN0 scanner positive/negative/allowed-zone unit tests | 14 PASS |
| N2-R1 binding and parity (disposable local PostgreSQL) | 26 PASS |
| Restaurant/R6/SO3 selected suites | 102 PASS |
| Backend browser-session suites | 15 PASS |
| Standalone bootstrap tests | 2 PASS |
| Frontend VN0 tests | 9 PASS |
| Browser public-contract and VN0 manifest drift | PASS |
| TypeScript global typecheck | PASS, zero errors |
| Production frontend build | PASS |
| PC6 WND leakage scanner unit test | PASS; PC6 code unchanged |
| Prior Chrome auth E2E | Not rerun; auth/session/frontend code unchanged |

Broader `git grep -ni -E 'Wine & Dine|\\bWND\\b' -- core pack_platform platform_admin`: 13 matches, all located in scoped finance ancestry/adapters, a conformance specimen, or the PC6 guard. Blocking shared authority: 0. A zero-string count is not an acceptance criterion.

## Supplemental PC0 architecture validator finding

A broader PC6 test run returned **17 passed, 1 failed**. The failing test is `test_pc0_architecture_covers_pc6_proof_module_and_stays_green`, with `PC0-NCE-KERNEL-CHANGED: core/api/kernel_router.py`. This is not the PC6 WND leakage scanner test; that scanner passes separately.

The accepted source commit's `core/api/kernel_router.py` object hash and the current working file's object hash are **both** `4663ba1899eb7940ff8388e582d05dbd57911a88`. Neither `core/api/kernel_router.py` nor `core/platform/architecture_contract.py` changed under R2. The broader PC0 fingerprint discrepancy is therefore pre-existing relative to N2-R1 and outside the authorized R2 edit scope. Do not modify PC0 contracts, frozen fingerprints, or boot authority to mask it. PCR may adjudicate it separately if full PC0 validation is required for promotion.
