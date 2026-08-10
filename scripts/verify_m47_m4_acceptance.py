"""Aggregate read-only development gate and M4.0-M4.6 release rehearsal."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.m2_acceptance import validate_release_manifest as validate_m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as validate_m3_manifest
from core.domain.finance.m4_acceptance import EXPECTED_HEAD, validate_release_manifest
from core.integrations.xafpay.adapter import XafPayAdapter
from core.integrations.xafpay.contract import XafPayInitiationRequest
from core.persistence.m40_payment_foundation import TEST_DATABASE_NAME as M40_DATABASE
from core.persistence.m41_payment_commands import TEST_DATABASE_NAME as M41_DATABASE
from core.persistence.m42_payment_attempts import TEST_DATABASE_NAME as M42_DATABASE
from core.persistence.m43_payment_settlements import TEST_DATABASE_NAME as M43_DATABASE
from core.persistence.m44_payment_patterns import TEST_DATABASE_NAME as M44_DATABASE
from core.persistence.m46_provider_financials import TEST_DATABASE_NAME as M46_DATABASE
from database import engine as application_engine
from scripts import (
    verify_m40_payment_foundation as m40,
    verify_m41_payment_commands as m41,
    verify_m42_payment_attempts as m42,
    verify_m43_payment_settlements as m43,
    verify_m44_payment_patterns as m44,
    verify_m45_xafpay_orchestration as m45,
    verify_m46_provider_financials as m46,
)

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
M45_DATABASE = "xbos_track_b_m45_xafpay_test"
DATABASES = (
    ("m40", M40_DATABASE),
    ("m41", M41_DATABASE),
    ("m42", M42_DATABASE),
    ("m43", M43_DATABASE),
    ("m44", M44_DATABASE),
    ("m45", M45_DATABASE),
    ("m46", M46_DATABASE),
)
EMPTY_TABLES = (
    "canonical_payment_requests",
    "canonical_payment_intents",
    "canonical_payment_tenders",
    "payment_tender_transitions",
    "canonical_payment_attempts",
    "canonical_payment_attempt_transitions",
    "provider_callback_events",
    "payment_settlements",
    "payment_settlement_transitions",
    "payment_settlement_reversals",
    "provider_settlement_components",
    "payment_provider_accounts",
    "idempotency_records",
    "kernel_source_records",
    "financial_events",
    "outbox_messages",
    "journal_entries",
    "journal_lines",
    "financial_obligations",
    "financial_obligation_lines",
    "value_sources",
    "payment_allocations",
    "allocation_reversals",
)


def _url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _engine(database_name, isolation_level=None):
    return create_engine(_url().set(database=database_name), isolation_level=isolation_level, pool_pre_ping=True)


def _exists(database_name):
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database_name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _create(database_name, *, clone):
    if database_name not in {name for _, name in DATABASES}:
        raise RuntimeError(f"unsafe disposable database target={database_name}")
    if _exists(database_name):
        raise RuntimeError(f"disposable database already exists={database_name}")
    application_engine.dispose()
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            template = f' TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"' if clone else ""
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"{template}')
    finally:
        engine.dispose()


def _drop(database_name):
    if database_name not in {name for _, name in DATABASES}:
        raise RuntimeError(f"unsafe disposable database target={database_name}")
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": database_name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        engine.dispose()


@contextmanager
def _migration_database(database_name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=database_name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _migrate(database_name, revision, *, downgrade=False):
    with _migration_database(database_name):
        config = Config(str(ROOT / "alembic.ini"))
        (alembic_command.downgrade if downgrade else alembic_command.upgrade)(config, revision)


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    m2 = validate_m2_manifest(ROOT)
    m3 = validate_m3_manifest(ROOT)
    m4 = validate_release_manifest(ROOT)
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_HEAD:
            raise RuntimeError(f"expected revision={EXPECTED_HEAD}; actual={revision}")
        catalog = connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one()
        if catalog != 20:
            raise RuntimeError(f"expected canonical catalog=20; actual={catalog}")
        tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        missing = set(EMPTY_TABLES) - tables
        if missing:
            raise RuntimeError(f"expected release tables missing={sorted(missing)}")
        populated = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in EMPTY_TABLES
        }
        populated = {table: count for table, count in populated.items() if count}
        if populated:
            raise RuntimeError(f"development release tables are not empty={populated}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print(f"financial_event_type_versions={catalog}")
    print(f"release_manifests=m2:{m2.checked_components},m3:{m3.checked_components},m4:{m4.checked_components}")
    print("m47_m4_development_acceptance=PASS canonical_head=m46_provider_financials_015 manifest=PASS development_empty=PASS")


def _verify_source_checkpoint():
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    if branch != "track-b/m4-payments-settlement-orchestration":
        raise RuntimeError(f"unexpected branch={branch}")
    if commit != "ef8b097":
        raise RuntimeError(f"unexpected starting commit={commit}")
    tracked_changes = tuple(
        line for line in subprocess.check_output(
            ["git", "diff", "--name-only"], cwd=ROOT, text=True
        ).splitlines() if line
    )
    allowed_hardening = (
        "scripts/verify_m43_payment_settlements.py",
        "scripts/verify_m44_payment_patterns.py",
    )
    if tracked_changes not in ((), allowed_hardening):
        raise RuntimeError(f"unexpected tracked worktree changes before M4.7={tracked_changes}")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode:
        raise RuntimeError("staged changes exist before M4.7")


def _status():
    clean = True
    for phase, database_name in DATABASES:
        exists = _exists(database_name)
        print(f"phase={phase} database={database_name} exists={str(exists).lower()}")
        clean = clean and not exists
    return clean


def _run_m40():
    _create(M40_DATABASE, clone=False)
    engine = None
    try:
        _migrate(M40_DATABASE, "m40_payment_foundation_011")
        engine = _engine(M40_DATABASE)
        with engine.connect() as connection:
            m40._verify_foundation(connection)
        engine.dispose(); engine = None
        _migrate(M40_DATABASE, "m34_obligation_aging_010", downgrade=True)
        _migrate(M40_DATABASE, "m40_payment_foundation_011")
        engine = _engine(M40_DATABASE)
        with engine.connect() as connection:
            m40._verify_foundation(connection)
        engine.dispose(); engine = None
        _drop(M40_DATABASE)
    except Exception:
        if engine is not None:
            engine.dispose()
        raise


def _run_current_head_capability(database_name, exercise):
    _create(database_name, clone=True)
    engine = None
    try:
        engine = _engine(database_name)
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != EXPECTED_HEAD:
                raise RuntimeError(f"disposable clone revision differs={database_name}:{revision}")
        exercise(engine)
        engine.dispose(); engine = None
        _drop(database_name)
    except Exception:
        if engine is not None:
            engine.dispose()
        raise


class _OutageTransport:
    def post(self, *, path, headers, body):
        raise TimeoutError("simulated provider outage")


def _verify_provider_outage():
    request = XafPayInitiationRequest(
        UUID("47000000-0000-0000-0000-000000000001"),
        Decimal("100"),
        "XAF",
        "mtn_momo",
        "+237670000000",
        "https://merchant.test/return",
        "https://merchant.test/cancel",
        "m47-provider-outage",
    )
    try:
        XafPayAdapter.initiate(request, api_key="not-persisted", transport=_OutageTransport())
    except TimeoutError as exc:
        if "simulated provider outage" not in str(exc):
            raise
    else:
        raise RuntimeError("provider outage fabricated a successful initiation")


def _create_and_verify():
    _verify_source_checkpoint()
    _verify_development()
    if not _status():
        raise RuntimeError("one or more M4 disposable databases already exist")
    active = None
    try:
        active = M40_DATABASE; _run_m40(); active = None
        for database_name, exercise in (
            (M41_DATABASE, m41._exercise),
            (M42_DATABASE, m42._exercise),
            (M43_DATABASE, m43._exercise),
            (M44_DATABASE, m44._exercise),
            (M45_DATABASE, m45._exercise),
            (M46_DATABASE, m46._exercise),
        ):
            active = database_name
            _run_current_head_capability(database_name, exercise)
            active = None
        _verify_provider_outage()
        _verify_development()
        if not _status():
            raise RuntimeError("one or more M4 disposable databases were retained")
        print("m47_m4_acceptance=PASS canonical_head=m46_provider_financials_015 manifest=PASS development_empty=PASS m40=PASS m41=PASS m42=PASS m43=PASS m44=PASS m45=PASS m46=PASS callback_replay=PASS callback_conflict=PASS provider_outage=PASS mixed_tender=PASS offline_cash=PASS security=PASS tenant_isolation=PASS disposable_databases_dropped=true")
    except Exception:
        print(f"M4.7 acceptance failed; inspect retained disposable database={active or 'status-output'}")
        raise


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("verify")
    commands.add_parser("create-and-verify")
    drop = commands.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()
    if args.command == "status":
        return 0 if _status() else 1
    if args.command == "verify":
        _verify_development()
    elif args.command == "create-and-verify":
        _create_and_verify()
    else:
        allowed = {name for _, name in DATABASES}
        if args.confirm_database_name not in allowed:
            raise RuntimeError("exact named M4 disposable confirmation required")
        _drop(args.confirm_database_name)
        print(f"dropped={args.confirm_database_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
