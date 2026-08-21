from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from restaurant.r6 import (
    CANDIDATE_DATABASE,
    CANONICAL_SOURCE_STAMP,
    DISPOSABLE_DATABASES,
    EXPECTED_COUNTS,
    KITCHEN_BON_PRESERVATION,
    REFERENCE_RELEASE_PRESERVATION,
    REFERENCE_RELEASE_TAG,
    REFERENCE_SOURCE_EVIDENCE_SHA256,
    PRODUCTION_BACKEND_RELEASE_BRANCH,
    PRODUCTION_FRONTEND_RELEASE_BRANCH,
    PRODUCTION_BACKEND_HEAD,
    PRODUCTION_BRANCH_ID,
    PRODUCTION_DATABASE,
    PRODUCTION_FRONTEND_HEAD,
    PRODUCTION_TENANT_ID,
    SERVER_BACKUP_FILENAME,
    SERVER_BACKUP_SHA256,
    SERVER_BACKUP_SIZE,
    SOURCE_DATABASE,
    SOURCE_REVISION,
    TARGET_HEAD,
)

SOURCE_CHECKPOINT = "2f90f17"
SOURCE_COMMIT = "2f90f1714782bcf54da6d8cac2cc0499d2e82dfc"
EXPECTED_BRANCH = "restaurant/r6-wnd-cutover"

KEY_COUNTS = EXPECTED_COUNTS

EXPECTED_TOTALS = {
    "sales": Decimal("35193200.00"),
    "orders": Decimal("38083300.00"),
    "ar_original": Decimal("736500.00"),
    "ar_paid": Decimal("96199.00"),
    "ar_balance": Decimal("640301.00"),
    "inventory_qoh": Decimal("1997976"),
    "inventory_movement_sum": Decimal("2143"),
}

EXPECTED_HISTORICAL_INVENTORY_MISMATCHES = 156
EXPECTED_HISTORICAL_INVENTORY_DELTA = Decimal("1995833")

CONTRACTS = (
    "contracts/restaurant/v1/r6_0_wnd_production_baseline.json",
    "contracts/restaurant/v1/r6_1_rehearsal_adoption_authority.json",
    "contracts/restaurant/v1/r6_1_control_totals.json",
)

# Frozen R4 certification evidence set, copied from the accepted R5 verifier.
# This is verifier support data, not Restaurant Pack public API.
R4_EVIDENCE_PATHS = (
    "contracts/restaurant/v1/r0_release_manifest.json",
    "contracts/restaurant/v1/r1_release_manifest.json",
    "contracts/restaurant/v1/r2_release_manifest.json",
    "contracts/restaurant/v1/r3_release_manifest.json",
    "contracts/packs/v1/pk_aggregate_release_manifest.json",
    "contracts/platform/v1/sc41_semantic_classification_hardening.json",
    "contracts/experience/v1/xa_release_manifest.json",
)
R4_TEXT_EVIDENCE_SUFFIXES = {".cmd", ".json", ".md", ".py", ".sql", ".txt"}



def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _r4_evidence_hashes() -> tuple[str, ...]:
    """Reproduce the frozen R4 certification evidence hashes used by accepted R5."""
    values: list[str] = []
    for relative in R4_EVIDENCE_PATHS:
        path = ROOT / relative
        data = path.read_bytes()
        if path.suffix.lower() in R4_TEXT_EVIDENCE_SUFFIXES:
            data = data.replace(b"\r\n", b"\n")
        values.append(hashlib.sha256(data).hexdigest())
    return tuple(values)



def _verify_release_manifest() -> int:
    manifest = _load("contracts/restaurant/v1/r6_1_release_manifest.json")
    if manifest.get("self_excluded") is not True:
        raise RuntimeError("R6_1_RELEASE_MANIFEST_SELF_EXCLUSION")
    artifacts = manifest.get("artifacts", [])
    if manifest.get("artifact_count") != len(artifacts):
        raise RuntimeError("R6_1_RELEASE_MANIFEST_COUNT")
    paths = [row["path"] for row in artifacts]
    if len(paths) != len(set(paths)):
        raise RuntimeError("R6_1_RELEASE_MANIFEST_DUPLICATE_PATH")
    if "contracts/restaurant/v1/r6_1_release_manifest.json" in paths:
        raise RuntimeError("R6_1_RELEASE_MANIFEST_SELF_INCLUDED")
    for row in artifacts:
        path = ROOT / row["path"]
        if not path.is_file():
            raise RuntimeError("R6_1_RELEASE_ARTIFACT_MISSING=" + row["path"])
        data = path.read_bytes()
        canonical = data.replace(b"\r\n", b"\n")
        digest = hashlib.sha256(canonical).hexdigest()
        if digest != row["sha256"]:
            raise RuntimeError("R6_1_RELEASE_ARTIFACT_HASH=" + row["path"])
        if len(data) != row["size"]:
            raise RuntimeError("R6_1_RELEASE_ARTIFACT_SIZE=" + row["path"])
    return len(artifacts)

def _static_verify() -> dict[str, Any]:
    baseline, authority, controls = (_load(path) for path in CONTRACTS)

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if branch != EXPECTED_BRANCH:
        raise RuntimeError(f"R6_1_WRONG_BRANCH expected={EXPECTED_BRANCH} actual={branch}")
    if head != SOURCE_COMMIT:
        raise RuntimeError(f"R6_1_SOURCE_HEAD_DRIFT expected={SOURCE_COMMIT} actual={head}")

    if baseline["server_evidence"]["database"] != PRODUCTION_DATABASE:
        raise RuntimeError("R6_0_PRODUCTION_DATABASE_DRIFT")
    if baseline["server_evidence"]["database_revision"] != SOURCE_REVISION:
        raise RuntimeError("R6_0_SOURCE_REVISION_DRIFT")
    if baseline["server_evidence"]["snapshot_backup"]["sha256"] != SERVER_BACKUP_SHA256:
        raise RuntimeError("R6_0_BACKUP_SHA_DRIFT")
    if baseline["server_evidence"]["snapshot_backup"]["size"] != SERVER_BACKUP_SIZE:
        raise RuntimeError("R6_0_BACKUP_SIZE_DRIFT")
    if baseline["runtime_source"]["backend_head"] != PRODUCTION_BACKEND_HEAD:
        raise RuntimeError("R6_0_BACKEND_HEAD_DRIFT")
    if baseline["runtime_source"]["frontend_head"] != PRODUCTION_FRONTEND_HEAD:
        raise RuntimeError("R6_0_FRONTEND_HEAD_DRIFT")
    reference = baseline["reference_release"]
    if reference["release_tag"] != REFERENCE_RELEASE_TAG:
        raise RuntimeError("R6_0_REFERENCE_TAG_DRIFT")
    if reference["backend_release_branch"] != PRODUCTION_BACKEND_RELEASE_BRANCH:
        raise RuntimeError("R6_0_BACKEND_RELEASE_BRANCH_DRIFT")
    if reference["frontend_release_branch"] != PRODUCTION_FRONTEND_RELEASE_BRANCH:
        raise RuntimeError("R6_0_FRONTEND_RELEASE_BRANCH_DRIFT")
    if reference["source_evidence_sha256"] != REFERENCE_SOURCE_EVIDENCE_SHA256:
        raise RuntimeError("R6_0_REFERENCE_SOURCE_EVIDENCE_DRIFT")
    if baseline["runtime_source"]["backend_source_archive_sha256"] != "eb489d820a0319b802cc06bcd0cad6a00727eff9e033e154dc0a2a5a04389838":
        raise RuntimeError("R6_0_BACKEND_SOURCE_ARCHIVE_DRIFT")
    if baseline["runtime_source"]["frontend_source_archive_sha256"] != "ab896bd6b0f84589f7151df507db80f776aa08c40662fa50c191bf3a9cac102b":
        raise RuntimeError("R6_0_FRONTEND_SOURCE_ARCHIVE_DRIFT")
    if baseline["runtime_source"]["backend_untracked_files"] != ["scripts/wnd_taxonomy_tree_export.py"]:
        raise RuntimeError("R6_0_BACKEND_UNTRACKED_DISCLOSURE_DRIFT")
    if baseline["runtime_source"]["frontend_untracked_files"] != []:
        raise RuntimeError("R6_0_FRONTEND_UNTRACKED_DISCLOSURE_DRIFT")
    behavior = baseline["reference_behavior"]
    for required in ("takeaway", "delivery"):
        if required not in behavior["fulfillment"].lower():
            raise RuntimeError("R6_0_FULFILLMENT_REFERENCE_NOT_FROZEN=" + required)
    for required in ("semantic", "suppress"):
        if required not in behavior["kitchen"].lower():
            raise RuntimeError("R6_0_KITCHEN_REFERENCE_NOT_FROZEN=" + required)
    for required in ("explicit", "unlinked"):
        if required not in behavior["customer_ar"].lower():
            raise RuntimeError("R6_0_CUSTOMER_AR_REFERENCE_NOT_FROZEN=" + required)
    if baseline["production_control_counts"] != EXPECTED_COUNTS:
        raise RuntimeError("R6_0_COUNT_CONTRACT_DRIFT")

    if authority["production_write_authorized"] is not False:
        raise RuntimeError("R6_1_PRODUCTION_WRITE_AUTHORIZATION_LEAK")
    if authority["production_database"] != PRODUCTION_DATABASE:
        raise RuntimeError("R6_1_PRODUCTION_DATABASE_DRIFT")
    if set(authority["rehearsal_databases"]) != set(DISPOSABLE_DATABASES):
        raise RuntimeError("R6_1_DISPOSABLE_DATABASE_DRIFT")
    if authority["candidate_clone"]["accepted_head"] != TARGET_HEAD:
        raise RuntimeError("R6_1_TARGET_HEAD_DRIFT")
    comp = authority["composition_rehearsal"]
    if comp["existing_production_tenant_id"] != PRODUCTION_TENANT_ID:
        raise RuntimeError("R6_1_TENANT_ID_DRIFT")
    if comp["existing_production_branch_id"] != PRODUCTION_BRANCH_ID:
        raise RuntimeError("R6_1_BRANCH_ID_DRIFT")
    if comp["create_new_wnd_tenant"] is not False:
        raise RuntimeError("R6_1_NEW_TENANT_LEAK")

    if controls["count_controls"] != EXPECTED_COUNTS:
        raise RuntimeError("R6_1_CONTROL_COUNT_DRIFT")
    if controls["legacy_reference_schema_controls"] != baseline["legacy_reference_schema"]:
        raise RuntimeError("R6_1_REFERENCE_SCHEMA_CONTRACT_DRIFT")
    if authority.get("reference_release_tag") != REFERENCE_RELEASE_TAG:
        raise RuntimeError("R6_1_REFERENCE_RELEASE_TAG_DRIFT")
    if authority.get("production_baseline_generation") != baseline["baseline_generation"]:
        raise RuntimeError("R6_1_BASELINE_GENERATION_DRIFT")

    r5 = _load("contracts/restaurant/v1/r5_r6_readiness.json")
    if r5["status"] != "READY_WHEN_R5_SINGLE_GATE_PASS":
        raise RuntimeError("R6_1_R5_READINESS_DRIFT")
    if "write production xbos" not in r5["r6_must_not_do_without_explicit_cutover_authorization"]:
        raise RuntimeError("R6_1_PRODUCTION_GUARD_MISSING")

    m75 = _load("contracts/finance/v1/m75_finance_migration_support_acceptance_and_freeze.json")
    if m75["live_cutover_owner"] != "R6":
        raise RuntimeError("R6_1_M7_OWNER_DRIFT")
    if m75["cutover_authorized"] or m75["retirement_execution_allowed"]:
        raise RuntimeError("R6_1_M7_PREMATURE_CUTOVER")

    if list((ROOT / "alembic_neutral/versions").glob("r6_*")):
        raise RuntimeError("R6_1_SCHEMA_MIGRATION_FORBIDDEN")
    if list((ROOT / "alembic_neutral/sql").glob("r6_*")):
        raise RuntimeError("R6_1_SCHEMA_SQL_FORBIDDEN")

    release_artifacts = _verify_release_manifest()

    return {
        "status": "PASS",
        "source_checkpoint": SOURCE_CHECKPOINT,
        "source_branch": branch,
        "source_head": head,
        "production_database": PRODUCTION_DATABASE,
        "production_backend_head": PRODUCTION_BACKEND_HEAD[:7],
        "production_frontend_head": PRODUCTION_FRONTEND_HEAD[:7],
        "source_revision": SOURCE_REVISION,
        "target_head": TARGET_HEAD,
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "kitchen_semantic_delta": "PRESERVE",
        "reference_release_tag": REFERENCE_RELEASE_TAG,
        "reference_release_preservation": "PRESERVE",
        "rehearsal_databases": sorted(DISPOSABLE_DATABASES),
        "release_artifacts": release_artifacts,
    }


def _database_url():
    from database import DATABASE_URL
    return make_url(DATABASE_URL)


def _assert_disposable(name: str) -> None:
    if name not in DISPOSABLE_DATABASES:
        raise RuntimeError(f"R6_1_DATABASE_NOT_AUTHORIZED={name}")
    if name == PRODUCTION_DATABASE:
        raise RuntimeError("R6_1_PRODUCTION_DATABASE_WRITE_REFUSED")


def _admin_engine():
    url = _database_url().set(database="postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def _database_engine(name: str):
    _assert_disposable(name)
    return create_engine(_database_url().set(database=name), poolclass=NullPool)


def _reset_database(name: str) -> None:
    _assert_disposable(name)
    engine = _admin_engine()
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:name AND pid<>pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        engine.dispose()


def _locate_pg_tool(name: str) -> Path:
    found = shutil.which(name)
    if found:
        return Path(found)
    candidates = []
    for base in (Path(r"C:\Program Files\PostgreSQL"), Path(r"C:\Program Files (x86)\PostgreSQL")):
        if base.exists():
            for child in base.iterdir():
                candidate = child / "bin" / f"{name}.exe"
                if candidate.is_file():
                    try:
                        major = int(child.name.split(".", 1)[0])
                    except ValueError:
                        major = 0
                    candidates.append((major, candidate))
    if not candidates:
        raise RuntimeError(f"R6_1_POSTGRES_TOOL_NOT_FOUND={name}")
    return max(candidates, key=lambda row: row[0])[1]


def _find_backup() -> Path:
    explicit = os.environ.get("R6_0_WND_BACKUP")
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.home() / "Downloads" / SERVER_BACKUP_FILENAME)
    candidates.extend(sorted((Path.home() / "Downloads").glob("WND_R6_0_SERVER_PRODUCTION_SNAPSHOT_*.backup")))
    seen = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        if path.stat().st_size == SERVER_BACKUP_SIZE and _sha256(path).lower() == SERVER_BACKUP_SHA256:
            return path
    raise RuntimeError(
        "R6_1_SERVER_BACKUP_NOT_FOUND_OR_HASH_MISMATCH. "
        f"Copy the server snapshot with SHA256 {SERVER_BACKUP_SHA256} to Downloads "
        f"or set R6_0_WND_BACKUP to its local path."
    )


def _restore(name: str, backup: Path) -> None:
    _assert_disposable(name)
    _reset_database(name)
    pg_restore = _locate_pg_tool("pg_restore")
    url = _database_url()
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    cmdline = [
        str(pg_restore),
        "--host", url.host or "localhost",
        "--port", str(url.port or 5432),
        "--username", url.username or "postgres",
        "--dbname", name,
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        str(backup),
    ]
    cp = subprocess.run(cmdline, env=env, text=True, capture_output=True)
    if cp.returncode:
        raise RuntimeError(
            "R6_1_PG_RESTORE_FAILED database="
            + name
            + "\n"
            + cp.stdout
            + "\n"
            + cp.stderr
        )


def _current_head(engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names(schema="public"))
        missing = set(KEY_COUNTS) - tables
        if missing:
            raise RuntimeError("R6_1_SOURCE_TABLES_MISSING=" + ",".join(sorted(missing)))
        return {
            table: int(connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
            for table in sorted(KEY_COUNTS)
        }


def _control_totals(engine) -> dict[str, Any]:
    with engine.connect() as c:
        sales = c.execute(text(
            "SELECT COALESCE(SUM(total),0) total FROM sales"
        )).mappings().one()
        sale_items = c.execute(text(
            "SELECT COALESCE(SUM(line_total),0) total FROM sale_items"
        )).mappings().one()
        orders = c.execute(text(
            "SELECT COALESCE(SUM(total),0) total FROM orders"
        )).mappings().one()
        order_items = c.execute(text(
            "SELECT COALESCE(SUM(line_total),0) total FROM order_items"
        )).mappings().one()
        ar = c.execute(text(
            "SELECT COALESCE(SUM(original_amount),0) original_amount,"
            "COALESCE(SUM(paid_amount),0) paid_amount,"
            "COALESCE(SUM(balance_due),0) balance_due,"
            "COUNT(*) FILTER (WHERE original_amount-paid_amount-balance_due<>0) mismatches "
            "FROM accounts_receivable"
        )).mappings().one()
        orphan = c.execute(text(
            "SELECT COUNT(*) FROM accounts_receivable_repayments r "
            "LEFT JOIN accounts_receivable a ON a.id=r.ar_id WHERE a.id IS NULL"
        )).scalar_one()
        inv = c.execute(text(
            "WITH l AS (SELECT inventory_item_id,COALESCE(SUM(quantity_delta),0) movement_sum "
            "FROM inventory_movements GROUP BY inventory_item_id),"
            "x AS (SELECT i.id,i.quantity_on_hand,COALESCE(l.movement_sum,0) movement_sum,"
            "i.quantity_on_hand-COALESCE(l.movement_sum,0) delta "
            "FROM inventory_items i LEFT JOIN l ON l.inventory_item_id=i.id) "
            "SELECT COALESCE(SUM(quantity_on_hand),0) qoh,"
            "COALESCE(SUM(movement_sum),0) movement_sum,"
            "COUNT(*) FILTER(WHERE delta<>0) mismatch_count,"
            "COALESCE(SUM(delta),0) delta FROM x"
        )).mappings().one()
        future = c.execute(text(
            "SELECT COUNT(*) FROM inventory_movements "
            "WHERE created_at>CURRENT_TIMESTAMP+INTERVAL '5 minutes'"
        )).scalar_one()
        recon = c.execute(text(
            "SELECT COUNT(*) rows,COUNT(*) FILTER(WHERE status='closed') closed_rows FROM recon_sheets"
        )).mappings().one()
        return {
            "sales_total": sales["total"],
            "sale_item_total": sale_items["total"],
            "orders_total": orders["total"],
            "order_item_total": order_items["total"],
            "ar_original": ar["original_amount"],
            "ar_paid": ar["paid_amount"],
            "ar_balance": ar["balance_due"],
            "ar_mismatches": int(ar["mismatches"]),
            "ar_orphan_repayments": int(orphan),
            "inventory_qoh": inv["qoh"],
            "inventory_movement_sum": inv["movement_sum"],
            "inventory_mismatch_count": int(inv["mismatch_count"]),
            "inventory_delta": inv["delta"],
            "future_inventory_movements": int(future),
            "reconciliation_rows": int(recon["rows"]),
            "reconciliation_closed_rows": int(recon["closed_rows"]),
        }


def _legacy_reference_schema(engine) -> dict[str, Any]:
    with engine.connect() as c:
        tables = set(inspect(c).get_table_names(schema="public"))
        customers_exists = "customers" in tables
        if not customers_exists:
            raise RuntimeError("R6_1_REFERENCE_CUSTOMERS_TABLE_MISSING")

        order_columns = {
            row["name"]: row for row in inspect(c).get_columns("orders", schema="public")
        }
        ar_columns = {
            row["name"]: row for row in inspect(c).get_columns("accounts_receivable", schema="public")
        }
        if "fulfillment_mode" not in order_columns:
            raise RuntimeError("R6_1_REFERENCE_FULFILLMENT_COLUMN_MISSING")
        if "customer_id" not in ar_columns:
            raise RuntimeError("R6_1_REFERENCE_AR_CUSTOMER_ID_MISSING")

        fulfillment = c.execute(text("""
            SELECT is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='orders' AND column_name='fulfillment_mode'
        """)).mappings().one()

        index_names = {
            row["indexname"]
            for row in c.execute(text("""
                SELECT indexname FROM pg_indexes WHERE schemaname='public'
            """)).mappings()
        }
        constraints = {
            row["conname"]: row["definition"]
            for row in c.execute(text("""
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace='public'::regnamespace
            """)).mappings()
        }
        linked_ar = int(c.execute(text(
            "SELECT count(*) FROM accounts_receivable WHERE customer_id IS NOT NULL"
        )).scalar_one())
        customer_rows = int(c.execute(text("SELECT count(*) FROM customers")).scalar_one())

        required_indexes = {
            "customers_pkey",
            "ix_customers_context_name",
            "ux_customers_context_normalized_phone",
            "ix_accounts_receivable_customer_id",
            "ix_orders_tenant_branch_fulfillment_mode",
        }
        missing_indexes = required_indexes - index_names
        if missing_indexes:
            raise RuntimeError("R6_1_REFERENCE_INDEX_MISSING=" + ",".join(sorted(missing_indexes)))

        required_constraints = {
            "fk_accounts_receivable_customer_id",
            "ck_orders_fulfillment_mode",
        }
        missing_constraints = required_constraints - set(constraints)
        if missing_constraints:
            raise RuntimeError("R6_1_REFERENCE_CONSTRAINT_MISSING=" + ",".join(sorted(missing_constraints)))

        fulfillment_definition = constraints["ck_orders_fulfillment_mode"]
        for value in ("DINE_IN", "TAKEAWAY", "DELIVERY"):
            if value not in fulfillment_definition:
                raise RuntimeError("R6_1_REFERENCE_FULFILLMENT_VALUE_MISSING=" + value)

        result = {
            "customers_table": True,
            "customers_rows": customer_rows,
            "accounts_receivable_customer_id_column": True,
            "linked_ar_rows": linked_ar,
            "orders_fulfillment_mode_column": True,
            "fulfillment_nullable": fulfillment["is_nullable"] == "YES",
            "fulfillment_default": fulfillment["column_default"],
            "fulfillment_constraint": "ck_orders_fulfillment_mode",
            "fulfillment_index": "ix_orders_tenant_branch_fulfillment_mode",
            "customer_fk": "fk_accounts_receivable_customer_id",
            "customer_index": "ix_accounts_receivable_customer_id",
        }
        expected = {
            "customers_table": True,
            "customers_rows": 0,
            "accounts_receivable_customer_id_column": True,
            "linked_ar_rows": 0,
            "orders_fulfillment_mode_column": True,
            "fulfillment_nullable": True,
            "fulfillment_default": "'DINE_IN'::character varying",
            "fulfillment_constraint": "ck_orders_fulfillment_mode",
            "fulfillment_index": "ix_orders_tenant_branch_fulfillment_mode",
            "customer_fk": "fk_accounts_receivable_customer_id",
            "customer_index": "ix_accounts_receivable_customer_id",
        }
        if result != expected:
            raise RuntimeError(
                "R6_1_REFERENCE_SCHEMA_DRIFT=" + json.dumps(
                    {"expected": expected, "actual": result}, sort_keys=True, default=str
                )
            )
        return result


def _assert_source_controls(engine, label: str) -> dict[str, Any]:
    head = _current_head(engine)
    if head != SOURCE_REVISION:
        raise RuntimeError(f"R6_1_{label}_HEAD={head}")
    counts = _counts(engine)
    if counts != dict(sorted(KEY_COUNTS.items())):
        diff = {
            key: {"expected": KEY_COUNTS[key], "actual": counts.get(key)}
            for key in sorted(KEY_COUNTS)
            if counts.get(key) != KEY_COUNTS[key]
        }
        raise RuntimeError(f"R6_1_{label}_COUNT_MISMATCH={json.dumps(diff,sort_keys=True)}")
    totals = _control_totals(engine)
    expected = {
        "sales_total": EXPECTED_TOTALS["sales"],
        "sale_item_total": EXPECTED_TOTALS["sales"],
        "orders_total": EXPECTED_TOTALS["orders"],
        "order_item_total": EXPECTED_TOTALS["orders"],
        "ar_original": EXPECTED_TOTALS["ar_original"],
        "ar_paid": EXPECTED_TOTALS["ar_paid"],
        "ar_balance": EXPECTED_TOTALS["ar_balance"],
        "ar_mismatches": 0,
        "ar_orphan_repayments": 0,
        "inventory_qoh": EXPECTED_TOTALS["inventory_qoh"],
        "inventory_movement_sum": EXPECTED_TOTALS["inventory_movement_sum"],
        "inventory_mismatch_count": EXPECTED_HISTORICAL_INVENTORY_MISMATCHES,
        "inventory_delta": EXPECTED_HISTORICAL_INVENTORY_DELTA,
        "future_inventory_movements": 0,
        "reconciliation_rows": 791,
        "reconciliation_closed_rows": 791,
    }
    for key, value in expected.items():
        if totals[key] != value:
            raise RuntimeError(f"R6_1_{label}_{key.upper()} expected={value} actual={totals[key]}")
    reference_schema = _legacy_reference_schema(engine)
    return {
        "head": head,
        "counts": counts,
        "totals": {k: str(v) for k, v in totals.items()},
        "legacy_reference_schema": reference_schema,
    }


@contextmanager
def _database_environment(name: str):
    _assert_disposable(name)
    url = _database_url().set(database=name).render_as_string(hide_password=False)
    previous_database = os.environ.get("DATABASE_URL")
    previous_migration = os.environ.get("MIGRATION_DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    os.environ["MIGRATION_DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous_database is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database
        if previous_migration is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous_migration


def _alembic_config(name: str) -> Config:
    _assert_disposable(name)
    cfg = Config(str(ROOT / "alembic.ini"))
    url = _database_url().set(database=name).render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _adopt_candidate() -> None:
    engine = _database_engine(CANDIDATE_DATABASE)
    try:
        if _current_head(engine) != SOURCE_REVISION:
            raise RuntimeError("R6_1_CANDIDATE_NOT_AT_RAW_SOURCE")
    finally:
        engine.dispose()
    with _database_environment(CANDIDATE_DATABASE):
        cfg = _alembic_config(CANDIDATE_DATABASE)
        command.stamp(cfg, CANONICAL_SOURCE_STAMP, purge=True)
        command.upgrade(cfg, TARGET_HEAD)


def _register_and_compose_candidate() -> dict[str, Any]:
    from core.platform.operating_context import OperatingContextAuthority
    from core.platform.operating_context.sql_repository import SQLOperatingContextRepository
    from pack_platform import PackAuthority
    from pack_platform.pk456_service import PK456Authority
    from pack_platform.pk456_sql_repository import SQLPK456Repository
    from pack_platform.sql_repository import SQLPackRepository
    from restaurant.r4 import build_certification_command, build_registration_command
    from restaurant.r5 import (
        activate_restaurant_pack,
        apply_wnd_operating_context,
        plan_and_apply_wnd_template,
        register_templates,
    )

    engine = _database_engine(CANDIDATE_DATABASE)
    try:
        with Session(engine) as session:
            tenant_count_before = int(session.execute(text("SELECT count(*) FROM tenants")).scalar_one())
            if tenant_count_before != 3:
                raise RuntimeError(f"R6_1_TENANT_COUNT_BEFORE={tenant_count_before}")
            if session.execute(text("SELECT 1 FROM tenants WHERE id=:id"), {"id": PRODUCTION_TENANT_ID}).one_or_none() is None:
                raise RuntimeError("R6_1_PRODUCTION_TENANT_2_MISSING")
            if session.execute(
                text("SELECT 1 FROM branches WHERE id=:b AND tenant_id=:t"),
                {"b": PRODUCTION_BRANCH_ID, "t": PRODUCTION_TENANT_ID},
            ).one_or_none() is None:
                raise RuntimeError("R6_1_PRODUCTION_BRANCH_1_MISSING")

            mapping = session.execute(
                text(
                    "SELECT organization_unit_id,location_id FROM legacy_branch_structural_mappings "
                    "WHERE tenant_id=:t AND branch_id=:b"
                ),
                {"t": PRODUCTION_TENANT_ID, "b": PRODUCTION_BRANCH_ID},
            ).mappings().one_or_none()
            if mapping is None:
                raise RuntimeError("R6_1_PC1_LEGACY_BRANCH_MAPPING_MISSING")

            pack_authority = PackAuthority(SQLPackRepository(session))
            pk456 = PK456Authority(SQLPK456Repository(session))
            operating = OperatingContextAuthority(SQLOperatingContextRepository(session))

            pack_authority.register(build_registration_command())
            pk456.certify(build_certification_command(_r4_evidence_hashes()))
            register_templates(pk456)

            active = activate_restaurant_pack(pack_authority, PRODUCTION_TENANT_ID)
            if active.status.value != "active":
                raise RuntimeError("R6_1_RESTAURANT_PACK_NOT_ACTIVE")

            plan, state = plan_and_apply_wnd_template(pk456, PRODUCTION_TENANT_ID)
            if plan.conflicts:
                raise RuntimeError("R6_1_TEMPLATE_CONFLICT=" + ",".join(plan.conflicts))
            calendar = apply_wnd_operating_context(
                operating,
                PRODUCTION_TENANT_ID,
                state.effective_configuration,
            )
            session.commit()

        with engine.connect() as connection:
            tenant_count_after = int(connection.execute(text("SELECT count(*) FROM tenants")).scalar_one())
            if tenant_count_after != tenant_count_before:
                raise RuntimeError("R6_1_TENANT_COUNT_CHANGED")
            proof = int(connection.execute(
                text("SELECT count(*) FROM tenants WHERE code='wnd-r5-proof'")
            ).scalar_one())
            if proof:
                raise RuntimeError("R6_1_PROOF_TENANT_CREATED")

            install = connection.execute(
                text(
                    "SELECT i.lifecycle_status AS status,v.pack_version AS version "
                    "FROM pk_tenant_pack_installations i "
                    "JOIN pk_packs p ON p.id=i.pack_id "
                    "JOIN pk_pack_versions v ON v.id=i.pack_version_id AND v.pack_id=i.pack_id "
                    "WHERE i.tenant_id=:t AND p.pack_code='industry.restaurant'"
                ),
                {"t": PRODUCTION_TENANT_ID},
            ).mappings().one()
            binding = connection.execute(
                text(
                    "SELECT t.template_code,v.template_version AS version "
                    "FROM pk_tenant_template_bindings b "
                    "JOIN pk_templates t ON t.id=b.template_id "
                    "JOIN pk_template_versions v ON v.id=b.template_version_id AND v.template_id=b.template_id "
                    "WHERE b.tenant_id=:t AND t.template_code='restaurant.counter_service'"
                ),
                {"t": PRODUCTION_TENANT_ID},
            ).mappings().one()
            pc4_values = int(connection.execute(
                text(
                    "SELECT count(*) FROM configuration_values "
                    "WHERE tenant_id=:t"
                ),
                {"t": PRODUCTION_TENANT_ID},
            ).scalar_one())

        return {
            "tenant_id": PRODUCTION_TENANT_ID,
            "branch_id": PRODUCTION_BRANCH_ID,
            "organization_unit_id": mapping["organization_unit_id"],
            "location_id": mapping["location_id"],
            "pack_status": install["status"],
            "pack_version": install["version"],
            "template_code": binding["template_code"],
            "template_version": binding["version"],
            "pc4_value_count": pc4_values,
            "business_calendar": calendar.calendar_code,
            "tenant_count_before": tenant_count_before,
            "tenant_count_after": tenant_count_after,
        }
    finally:
        engine.dispose()


def _verify_post_adoption(source_before: dict[str, Any]) -> dict[str, Any]:
    source_engine = _database_engine(SOURCE_DATABASE)
    candidate_engine = _database_engine(CANDIDATE_DATABASE)
    try:
        if _current_head(source_engine) != SOURCE_REVISION:
            raise RuntimeError("R6_1_SOURCE_CLONE_MUTATED")
        if _current_head(candidate_engine) != TARGET_HEAD:
            raise RuntimeError("R6_1_CANDIDATE_TARGET_HEAD_MISMATCH")

        source_counts = _counts(source_engine)
        candidate_counts = _counts(candidate_engine)
        if candidate_counts != source_counts:
            raise RuntimeError("R6_1_LEGACY_ROW_COUNTS_CHANGED")

        source_totals = _control_totals(source_engine)
        candidate_totals = _control_totals(candidate_engine)
        if candidate_totals != source_totals:
            raise RuntimeError("R6_1_LEGACY_CONTROL_TOTALS_CHANGED")

        source_reference_schema = _legacy_reference_schema(source_engine)
        candidate_reference_schema = _legacy_reference_schema(candidate_engine)
        if candidate_reference_schema != source_reference_schema:
            raise RuntimeError("R6_1_LEGACY_REFERENCE_SCHEMA_CHANGED")

        candidate_tables = set(inspect(candidate_engine).get_table_names(schema="public"))
        required = {
            "financial_events",
            "journal_entries",
            "organization_units",
            "legal_entities",
            "locations",
            "legacy_branch_structural_mappings",
            "pk_packs",
            "pk_tenant_pack_installations",
            "pk_templates",
            "configuration_definitions",
            "configuration_values",
            "r1_restaurant_orders",
            "r2_restaurant_station_profiles",
        }
        missing = required - candidate_tables
        if missing:
            raise RuntimeError("R6_1_NEUTRAL_TABLES_MISSING=" + ",".join(sorted(missing)))

        return {
            "source_head": _current_head(source_engine),
            "candidate_head": _current_head(candidate_engine),
            "legacy_counts_preserved": True,
            "legacy_controls_preserved": True,
            "legacy_reference_schema_preserved": True,
            "fulfillment_reference_preserved": True,
            "customer_ar_identity_reference_preserved": True,
            "historical_inventory_mismatch_preserved": (
                candidate_totals["inventory_mismatch_count"] == EXPECTED_HISTORICAL_INVENTORY_MISMATCHES
                and candidate_totals["inventory_delta"] == EXPECTED_HISTORICAL_INVENTORY_DELTA
            ),
            "neutral_required_tables": sorted(required),
        }
    finally:
        source_engine.dispose()
        candidate_engine.dispose()


def _run_acceptance() -> dict[str, Any]:
    backup = _find_backup()

    _restore(SOURCE_DATABASE, backup)
    source_engine = _database_engine(SOURCE_DATABASE)
    try:
        source_before = _assert_source_controls(source_engine, "SOURCE_CLONE")
    finally:
        source_engine.dispose()

    _restore(CANDIDATE_DATABASE, backup)
    candidate_engine = _database_engine(CANDIDATE_DATABASE)
    try:
        _assert_source_controls(candidate_engine, "CANDIDATE_RAW")
    finally:
        candidate_engine.dispose()

    _adopt_candidate()
    adopted = _verify_post_adoption(source_before)
    composition = _register_and_compose_candidate()
    final = _verify_post_adoption(source_before)

    result = {
        "status": "PASS",
        "backup": str(backup),
        "backup_sha256": _sha256(backup),
        "source_clone": source_before,
        "adoption": adopted,
        "composition": composition,
        "final": final,
        "production_database_touched": False,
        "production_writes": "NONE",
        "writer_routing": "UNCHANGED",
        "kitchen_bon_preservation": KITCHEN_BON_PRESERVATION,
        "reference_release_preservation": REFERENCE_RELEASE_PRESERVATION,
        "reference_release_tag": REFERENCE_RELEASE_TAG,
    }

    output = Path.home() / "Downloads" / "XBOS_R6_1_WND_REHEARSAL_RESULT.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    result["result_file"] = str(output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", action="store_true")
    args = parser.parse_args()

    static = _static_verify()
    print(json.dumps(static, indent=2, sort_keys=True))
    print("R6_1_VERIFY=PASS")

    if args.acceptance:
        result = _run_acceptance()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        print("R6_1_POSTGRES_REHEARSAL=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
