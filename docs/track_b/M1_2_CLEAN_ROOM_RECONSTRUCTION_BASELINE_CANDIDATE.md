# XBOS Track B M1.2 — Clean-Room Reconstruction Baseline Candidate

**Record type:** Schema reconstruction decision, candidate baseline, and safety runbook

**Workstream:** Track B-FIN — Neutral Financial Spine

**Milestone:** M1.2 — Fresh-database reconstruction proof

**Status:** Revision 2 candidate awaiting clean-room execution

**Date:** 6 August 2026

**Source checkpoint:** `2f6cedb` at active revision `5c706797029a`

## 1. Outcome

M1.2 introduces an isolated Alembic candidate that can reconstruct the observed XBOS
source-state schema from an empty local PostgreSQL database without application row
data and without `Base.metadata.create_all()`.

The candidate is deliberately not the active migration history. It must first pass a
clean-room reconstruction against one exact disposable database. Existing XBOS, WND
parity, and Track B test databases are rejected by code.

M1.2 does not:

- change `alembic.ini`;
- edit or move the four historical migration revisions;
- change any existing `alembic_version` stamp;
- execute against production, parity, or the characterization database;
- declare WND staging structures to be part of the neutral target architecture;
- activate the candidate as production migration authority.

## 2. Why an isolated candidate is required

The active lineage is:

```text
<base>
  -> 86322f59e0de  baseline_existing_db (no-op)
  -> fff36dab3483  add_tier1_business_tables
  -> 577f5fc9b121  lock_receipt_no_and_cleanup_sales
  -> 5c706797029a  add_treasury_logs
```

Appending a revision after `5c706797029a` cannot repair empty-database reconstruction.
On a blank database, execution fails earlier because the no-op root does not create
foundational tables required by later revisions.

Changing a historical `down_revision`, silently replacing a revision body, or
pointing the main Alembic configuration at a new lineage before rehearsal would hide
the problem instead of controlling it.

The approved M1.2 sequence is therefore:

1. freeze the source schema and historical revision hashes;
2. create a separate one-root/one-head baseline candidate;
3. execute it only against a guarded disposable database;
4. verify the reconstructed object inventory;
5. review the result;
6. decide candidate adoption in a later explicit milestone.

### 2.1 Revision 2 correction

The first clean-room execution correctly created and retained only the disposable
database, but failed while Alembic wrote its final revision stamp. The schema-only
dump had set the connection's session `search_path` to empty, so Alembic's
unqualified insert could not resolve `alembic_version`.

Revision 2:

- removes that session-level `search_path` mutation from the SQL asset;
- configures Alembic's version-table schema explicitly as `public`;
- reads `public.alembic_version` explicitly during verification;
- leaves all source schema objects and the candidate revision identifier unchanged.

The failed attempt did not change production, parity, characterization, or active
migration-history state.

## 3. Source evidence

The schema-only PostgreSQL dump came from `xbos_track_b_parity` on PostgreSQL 17.5.

| Evidence | Value |
|---|---|
| Source schema SHA-256 | `db109eb0a6f8c508fe235dc3635407f91bd2c71e41505a5820be3af82107d09f` |
| Application and staging tables | 26 |
| Tables including `alembic_version` | 27 |
| Sequences | 21 |
| Explicit indexes | 83 |
| `ADD CONSTRAINT` declarations | 64 |
| Inline constraints | 2 |
| Functions | 1 |
| Extensions | 1 (`pgcrypto`) |
| `COPY` statements | 0 |
| `INSERT` statements | 0 |

The SQL asset differs from the source dump only by removing creation and constraint
DDL for `alembic_version`. Alembic owns that table during upgrade.

## 4. Source state versus neutral target

The candidate reconstructs the audited starting point so migration work becomes
reproducible. It is not the final neutral schema.

In particular:

- `wnd_inventory_aliases`, `wnd_inventory_real_staging`, and
  `wnd_inventory_staging` are source-state evidence, not neutral kernel entities;
- current sales, payment, A/R, treasury, and reconciliation structures remain
  compatibility/source structures pending canonical migration;
- future canonical tables continue to follow the approved B2 physical blueprint;
- WND will be migrated into the Restaurant pack and tenant profile rather than
  becoming the platform architecture.

This reconstruction proof therefore creates a reliable departure point without
constraining the destination.

## 5. Candidate structure

| File | Responsibility |
|---|---|
| `alembic_reconstruction.ini` | Separate candidate configuration |
| `alembic_reconstruction/env.py` | Local disposable-target enforcement |
| `alembic_reconstruction/versions/m12_source_state_001_source_state_baseline.py` | One root/head, checksum-verified baseline |
| `alembic_reconstruction/sql/source_state_baseline.sql` | Schema-only source-state DDL |
| `core/persistence/reconstruction_policy.py` | Exact database and host safety boundary |
| `contracts/persistence/v1/reconstruction_baseline.json` | Machine-readable evidence and authority decision |
| `scripts/verify_fresh_database_reconstruction.py` | Guarded create, upgrade, verify, inspect, and explicit drop workflow |
| `tests/contracts/test_reconstruction_baseline.py` | DB-free executable contract tests |

## 6. Safety boundary

The candidate accepts only:

```text
database: xbos_track_b_reconstruction_test
hosts:    localhost, 127.0.0.1, ::1
backend:  PostgreSQL
```

It explicitly rejects:

- `xbos`;
- `xbos_track_b_parity`;
- `xbos_track_b_test`;
- any remote host;
- any non-PostgreSQL URL.

Creation refuses to overwrite an existing database. Failure retains the disposable
database for inspection. Drop is a separate command requiring the exact database
name as confirmation.

## 7. Installation verification

Run from the XBOS repository root with the Track B environment active.

```bat
python -m json.tool contracts\persistence\v1\reconstruction_baseline.json > nul

python -m py_compile core\persistence\reconstruction_policy.py alembic_reconstruction\env.py alembic_reconstruction\versions\m12_source_state_001_source_state_baseline.py scripts\verify_fresh_database_reconstruction.py tests\contracts\test_reconstruction_baseline.py

python -m pytest tests\contracts\test_reconstruction_baseline.py --collect-only -q
python -m pytest tests\contracts\test_reconstruction_baseline.py -q

python -m alembic heads
python -m alembic current
python -m alembic check

python -m alembic -c alembic_reconstruction.ini heads

python scripts\verify_fresh_database_reconstruction.py status
```

Expected before clean-room execution:

- 25 M1.2 tests collected and passing;
- main Alembic head/current remains `5c706797029a`;
- main `alembic check` remains clean;
- candidate has one head: `m12_source_state_001`;
- disposable database reports `exists=false`.

## 8. Clean-room execution

Only after the preceding checks pass:

```bat
python scripts\verify_fresh_database_reconstruction.py create-and-verify
```

Expected result:

```text
M1.2 clean-room reconstruction: PASS
database=xbos_track_b_reconstruction_test
revision=m12_source_state_001
tables=27
sequences=21
explicit_indexes=83
constraints=66
extension=pgcrypto
function=xbos_taxonomy_tree
```

Verify again without rebuilding:

```bat
python scripts\verify_fresh_database_reconstruction.py verify-existing
```

Keep the disposable database until the M1.2 evidence is reviewed. Its later removal
is explicit:

```bat
python scripts\verify_fresh_database_reconstruction.py drop --confirm-database-name xbos_track_b_reconstruction_test
```

## 9. Regression verification

After reconstruction passes:

```bat
python -m pytest tests\contracts -q
python -m pytest -q

git diff --check
git status --short --untracked-files=all
```

Expected totals:

- 200 contract tests passing;
- 218 total tests passing;
- the existing 48 deprecation warnings may remain;
- nine intended new M1.2 files;
- no modification to the active migration history;
- no modification to existing database stamps.

## 10. Exit gate

M1.2 is complete when:

- source schema and historical revision checksums are frozen;
- the baseline contains no business row data;
- the candidate exposes one root and one head;
- wrong databases and remote hosts are rejected;
- a new disposable database upgrades to `m12_source_state_001`;
- its public table inventory matches the contract exactly;
- sequences, explicit indexes, constraints, `pgcrypto`, and
  `xbos_taxonomy_tree` are present;
- the main Alembic lineage and existing database stamps remain unchanged;
- all tests pass.

## 11. Next decision

Passing M1.2 proves that the source state is reconstructible. It does not activate
the candidate.

The next persistence milestone must review baseline adoption and the first canonical
structural migration together. That avoids switching migration authority merely to
reproduce old structures without immediately advancing the neutral kernel.
