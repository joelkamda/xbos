# XBOS PC0-R4 — exact VN0-C2 dependency closure

Authority: `XBOS-NEUTRAL-F-R1-B1-R1-PC0-R4`; PCR 2026-10-11.
Accepted start: `8508e0e0537ee959395cb397547cf81c90acbb05` (tree `8b4ffadb95d2bdf3a840093d3599a5aa12109daf`).

## Four exact C2 imports — no fifth edge

Additive `contracts/platform/v1/pc0_vn0_c2_dependency_edges.json` pins source path, import, source/target module, accepted C2 commit/authority and Git blob. Verified independently with `git rev-parse <C2>:<path>` and `git rev-parse HEAD:<path>`, byte-for-byte at all four paths:

| Source | Import | Accepted Git blob |
|---|---|---|
| `core/auth/browser_session_model.py` | `database` | `e30ce0d3ab0942790e150ce45ea4c039e104de7e` |
| `core/auth/browser_session_router.py` | `database` | `b4ee6b28027ab82cff263f78ae9c58dbec71ff2e` |
| `core/auth/browser_session_service.py` | `settings` | `ebdd63ed86840e43c3e5ee79772fb15559d5ed00` |
| `core/middleware/auth_middleware.py` | `database` | `e330908fcb2cbc426cdf5389e3c3e18b8ae52faf` |

All are existing `identity → application` imports at accepted `51057262faf7288e0ba4a8d488c8f2ff94e5cbe0`. The global PC0 policy still forbids generic `identity → application`; only these four exact verified source-level exceptions are admitted. Any fifth edge would remain denied.

## R4 seal lifecycle

The additive `pc0_validator_successor_seal_r4.json` pins PCR R4 authority, the accepted R3 predecessor `8508e0e...`, and exactly two permitted source paths: `core/platform/architecture_contract.py` and `tests/contracts/test_pc0_kernel_boundaries.py`. It additionally checks the previously accepted, immutable R3 seal and predecessor SHA-256. No final R4 commit identity is stored in the seal. Wrong path, wrong predecessor/authority, wrong successor digest, missing seal, duplicate/third file and post-seal mutation fail closed.

The frozen PC0 composition baseline, finance inventory, module map, NCE/PC8, VN0-C2 kernel successor, R2 17-step registry, and all R3 successors/seal remain unchanged.

## Legacy PC0 fixture reconciliation

The existing PC0 test file now checks the exact accepted kernel/C2 and PC8/R2 successor chain rather than assuming original historical fingerprints are the final source hashes. The temporary mutation fixture includes exact successor materials, so its injected `database.py` change still fails as `PC0-COMPOSITION-CHANGED: database.py`. No negative assertions are disabled or marked xfail.

## Regression evidence

- Real full PC0 validator: **PASS**; 34 modules, 47 authorities, 29 reference migrations, 72 legacy exceptions, 393 scanned production Python files, 155 cross-module edges, **10 exact successor edges** (2 NCE + 4 N2 + 4 C2), 22 release artifacts.
- Full legacy PC0 suite: **21/21 PASS**.
- Full PC6: **18/18 PASS**.
- R4 targeted strict negative and positive cases: **23/23 PASS**.
- VN0-C2 (11), R2 lineage (16), VN0 neutrality tests (14): **41/41 PASS**.
- N2 policy/runtime unit tests: **15/15 PASS**; standalone: **2/2 PASS**; Restaurant/R6/SO3: **102/102 PASS**; frontend unit: **9/9 PASS**; public contract drift **PASS**, global TypeScript **0 errors**, production frontend build **PASS**; VN0 scanner **PASS**.
- Accepted R3 target suite was replayed in a temporary detached worktree at the *PCR-accepted* R3 commit `8508e0e`, with **25/25 PASS**. Temporary worktree removed. When those same R3 snapshot tests are run **against current R4 source** instead, **22 PASS / 3 FAIL** because their old assertions demand the exact R3 source digest or a C2 denied-edge state. R4 explicitly does not authorize modifying `test_pc0_r3_descendant_successors.py`. No tests were hidden, skipped or mocked. PCR must determine whether replaying the historical R3 acceptance suite at its accepted revision satisfies R4's regression law; current-head R3 snapshot tests are not entirely green.

No auth, browser-session, settings, kernel, business, middleware, Restaurant, orders, inventory, migration, database, frontend, deployment or financial effects. One local commit only; no remote push, merge, tag or deployment.
