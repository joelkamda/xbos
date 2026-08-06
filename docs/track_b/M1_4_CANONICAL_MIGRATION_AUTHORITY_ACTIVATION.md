# XBOS Track B M1.4 — Canonical Migration Authority Activation

**Record type:** Migration-authority activation and local adoption record

**Workstream:** Track B-FIN — Neutral Financial Spine

**Phase:** M1.4

**Status:** Activation candidate

**Date:** 6 August 2026

**Predecessor:** M1.3 canonical foundation at `d7edf61`

## 1. Decision

The M1.3 lineage has passed fresh reconstruction, empty downgrade/re-upgrade and existing-state adoption rehearsals. M1.4 promotes that proven lineage to the sole active Alembic authority for XBOS.

After activation:

```text
alembic.ini -> alembic_neutral -> m13_financial_foundation_002
```

The directories `alembic` and `alembic_reconstruction` remain version-controlled evidence, but neither is an active migration authority. `alembic_neutral.ini` remains a rehearsal alias pointing to the same canonical lineage; it is not a second lineage.

## 2. Configuration correction

The previous `alembic.ini` contained a database URL with embedded credentials and pointed to the non-reconstructable source history. M1.4 changes only:

```ini
script_location = %(here)s/alembic_neutral
sqlalchemy.url = driver://unused
```

Runtime connection resolution remains centralized through the approved persistence configuration. Credentials must not be committed in Alembic configuration.

## 3. Adoption target

This activation package is restricted to:

```text
host     = localhost / loopback
database = xbos_track_b_dev
```

It cannot activate production, parity, WND, USA or an arbitrary database. Broader rollout requires a later approved plan.

## 4. Adoption preconditions

The tool requires all of the following:

- exact local database name;
- raw database revision `5c706797029a`;
- an exact table-inventory match with the approved M1.2 source-state SQL;
- absence of all 15 canonical foundation tables;
- active canonical `alembic.ini` configuration;
- explicit database and source-revision confirmations.

No source row is transformed, copied, deleted or rewritten. Adoption changes the migration authority stamp and adds the empty M1 foundation.

## 5. Activation sequence

### 5.1 Static inspection

```bat
python -m json.tool contracts\persistence\v1\m14_canonical_migration_authority.json > nul
python -m py_compile core\persistence\m14_authority.py scripts\activate_canonical_migration_authority.py tests\contracts\test_m14_canonical_migration_authority.py
python scripts\activate_canonical_migration_authority.py config-status
python scripts\activate_canonical_migration_authority.py preflight
```

Expected preflight state:

```text
authority_state=ready_for_adoption
```

### 5.2 Activate repository configuration

```bat
python scripts\activate_canonical_migration_authority.py activate-config
python scripts\activate_canonical_migration_authority.py config-status
python -m alembic heads
python -m alembic history
```

Expected head:

```text
m13_financial_foundation_002 (head)
```

### 5.3 Static tests

```bat
python -m pytest tests\contracts\test_m14_canonical_migration_authority.py -q
python -m pytest tests\contracts -q
```

### 5.4 Adopt the local development database

Stop any XBOS process writing to `xbos_track_b_dev`, then run:

```bat
python scripts\activate_canonical_migration_authority.py adopt --confirm-database-name xbos_track_b_dev --confirm-source-revision 5c706797029a
```

### 5.5 Verify

```bat
python scripts\activate_canonical_migration_authority.py preflight
python -m alembic current
python -m pytest tests\contracts -q
python -m pytest -q
git diff --check
git status --short --untracked-files=all
```

Expected state:

```text
authority_state=adopted_empty
m13_financial_foundation_002 (head)
```

## 6. Empty-foundation rollback

Rollback is available only while every M1 foundation table is empty:

```bat
python scripts\activate_canonical_migration_authority.py rollback-empty --confirm-database-name xbos_track_b_dev --confirm-empty-foundation-rollback EMPTY-M14-FOUNDATION
```

The command drops only the empty foundation, restores the source authority stamp, and verifies the exact source table inventory. Configuration can then be reverted through Git if the activation commit has not been approved.

Once later slices write canonical records, destructive rollback is prohibited. Correction becomes forward-only.

## 7. Explicit non-changes

M1.4 does not:

- seed the financial event catalog;
- emit financial events;
- transform WND or historical rows;
- change payment, sales, accounting or reconciliation writers;
- activate XafPay callbacks;
- cut over application APIs;
- operate on production or parity databases.

## 8. Exit gate

M1.4 is complete when:

- `alembic.ini` has no credentials and points to `alembic_neutral`;
- normal `python -m alembic` commands show one canonical head;
- the local development database is adopted at that head;
- all canonical foundation tables exist and remain empty;
- exact source tables remain present;
- contract and full regression suites pass;
- the worktree contains only reviewed M1.4 changes.

Passing this gate completes the migration-authority portion of M1. It still does not authorize canonical financial writes.
