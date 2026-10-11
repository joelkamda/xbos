# XBOS PC0-R3 — Final accepted descendant reconciliation

Authority: `XBOS-NEUTRAL-F-R1-B1-R1-PC0-R3` (PCR, 2026-10-11).
Accepted start HEAD: `6d3c8940d99bcda77f6522200999ef0e79859792`.
Accepted start TREE: `3731d12b9cf3435e548be022c6eec3d371ec5150`.

## Scope completed

1. **Non-Finance migration extensions:** additive contract `contracts/platform/v1/pc0_non_finance_migration_successors.json` registers exactly 10 verified files in revisions 048–051. The current canonical SHA-256 of each file was compared with the same file at its accepted Git commit. No Finance inventory or migration file was rewritten, and no migration was executed. Commits: 048 `a168df1de5041d3be2c32539e0d52544d1351ce0`, 049 `ca2b27bbc8a7c3c32b3a89c74623757da8c5e9c6`, 050 `e0ae0123cec02cb2cb294e2bbad09df341be17c1`, 051 `bbb60a1e979727917dc1b9f55d7f56e405b23d04`. Each entry carries exact path, digest, revision, source commit, PCR authority, owner and reason. The Finance 020 prefix and already-governed descendants remain unchanged.
2. **Neutral policy ownership:** additive `contracts/platform/v1/pc0_n2_operational_policy_successor.json` declares precisely `core/domain/operational_policy.py` under the neutral `operational_policy` module, from accepted commit `631e9280bbf4d95d5c97400d3268a7cb9d787994`. It does not grant restaurant business authority or introduce a database/selector.
3. **Accepted N2 import edges:** the separate `pc0_n2_operational_policy_edges.json` registers exactly four existing and previously accepted imports from generic Orders (2) and Inventory (2) to the neutral policy contract. Each import appears in accepted N2-R1 source `93198dafff6f1e0809e6dba2b9e4352d8a6037a8`.
4. **Validator successor seal:** `pc0_validator_successor_seal.json` seals only `core/platform/architecture_contract.py`, bound to PCR R3 authority and accepted PC0-R2 predecessor commit `6d3c8940d99bcda77f6522200999ef0e79859792`. Its predecessor canonical SHA-256 is `2a0bccd2cc0301fca71badf6e5cc004e287a9f687d4cdf123f74ddf8f5a05689`. The exact proposed R3 SHA-256 is stored in the seal. The seal does not claim that the as-yet-unadjudicated R3 commit has previous PCR acceptance, and it contains no self-referential final commit ID.
5. **Historical contracts:** `pc0_composition_baseline.json`, `pc0_frozen_finance_inventory.json`, `pc0_module_map.json`, NCE/PC8 contracts and manifests, VN0-C2 PC0-R1 registration and PC0-R2 17-step successor registry all remain intact.

## Exact unresolved PC0 dependency blocker — outside R3 grant

A full, unmodified import dependency scan of 155 production cross-module edges produces four deny results **after** original NCE and the exact four N2 admissions:

| Source path | Import name | Source module | Target module | Historical origin |
|---|---|---|---|---|
| `core/auth/browser_session_model.py` | `database` | identity | application | accepted VN0-C2 |
| `core/auth/browser_session_router.py` | `database` | identity | application | accepted VN0-C2 |
| `core/auth/browser_session_service.py` | `settings` | identity | application | accepted VN0-C2 |
| `core/middleware/auth_middleware.py` | `database` | identity | application | accepted VN0-C2 |

The actual full PC0 failure is `PC0-DEPENDENCY-DENIED: core/auth/browser_session_model.py -> database -> identity -> application`.

R3's approved new dependency edges are explicitly restricted to N2's neutral operational policy. None of these C2 edges were admitted, renamed or hidden. PCR must authorize a separate strict, source-verified C2 Identity→Application dependency successor (or authorize an alternative architectural correction), without widening existing global dependency rules.

## Regression and negative gates

- R3 targeted negative/positive tests: **25 PASS**. These cover unregistered/wildcard/altered migrations, wrong migration commit or owner, exact module owner/root, unauthorized import edges, seal path/predecessor/authority/hash, missing seal and post-seal source mutation.
- PC0-R2 lineage, VN0-C2 successor and VN0 semantic scanner unit tests: **41 PASS**. Combined new/accepted architecture+scanner tests **66 PASS**.
- N2 policy, parity and order-write propagation unit tests without database access: **15 PASS**; previously accepted 11 PostgreSQL binding tests were not rerun, preserving no-DML/DDL.
- Standalone **2 PASS**; Restaurant/R6/SO3 **102 PASS**; frontend unit **9 PASS**; public contract drift **PASS**; TypeScript 0 errors; frontend production build **PASS**.
- VN0 semantic scanner current source **PASS, 0 findings**.
- Full PC0 **18 PASS / 3 FAIL**: full repository test blocked by the four C2 edges; frozen-composition test still contains pre-C2 direct-hash assertions; a historical composition fixture omits accepted successor materials and fails at kernel validation ahead of its intended database-mutation check.
- Full PC6 **17 PASS / 1 FAIL**, with its single failure delegated to the real PC0 dependency denial. Original PC6 WND-leakage behavior remains unchanged.

These PC0 legacy fixture assertions may be corrected in a narrowly authorized successor along with the separate C2 dependency-edge decision; neither is bypassed or reported as passing under R3.

## Effects and stop state

Only architecture governance, additive successor contracts, targeted R3 tests and this document changed. No business source, middleware, auth, kernel, settings, orders, inventory, Restaurant, schema/migration, database, hosted WND runtime, frontend, deployment, remote push, merge, tag or financial effects.

Disposition: `EXECUTION_RETURN=BLOCKED` for full PC0-R3 acceptance, with migration/module/N2-edge/validator-seal subscopes locally verified. **VN0 remains HOLD.** PCR adjudication of the bounded source evidence is required.
