# PC0-R2 Accepted Source Fingerprint Lineage — Bounded Reconciliation

Authority: `XBOS-NEUTRAL-F-R1-B1-R1-PC0-R2`, 2026-10-11.
Accepted starting commit: `47200c29b974e1c89af2080139b8b899d0778898`.
Starting tree: `2ba8360fd3dc93446965461c9cdc98484a215b3c`.

## Source fingerprint inventory (11 checks, 8 distinct paths)

| Path | Historical source | Ordered accepted successor commits | At start HEAD |
|---|---|---|---|
| `startup.py` | PC0 composition | `d064f617` (H1B) | Already registered by historical H1B contract |
| `core/api/kernel_router.py` | PC0 composition | `92f6dbc7` (NCE), `51057262` (VN0-C2) | Already registered by PC0-R1 |
| `settings.py` | PC0 composition | `b9174cbe` (VN0-R1) | 1 new registered step |
| `core/middleware/auth_middleware.py` | PC0 composition, PC8 | `92f6dbc7` (NCE), `d064f617` (H1B), `5931c901` (PC8/H1B), `51057262` (VN0-C2) | 4 new registered steps |
| `core/middleware/tenant_middleware.py` | PC0 composition, PC8 | `92f6dbc7`, `d064f617`, `5931c901`, `51057262`, `b9174cbe` | 5 new registered steps |
| `core/middleware/branch_middleware.py` | PC0 composition, PC8 | `92f6dbc7`, `d064f617`, `5931c901`, `51057262`, `b9174cbe` | 5 new registered steps |
| `core/integrations/xafpay_v2/contract.py` | NCE module overlay | `81769368` (N2-R2 terminology) | 1 new registered step |
| `core/platform/architecture_contract.py` | H1B PC0 release successor | `47200c29` (accepted PC0-R1) | 1 registered step; **current PC0-R2 source remains unaccepted** |

The registry has **6 new paths / 17 exact source transitions**. All SHA-256 values are pinned in both the additive registry and the PC0 validator's trusted table. The target test validates each historical anchor and successor's canonical LF-normalized content against `git show <commit>:<path>`; it rejects reordered/skipped steps, wrong commits/authority, historical NCE/PC8 rewrites, wrong SHA and subsequent source mutation.

Authority references: historical NCE authority is `XBOS-NCE-H1B-ADDITIVE-SUCCESSOR-R1-SOURCE-MATERIALIZATION`; H1B/PC8 restoration is captured in the preserved accepted H1B successor; VN0-C2, VN0-R1, N2-R2 and PC0-R1 were accepted by PCR. No predecessor hash was overwritten.

## Forensic supplemental blockers — DO NOT register without more authority

1. **Self-referential active source:** `architecture_contract.py` is necessarily changed by PC0-R2. The new source does not yet have a previously **accepted** commit. It remains excluded from the accepted history registry; the last registered SHA is PC0-R1. The old `test_pc0_kernel_boundaries.py` remains unchanged for the same reason. Full PC0 stops at `PC0-H1B-RELEASE-REPLACEMENTS: core/platform/architecture_contract.py`. Do not register an active, unadjudicated commit as accepted or weaken the release fingerprint.
2. **Frozen finance non-finance extension inventory:** a diagnostic in-memory exercise that used the last accepted PC0-R1 validator SHA (never in a real PC0 PASS result) exposed ten unregistered Alembic files belonging to 048–051:
   - `sql/cc_catalog_binding_registry_{up,down}.sql` and `versions/cc_catalog_binding_registry_048.py` — `a168df1d`
   - `sql/cc_catalog_binding_price_code_case_049_{up,down}.sql` and `versions/cc_catalog_binding_price_code_case_049.py` — `ca2b27bb`
   - `sql/cc_order_draft_facade_050_{up,down}.sql` and `versions/cc_order_draft_facade_050.py` — `e0ae0123`
   - `versions/browser_session_v1_051.py` — `bbb60a1e`
   These are Git-tracked, existing migration files. PC0-R2 does not authorize changing schema, the historical frozen finance inventory, or adding unreviewed extension authority.
3. **Missing module-map authority:** bypassing the PC0 finance gate in memory solely for diagnosis exposes `PC0-UNMAPPED-TARGET: core/api/orders/orders_controller.py -> core.domain.operational_policy`. The accepted N2 source `core/domain/operational_policy.py` requires a separate explicit PC0 module/dependency-ownership successor; it must not be resolved by a wildcard.

The two diagnostic bypasses were invoked only using `unittest.mock.patch` inside a one-time test process *outside* the repository. No source validation was relaxed in the preserved implementation, and those exercises are **not PASS evidence**.

## Invariants

- Source file changes permitted by PC0-R2 only: `core/platform/architecture_contract.py`, the additive successor registry, target tests, and this documentation.
- `pc0_composition_baseline.json`, historical NCE/H1B, PC8 contract and manifest, and PC0-R1 VN0-C2 successor are untouched.
- `kernel_router.py`, XafPay V2 contract, middleware, settings, auth, policy, browser-session, Restaurant, orders and inventory source remain unchanged.
- Database / migration mutation: 0. Remote push / merge / tag / deployment: 0.
- A subsequent PCR release must cover accepted migration-extension inventory and the accepted N2 module-map dependency, plus provide a workable source-attestation lifecycle for PC0 validator/test files modified in the current tranche.

**Disposition:** `PC0-R2=BLOCKED` pending additional contract authority. Never promote the accepted-source registry's success to full PC0/VN0 acceptance while the other independent PC0 gates are red.
