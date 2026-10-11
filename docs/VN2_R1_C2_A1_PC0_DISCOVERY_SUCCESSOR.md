# XBOS VN2 C2 A1-R1 — pre-implementation PC0 discovery successor

**Authority:** `XBOS-NEUTRAL-VN2-R1-C2-A1-R1`; parent A1 `BLOCKED_ACCEPTED` because PCR corrected the predecessor SHA pins. A0 topology is accepted and unchanged. All four corrected hashes were reverified both against the working tree and committed `git show HEAD:<path>` using canonical LF-normalized SHA-256 before branch creation.

**Accepted C1 predecessor:** `45f2313dbb57fc3f6b50638b279c2bf581234e5e`; tree `8b21a3aee557c04fbc8e282bb42e42fdfa6e8f1e`. **Local branch:** `platform/neutral-vnext-vn2-pc0-discovery-successor`. One local commit permitted; no remote push or deployment.

## Corrected four immediate predecessors

| Frozen C1 path | PCR-corrected accepted SHA-256 | A1 result |
|---|---|---|
| `core/api/kernel_router.py` | `243a6f77c8804eaff82cb131f8edc5d6dcd24e47ecafd6fa7f8ae660f2d97b00` | Unchanged |
| `core/middleware/auth_middleware.py` | `e03e258e5ebb574445b3a29e4db950f6ef80dde7b8fc344b45d7f781dc64b8d4` | Unchanged |
| `core/platform/architecture_contract.py` | `28515d9fda2ee909497cf0bb30fd3e4cfb04ecefcc99ec7e1eda60074078c888` | **Only existing source modified** |
| `tests/contracts/test_pc0_kernel_boundaries.py` | `1fc07557db90914d48a5a8cce23e485a71849649fb25f3e955580f249717d565` | Unchanged |

PCR's withdrawn A1 predecessor hashes are not used as accepted predecessors. The historical VN0-C2 kernel SHA equals the current kernel SHA. No artificial kernel transition was created.

## A1 admission (not implementation)

`contracts/platform/v1/pc0_vn2_c2_discovery_admission.json` is an exact-value admission with authority `XBOS-NEUTRAL-VN2-R1-C2-A1-R1`, accepted parent commit, the frozen C1 name and route, future source ownership, two exact future dependency imports, one additive public PK discovery read interface, four corrected source predecessors, security/read-only conditions, and pre-activation law.

Future new file paths:

- `core/auth/pack_template_discovery_router.py`: **PC0 identity**, owner **PC5**.
- `pack_platform/discovery_read_model.py`: **PC0 packs**, owner **PK**.

Only two future extra cross-module imports may be registered, both originating at the exact future Identity adapter path:

1. `(core/auth/pack_template_discovery_router.py, database, identity, application)`
2. `(core/auth/pack_template_discovery_router.py, pack_platform.discovery_read_model, identity, packs)`

The `composition → identity` kernel-router import is already allowed by the frozen general policy. Broad `composition → packs`, `identity → packs`, `identity → application`, `packs → identity`, or `packs → application` directions are **NOT** authorized. The historical PC0 module map, general policy, public/private interface baseline and legacy exceptions remain immutable.

The future PK discovery read surface is an additive public *interface declaration only*. Neither private PK SQL repository becomes a public interface.

## Pre-activation and future seal

A1 leaves the future router, PK discovery read model, kernel wiring, auth middleware discovery-path change, and `contracts/platform/v1/pc0_vn2_c2_discovery_implementation_seal.json` **absent**.

The updated PC0 validator requires the absent state and exact accepted kernel/auth hashes. A future unsealed router, unsealed read model, mutated kernel, or mutated auth middleware fails closed. When the future implementation seal is materialized under **separate PCR C2 authority**, PC0 is prepared to validate the exact four future source path digests, the two exact import keys, unchanged accepted predecessors, immutable markers, and read-only SQL conditions before it admits either dependency edge. No future implementation is automatically activated by the presence of this admission contract alone.

Accepted browser session validation and `/auth/me` semantics remain the only authenticated tenant source. No X-Tenant-Code, dev fallback, legacy access token, inferred entitlement/eligibility, default pack or default template may be trusted. The future DB transaction is read-only. C1's discovery schema stays untouched.

## R5 validator successor chain

`contracts/platform/v1/pc0_validator_successor_seal_r5.json` records a single permitted changed source: `core/platform/architecture_contract.py`, predecessor SHA `28515d9f...`, and the exact canonical LF SHA-256 of A1's final successor. It references the accepted C1 predecessor commit rather than its own final Git commit. The validator checks unchanged archival R3 and R4 seal contents, and preserves the R4-accepted unchanged PC0 test SHA rather than manufacturing a test-source successor.

A1 recognizes its validator successor through the H1B and PC0 release-integrity checks without rewriting historical H1B, NCE, VN0-C2, R3 or R4 fingerprints.

## Test results and regression disclosure

- **A1 targeted exact governance / negative tests: 28 PASS.**
- **VN2 C1 contract: 20 PASS.**
- **PK0123: 4 PASS. PK456: 7 PASS.**
- **PC6: 18 PASS.**
- **Full real repository PC0 `validate_pc0`: PASS** (release-integrity included; see A1 target test).
- **Current-HEAD legacy PC0 test suite: 20 PASS / 1 FAIL.** `test_real_composition_source_change_fails` constructs a partial temporary fixture that copies the R3/R4 attestations but not the newly added A1 admission and R5 seal. The new validator (correctly) rejects the copied R5-era architecture source with `PC0-R4-SEAL-SOURCE-CHANGED` before the test's injected `database.py` mutation is reached. A1 explicitly forbids edits to the legacy test file. This is a **new A1-era historical test-fixture incompatibility** and cannot be claimed as an inherited C1 failure or as a green current-HEAD PC0 suite. Separate PCR disposition or bounded test-fixture successor authority is required. Do not bypass source attestation to make the fixture green.
- **PK aggregate: 10 PASS / 2 FAIL**, exactly the existing `PC8_SUCCESSOR_DESCENDANT_HASH_MISMATCH=core/platform/architecture_contract.py` failures independently established at the accepted C1 parent. Historical exception was accepted for C1 only; A1 has not changed or relabeled PC8 history. No additional PK aggregate failures.

## Firewall and pending disposition

Only five source paths authorized by A1 are in this local commit: the validator, admission JSON, R5 seal JSON, this evidence doc, and the dedicated A1 tests. No route/read-model source, business source, existing test source, PK repository, DB migrations, runtime settings, frontend, or database was changed. No push, merge, tag, deployment, pack effect or financial effect.

**A1-R1 execution disposition:** the bounded implementation and preactivation protections are complete, but final PASS is **blocked by the legacy PC0 test-suite requirement (20/21)** until PCR adjudicates a bounded historical fixture successor. C2 implementation remains HOLD.
