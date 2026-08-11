"""Disposable PostgreSQL verification for M8.0 global hardening invariants."""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.event_contract import (
    FinancialEventIdempotencyConflict,
    FinancialEventValidationError,
)
from core.domain.finance.global_invariant_contract import (
    deterministic_property_cases,
    validate_property_corpus,
)
from core.domain.finance.global_invariant_service import validate_kernel_concurrency_guards
from core.domain.finance.m2_acceptance import validate_release_manifest as m2_manifest
from core.domain.finance.m3_acceptance import validate_release_manifest as m3_manifest
from core.domain.finance.m5_acceptance import validate_release_manifest as m5_manifest
from core.domain.finance.m6_acceptance import (
    EXPECTED_HEAD,
    validate_frozen_m4_manifest,
    validate_release_manifest as m6_manifest,
)
from core.domain.finance.m7_acceptance import validate_release_manifest as m7_manifest
from core.domain.finance.transactional_event_engine import TransactionalCanonicalFinancialEventEngine
from database import engine as application_engine
from scripts.verify_m21_canonical_event_engine import (
    SOURCE_OTHER_TENANT,
    _event_command,
    _install_fixtures,
)

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m80_invariants_test"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
WORKERS = 8
EMPTY_TABLES = (
    "idempotency_records", "kernel_source_records", "financial_events", "outbox_messages",
    "journal_entries", "journal_lines", "financial_obligations", "value_sources",
    "payment_allocations", "allocation_reversals", "payment_settlements",
    "operational_account_balance_anchors", "operational_account_balance_observations",
    "operational_transfers", "reconciliation_windows", "reconciliation_controls",
)


def _base_url():
    url = make_url(application_engine.url)
    if url.host not in LOCAL_HOSTS:
        raise RuntimeError(f"refusing non-local PostgreSQL host={url.host!r}")
    return url


def _engine(name: str, isolation_level: str | None = None):
    return create_engine(_base_url().set(database=name), isolation_level=isolation_level)


def _exists(name: str) -> bool:
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar())
    finally:
        selected.dispose()


def _create_clone() -> None:
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.exec_driver_sql(
                f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"'
            )
    finally:
        selected.dispose()


def _drop(name: str) -> None:
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    selected = _engine("postgres", "AUTOCOMMIT")
    try:
        with selected.connect() as connection:
            connection.execute(text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=:name AND pid<>pg_backend_pid()"
            ), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        selected.dispose()


def _expect(code: str, action) -> None:
    try:
        action()
    except Exception as exc:
        if getattr(exc, "code", None) != code:
            raise RuntimeError(f"expected={code}; actual={getattr(exc, 'code', type(exc).__name__)}") from exc
    else:
        raise RuntimeError(f"expected error not raised={code}")


def _development() -> None:
    if _base_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"development database must be={DEVELOPMENT_DATABASE_NAME}")
    releases = (
        m2_manifest(ROOT).checked_components,
        m3_manifest(ROOT).checked_components,
        validate_frozen_m4_manifest(ROOT),
        m5_manifest(ROOT),
        m6_manifest(ROOT).checked_components,
        m7_manifest(ROOT).checked_components,
    )
    validate_kernel_concurrency_guards(ROOT)
    with application_engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != DEVELOPMENT_DATABASE_NAME or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
        tables = set(connection.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )).scalars())
        for table in EMPTY_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development financial table not empty={table}")
    cases = deterministic_property_cases(seed=8000, count=512)
    if validate_property_corpus(cases) != 512:
        raise RuntimeError("property corpus count differs")
    print(f"database={database}")
    print(f"revision={revision}")
    print(
        "release_manifests="
        f"m2:{releases[0]},m3:{releases[1]},m4:{releases[2]},m5:{releases[3]},m6:{releases[4]},m7:{releases[5]}"
    )
    print("m80_global_invariants_development=PASS manifests=PASS lineage=PASS development_empty=PASS property_cases=512")


def _worker(selected, barrier: Barrier, command):
    barrier.wait(timeout=30)
    with Session(selected, expire_on_commit=False) as session:
        with session.begin():
            result = TransactionalCanonicalFinancialEventEngine.emit(session, command)
    return str(result.event.public_id), str(result.outbox_message.public_id), result.replayed


def _exercise(selected) -> None:
    _install_fixtures(selected)
    command = _event_command(
        public_id=UUID("80000000-0000-0000-0000-000000000001"),
        idempotency_key="m80:concurrency:1",
        correlation_id=UUID("80000000-0000-0000-0000-000000000099"),
        metadata={"source": "m80_concurrency_probe"},
        actor_service="m80-verifier",
    )
    barrier = Barrier(WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = tuple(pool.submit(_worker, selected, barrier, command) for _ in range(WORKERS))
        results = tuple(future.result(timeout=60) for future in futures)
    if sum(not row[2] for row in results) != 1 or sum(row[2] for row in results) != WORKERS - 1:
        raise RuntimeError(f"concurrent replay cardinality differs={results!r}")
    if len({row[0] for row in results}) != 1 or len({row[1] for row in results}) != 1:
        raise RuntimeError("concurrent replay changed event or outbox identity")

    with Session(selected) as session:
        _expect("idempotency_conflict", lambda: (
            session.begin(),
            TransactionalCanonicalFinancialEventEngine.emit(session, replace(command, amount=Decimal("1001"))),
        ))
        session.rollback()

    rollback = replace(
        command,
        public_id=UUID("80000000-0000-0000-0000-000000000002"),
        idempotency_key="m80:rollback:1",
    )
    with Session(selected) as session:
        transaction = session.begin()
        TransactionalCanonicalFinancialEventEngine.emit(session, rollback)
        transaction.rollback()

    cross_tenant = replace(
        command,
        public_id=UUID("80000000-0000-0000-0000-000000000003"),
        idempotency_key="m80:cross-tenant:1",
        source_record_id=SOURCE_OTHER_TENANT,
    )
    with Session(selected) as session:
        _expect("source_record_not_found", lambda: (
            session.begin(),
            TransactionalCanonicalFinancialEventEngine.emit(session, cross_tenant),
        ))
        session.rollback()

    with selected.connect() as connection:
        counts = tuple(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                       for table in ("idempotency_records", "financial_events", "outbox_messages"))
        if counts != (1, 1, 1):
            raise RuntimeError(f"unexpected atomic counts={counts}")
        residue = connection.execute(text(
            "SELECT count(*) FROM idempotency_records WHERE idempotency_key IN "
            "('m80:rollback:1','m80:cross-tenant:1')"
        )).scalar_one()
        if residue:
            raise RuntimeError("failed or rolled-back command left idempotency residue")
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != EXPECTED_HEAD:
            raise RuntimeError(f"disposable revision changed={revision}")


def _run() -> None:
    _development()
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    _create_clone()
    selected = None
    try:
        selected = _engine(TEST_DATABASE_NAME)
        _exercise(selected)
        selected.dispose()
        selected = None
        _drop(TEST_DATABASE_NAME)
        _development()
    except Exception:
        if selected is not None:
            selected.dispose()
        print(f"M8.0 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print(
        f"m80_global_financial_invariants=PASS database={TEST_DATABASE_NAME} "
        "global_invariants=PASS property_cases=512 concurrency=PASS workers=8 "
        "single_effect=PASS replay=PASS conflict=PASS rollback=PASS tenant_scope=PASS "
        "atomic_event_outbox=PASS schema_neutral=PASS migration=NONE dropped=true"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "create-and-verify", "drop"))
    parser.add_argument("--confirm-database-name")
    args = parser.parse_args()
    if args.command == "verify":
        _development()
    elif args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    else:
        _run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
