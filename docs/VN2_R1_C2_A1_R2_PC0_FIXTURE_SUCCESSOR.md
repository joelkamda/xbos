# XBOS VN2-R1-C2-A1-R2 — PC0 legacy fixture and exact R6 governed source successor

PCR authority: `XBOS-NEUTRAL-VN2-R1-C2-A1-R2` (2026-10-11).
Accepted parent source: `c5e031b437561363dcb94b43ca9b52ac25ddadf8`;
tree `a28b70cae7fbfb6b7de0e93fc03cfb42b0b2fd92`;
branch `platform/neutral-vnext-vn2-pc0-discovery-successor`.

## Exact lineage and source scope

PCR-pinned parent canonical LF-normalized SHA-256:

| Path | Accepted A1-R1 predecessor | R6 successor |
|---|---|---|
| `core/platform/architecture_contract.py` | `75c42332159c9673a3e081eb6fc682303bdec8174a9a4e34c1ca6d9689d4d02f` | `8d319746041073680268fd20f123a06c0190368083cd0e37b8b1565cfd5ffc9d` |
| `tests/contracts/test_pc0_kernel_boundaries.py` | `1fc07557db90914d48a5a8cce23e485a71849649fb25f3e955580f249717d565` | `7022b90767677e0707be6be752907405f7edb291561a9a4f6fb05a3f5e4c07ac` |

The new `contracts/platform/v1/pc0_validator_successor_seal_r6.json` is pinned to the accepted predecessor commit, exact R6 authority and only these two paths. The validator checks exact predecessors, nontrivial successors, current source digests, and rejects duplicate, wildcard, unauthorized, or extra paths. No current commit identity is embedded in source. No generic hash acceptance is enabled.

The R6 validator ensures the previously accepted R5 source seal is still byte-identical to its SHA-256 `8d2846131f4c4c9ac06a109de82574ad5b20fbd7639dfc366f0b7d2e87d898cd`, and the A1 admission is unchanged at `5a9501d193abd96918d6af8681a1ff9feedf5f73e3853c7600228c3b95f5c3e3`. Historical R3/R4 values and immutable R5 predecessor remain preserved; R6 validates the **current** two source files. This does not overwrite historical R4/R5 seals.

## Original regression repair

The original `test_real_composition_source_change_fails` fixture now copies the three additional accepted materials:

- `contracts/platform/v1/pc0_vn2_c2_discovery_admission.json`
- `contracts/platform/v1/pc0_validator_successor_seal_r5.json`
- `contracts/platform/v1/pc0_validator_successor_seal_r6.json`

The original negative assertion remains unchanged: `PC0-COMPOSITION-CHANGED: database.py`. It still appends `# real mutation` to the candidate `database.py`, and now successfully reaches this negative check after verifying the R6 source chain. A further four test cases validate the R6 exact seal, unauthorized path/wildcard, wrong predecessor or successor digest, authority and predecessor commit.

## Test evidence and historical snapshot distinction

- Original failing fixture: **1 PASS**.
- Full current-head PC0 tests: **25 PASS / 0 FAIL** (existing 21 plus four R6 negatives).
- Complete current-head C1 discovery contract: **20 PASS**.
- PC6: **18 PASS**.
- PK0123: **4 PASS**; PK456: **7 PASS**.
- PK aggregate: **10 PASS / 2 FAIL**. Both match the pre-existing PC8 `PC8_SUCCESSOR_DESCENDANT_HASH_MISMATCH=core/platform/architecture_contract.py` classification; no third failure. Not reported as globally passing.
- Unmodified A1-R1 targeted tests **replayed at exact accepted source commit** `c5e031b437561363dcb94b43ca9b52ac25ddadf8`: **28 PASS**, temporary detached worktree removed.
- The same A1-R1 tests on the **current R6 HEAD**: **25 PASS / 3 historical snapshot failures**. The three assert R4 test/R5 validator SHA values against the **current** files instead of the accepted A1-R1 snapshot. These expectations were true at A1-R1; R6 explicitly authorizes the two changed sources. This tranche does not permit modification of `tests/contracts/test_vn2_c2_a1_pc0_discovery_successor.py`. PCR must adjudicate whether historical A1 replay is sufficient for this R2 gate, as was separately accepted for R3. These failures are not silently treated as PASS.

## Effect firewall

No discovery HTTP route, PK read model, implementation seal, kernel wiring, auth middleware, database access, migration, pack/template activation, frontend change, env mutation or deployment. No tag, merge, rebase, remote push or financial effect.

Four total R2 paths: the two exactly authorized existing source files, the single R6 JSON seal, and this optional evidence document. One additional local commit maximum; C2 implementation remains HOLD. Final PCR adjudication required.
