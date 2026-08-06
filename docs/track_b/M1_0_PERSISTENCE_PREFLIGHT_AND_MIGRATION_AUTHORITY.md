# XBOS Track B — M1.0 Persistence Preflight and Migration Authority

**Record type:** Implementation checkpoint and migration safety authority
**Workstream:** Track B-FIN — Neutral Financial Spine
**Phase:** M1.0 — Persistence Preflight
**Status:** Approved implementation candidate
**Date:** 6 August 2026
**M0 baseline:** `track-b-m0-neutral-contracts-20260806` at `1f047a5`

## 1. Outcome

M1.0 establishes the persistence infrastructure required before the first canonical table migration. It unifies database URL resolution, removes embedded credentials, activates deterministic metadata naming, registers the complete current ORM model boundary, hardens Alembic comparison settings, and makes known migration limitations executable rather than implicit.

M1.0 creates no table, column, constraint, index, trigger, view, or database role.

## 2. Preflight evidence

The verified migration topology is:

```text
86322f59e0de
  -> fff36dab3483
  -> 577f5fc9b121
  -> 5c706797029a (single head)
```

The `xbos`, `xbos_track_b_parity`, and `xbos_track_b_test` databases all reported revision `5c706797029a`. PostgreSQL transactional DDL is active and Alembic reports no branches.

## 3. Critical findings

### 3.1 Empty-database reconstruction gap

The root revision `86322f59e0de` is an empty baseline for an already existing database. The next revision expects shared tables such as `tenants`, `branches`, and `users` to exist. Therefore, the historical chain cannot currently construct XBOS from an empty PostgreSQL database.

M1.0 does not rewrite an already applied historical revision. The gap is recorded as an open M1 release blocker. Additive Slice 1 development may proceed on disposable databases based on the verified platform revision, but M1 cannot close until an authoritative platform-bootstrap or replacement-baseline strategy is approved and tested.

### 3.2 Incomplete model registration

The prior `core.models_import` omitted orders, payment intents, payment attempts, A/R, and repayments. It also did not explain the duplicate inventory model modules.

M1.0 introduces an explicit module registry and establishes `core.domain.inventory.models` as the temporary registered owner of `inventory_items` and `inventory_movements`. The duplicate `core.domain.catalog.models` module is deliberately excluded pending its later retirement or migration.

### 3.3 Split connection authority

The application previously used `database.py`, while Alembic used its INI configuration path. Both happened to resolve to the same local database, but the mechanisms could drift. M1.0 makes both consumers call one resolver.

## 4. Database URL resolution

The shared resolver uses this precedence:

1. process `DATABASE_URL`;
2. project environment-file `DATABASE_URL`;
3. explicit Alembic configuration URL.

Only PostgreSQL URLs naming a database are accepted. No credential-bearing fallback URL remains in source code. The environment-file parser is dependency-free because the repository does not declare `python-dotenv`.

## 5. Metadata authority

`core.persistence.metadata.metadata` becomes the sole SQLAlchemy metadata object used by `database.Base`.

The naming convention supplies deterministic fallbacks for previously unnamed objects. New canonical models must still explicitly name every semantic constraint and access-path index according to the B2 physical blueprint. The PostgreSQL 63-byte identifier limit remains mandatory.

Canonical tables stay in `public` during the compatibility migration.

## 6. Alembic behavior

Alembic now:

- uses the shared database URL resolver;
- imports the explicit model registry;
- compares SQL types;
- compares server defaults;
- excludes additional PostgreSQL schemas during this migration series;
- runs each migration transactionally;
- uses `NullPool` for migration connections.

Autogeneration remains review-only and blocked pending an explicit metadata-versus-database drift audit. No generated migration may be applied without human review and contract tests.

The next approved revision must descend from `5c706797029a`.

## 7. Database safety

Automated schema mutation is restricted to:

- `xbos_track_b_test`;
- disposable databases whose names begin with `xbos_migration_test_`.

The parity database is a read-only source for creating disposable rehearsal clones. WND production migration remains forbidden without separate Track A stability and rollout approval.

## 8. Files in this checkpoint

| File | Change |
|---|---|
| `core/persistence/__init__.py` | New persistence package boundary |
| `core/persistence/database_config.py` | New shared, dependency-free URL resolver |
| `core/persistence/metadata.py` | New deterministic metadata authority |
| `database.py` | Replaced embedded fallback and attached authoritative metadata |
| `core/models_import.py` | Replaced incomplete imports with explicit module registry |
| `alembic/env.py` | Unified URL resolution and hardened migration context |
| `contracts/persistence/v1/migration_authority.json` | Machine-readable M1 migration authority |
| `tests/contracts/test_persistence_foundation.py` | 25 executable M1.0 assertions |
| `docs/track_b/M1_0_PERSISTENCE_PREFLIGHT_AND_MIGRATION_AUTHORITY.md` | This approval and operating record |

## 9. Verification

From the repository root, with the project environment active:

```bat
python -m py_compile core\persistence\__init__.py core\persistence\database_config.py core\persistence\metadata.py database.py core\models_import.py alembic\env.py tests\contracts\test_persistence_foundation.py

python -m pytest tests\contracts\test_persistence_foundation.py --collect-only -q
python -m pytest tests\contracts\test_persistence_foundation.py -q
python -m pytest tests\contracts -q
python -m pytest --collect-only -q
python -m pytest -q

python -m alembic heads
python -m alembic current

python -c "from database import engine; print(engine.url.render_as_string(hide_password=True))"
python -c "import core.models_import; from database import Base; print('registered_tables=', len(Base.metadata.tables)); print('\n'.join(sorted(Base.metadata.tables)))"

git diff --check
git status --short --untracked-files=all
```

Expected test totals:

- 25 M1.0 tests;
- 155 contract tests;
- 173 complete tests;
- the existing deprecation-warning count should not materially increase.

Expected Alembic result:

```text
5c706797029a (head)
```

No migration revision or database object is added by M1.0.

## 10. Rollback before commit

If verification fails, preserve the output and do not stage the files. The changes can be reviewed individually because M1.0 performs no database mutation.

## 11. Exit gate

M1.0 is complete when:

```text
Application and Alembic share one safe database URL authority;
metadata naming and model registration are deterministic and complete;
the Alembic head remains unchanged; all 173 tests pass; and the known
fresh-database gap remains explicit as an M1 release blocker.
```

## 12. Next checkpoint

M1.1 performs the metadata drift audit and prepares the first handwritten, additive Slice 1 migration plan. It will define the shared registries, currency and business-cycle policies, operational/provider accounts, idempotency, outbox, and document sequences without modifying legacy financial tables.
