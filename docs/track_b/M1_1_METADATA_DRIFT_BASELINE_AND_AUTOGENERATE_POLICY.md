# XBOS Track B M1.1 — Metadata Drift Baseline and Alembic Autogenerate Policy

**Record type:** Persistence architecture decision and executable safety baseline

**Workstream:** Track B-FIN — Neutral Financial Spine

**Milestone:** M1.1 — Metadata drift containment

**Status:** Implementation candidate

**Date:** 6 August 2026

**Source baseline:** `a967b93` at Alembic revision `5c706797029a`

## 1. Outcome

M1.1 establishes a safe boundary between XBOS's observed compatibility schema and
the additive canonical persistence work that follows.

The live local schema and the authoritative ORM metadata are materially different.
Running Alembic autogenerate without a boundary would propose destructive changes
that are unrelated to the approved canonical migration slices. M1.1 records that
drift and prevents Alembic from generating operations against every existing public
table.

New canonical tables are not excluded. They remain visible to Alembic and must be
introduced by reviewed, handwritten, additive migrations.

M1.1 does **not** execute a migration, alter a table, remove staging data, or repair
historical schema drift.

## 2. Observed schema inventory

The inventory was taken after M1.0 with all databases at migration head
`5c706797029a`.

| Classification | Count | Meaning |
|---|---:|---|
| Database tables | 27 | All observed tables in PostgreSQL `public` |
| ORM tables | 21 | Tables registered in authoritative SQLAlchemy metadata |
| Common tables | 21 | Present in both database and ORM metadata |
| ORM-only tables | 0 | No registered ORM table is absent from the database |
| Database-only application tables | 2 | Preserved tables not represented by the ORM registry |
| WND staging tables | 3 | Preserved staging/import data |
| Alembic internal tables | 1 | `alembic_version` |

The six database-only tables are:

- `alembic_version`;
- `billable_unit_taxonomy`;
- `idempotency_keys`;
- `wnd_inventory_aliases`;
- `wnd_inventory_real_staging`;
- `wnd_inventory_staging`.

All 27 observed tables are classified in
`contracts/persistence/v1/metadata_drift_baseline.json`.

## 3. Raw Alembic comparison result

Before this policy, `python -m alembic check` detected 179 comparison notices.

| Notice category | Count |
|---|---:|
| Removed index | 29 |
| Server default | 27 |
| Added index | 26 |
| Nullability | 20 |
| Column comment | 15 |
| Type change | 14 |
| Owned sequence notice | 13 |
| Removed column | 9 |
| Removed unique constraint | 8 |
| Added unique constraint | 6 |
| Removed table | 5 |
| Removed foreign key | 4 |
| Added foreign key | 3 |
| **Total** | **179** |

The proposed operations included five table drops, nine column removals, replacement
of working indexes and constraints, changes from `JSONB` to `JSON`, and changes to
defaults, types, comments, nullability, and foreign keys on active financial and
operational tables.

These notices describe ORM/database drift. They are not an approved canonical
migration plan.

## 4. Decision

### 4.1 Protected compatibility inventory

Alembic autogenerate excludes:

- all 21 existing ORM-backed tables;
- both database-only application tables;
- all three WND staging tables;
- `alembic_version`.

The exclusion applies to each protected table and its columns, indexes, unique
constraints, foreign keys, checks, and other child objects.

### 4.2 Canonical additions stay visible

Any table not in the frozen protected inventory remains visible to Alembic. This is
the path for canonical additions such as financial accounts, postings, allocations,
outbox messages, and other approved neutral persistence entities.

### 4.3 Existing-table changes require explicit migrations

The filter is not a declaration that existing tables can never change. It prevents
unreviewed changes from being inferred from metadata drift.

If a canonical slice must change an existing table, the migration must be:

1. handwritten;
2. additive unless a separately approved cutover says otherwise;
3. linked to a domain migration and backfill plan;
4. reviewed for tenant, branch, money, idempotency, and rollback safety;
5. verified against the parity and test databases before production use.

## 5. Files introduced or changed

| File | Purpose |
|---|---|
| `core/persistence/alembic_policy.py` | Frozen protected-table inventory and `include_object` callback |
| `alembic/env.py` | Installs the callback for online and offline comparison contexts |
| `contracts/persistence/v1/metadata_drift_baseline.json` | Machine-readable observed drift and policy record |
| `tests/contracts/test_metadata_drift_policy.py` | DB-free executable policy and integrity tests |
| This record | Human-readable rationale and operating procedure |

## 6. Safety properties

M1.1 makes these rules executable:

- no observed table can be silently treated as an autogenerate drop candidate;
- no existing ORM table can be rewritten because model declarations drifted from
  PostgreSQL;
- WND staging tables remain preserved;
- database-only operational tables remain preserved;
- new canonical tables remain discoverable;
- protected-table changes require deliberate migration code;
- the current database remains unchanged during this milestone.

## 7. Verification procedure

Run from the repository root with the Track B virtual environment active.

```bat
python -m json.tool contracts\persistence\v1\metadata_drift_baseline.json > nul

python -m py_compile core\persistence\alembic_policy.py alembic\env.py tests\contracts\test_metadata_drift_policy.py

python -m pytest tests\contracts\test_metadata_drift_policy.py --collect-only -q
python -m pytest tests\contracts\test_metadata_drift_policy.py -q

python -m alembic heads
python -m alembic current
python -m alembic check

python -m pytest tests\contracts -q
python -m pytest -q

git diff --check
git status --short --untracked-files=all
```

Expected results for this slice:

- 20 M1.1 contract tests collected and passing;
- one Alembic head: `5c706797029a`;
- current database revision: `5c706797029a`;
- `alembic check`: no new upgrade operations detected;
- 175 contract tests passing;
- 193 total tests passing;
- the existing 48 deprecation warnings may remain;
- no migration file and no database mutation.

## 8. Exit gate

M1.1 is complete when:

- all 27 existing public tables are classified;
- all 21 ORM tables are protected from inferred rewrites;
- database-only and staging tables are protected from inferred drops;
- new canonical tables remain visible;
- `alembic check` is clean at revision `5c706797029a`;
- all tests pass;
- the worktree contains only the five intended M1.1 file changes;
- no database object has been mutated.

## 9. What remains open

This milestone contains drift; it does not erase it. The known historical migration
chain still cannot reconstruct an empty database because its root revision is a
no-op. That release blocker remains open for a dedicated additive bootstrap or
baseline strategy.

The next persistence slice may proceed only from this protected comparison boundary
and must not rewrite historical migrations.
