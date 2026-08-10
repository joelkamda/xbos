"""Read-only development gate and disposable M6.0 operational-balance rehearsal."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.operational_balance_contract import (
    CreateOperationalAccountCommand,
    OperationalBalanceIdempotencyConflict,
    OperationalBalanceQuery,
    OperationalBalanceValidationError,
    RecordActualBalanceCommand,
    RecordBalanceAnchorCommand,
)
from core.domain.finance.operational_balance_engine import TransactionalOperationalBalanceEngine
from core.domain.finance.operational_balance_service import OperationalBalanceService
from core.persistence.m60_operational_balance_authority import (
    M60_TABLES,
    PARENT_REVISION,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
)
from database import engine as application_engine

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
BASE = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
BUSINESS_DATE = date(2026, 8, 10)
CORRELATION = UUID("60000000-0000-0000-0000-000000000099")
FINANCIAL_EMPTY_TABLES = (
    "financial_dimension_types", "financial_dimension_values", "posting_dimension_policies",
    "idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines",
    "financial_obligations", "value_sources", "payment_allocations", "allocation_reversals",
    "canonical_payment_intents", "canonical_payment_attempts", "payment_settlements",
    "provider_settlement_components",
)


def _url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _engine(name, isolation_level=None):
    return create_engine(_url().set(database=name), isolation_level=isolation_level, pool_pre_ping=True)


def _exists(name):
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _create_clone():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally:
        engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"unsafe disposable database target={name}")
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        engine.dispose()


@contextmanager
def _migration_database(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _migrate(name, revision, *, downgrade=False):
    with _migration_database(name):
        config = Config(str(ROOT / "alembic.ini"))
        (alembic_command.downgrade if downgrade else alembic_command.upgrade)(config, revision)


def _revision(connection):
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _verify_development():
    if _url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = _revision(connection)
        if revision not in {PARENT_REVISION, TARGET_REVISION}:
            raise RuntimeError(f"unexpected development revision={revision}")
        tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")).scalars())
        for table in M60_TABLES:
            if revision == TARGET_REVISION and table not in tables:
                raise RuntimeError(f"M6.0 table missing={table}")
            if revision == PARENT_REVISION and table in tables:
                raise RuntimeError(f"M6.0 table exists at parent revision={table}")
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development M6.0 table is not empty={table}")
        for table in FINANCIAL_EMPTY_TABLES:
            if table in tables and connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one():
                raise RuntimeError(f"development financial table is not empty={table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m60_operational_balance_development=PASS")
    return revision


def _status():
    exists = _exists(TEST_DATABASE_NAME)
    print(f"database={TEST_DATABASE_NAME} exists={str(exists).lower()}")
    return not exists


def _seed_scope(session):
    tenant = int(session.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar_one())
    session.execute(text("""INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active)
      VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"""))
    organization = session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:tenant ORDER BY id LIMIT 1"), {"tenant": tenant}).scalar_one_or_none()
    if organization is None:
        organization = session.execute(text("""INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active)
          VALUES(:tenant,'branch','m60-verifier','M6.0 Verifier','Africa/Douala',true) RETURNING id"""), {"tenant": tenant}).scalar_one()
    other_organization = session.execute(text("SELECT id FROM organization_units WHERE tenant_id=:tenant AND id<>:org ORDER BY id LIMIT 1"), {"tenant": tenant, "org": organization}).scalar_one_or_none()
    if other_organization is None:
        other_organization = session.execute(text("""INSERT INTO organization_units(tenant_id,unit_type,code,name,timezone_name,active)
          VALUES(:tenant,'branch','m60-other','M6.0 Other','Africa/Douala',true) RETURNING id"""), {"tenant": tenant}).scalar_one()
    return tenant, int(organization), int(other_organization)


def _account(tenant, organization, *, public_id=UUID("60000000-0000-0000-0000-000000000001"), code="m60-drawer", aggregation="leaf", parent=None, key="drawer"):
    return CreateOperationalAccountCommand(
        public_id=public_id, tenant_id=tenant, organization_unit_id=organization,
        parent_account_public_id=parent, account_class="treasury", account_type="cash",
        code=code, display_name=code.replace("-", " ").title(), currency_code="XAF",
        aggregation_role=aggregation, opened_at=BASE, correlation_id=CORRELATION,
        actor_service="m60.verifier", source_component="m60.verifier", source_record_id=key,
        idempotency_scope="m60.account", idempotency_key=key, metadata={"verified": True},
    )


def _anchor(tenant, organization, account_public, *, key="anchor", balance="100"):
    return RecordBalanceAnchorCommand(
        public_id=UUID("60000000-0000-0000-0001-000000000001"), tenant_id=tenant,
        organization_unit_id=organization, operational_account_public_id=account_public,
        anchor_balance=balance, currency_code="XAF", anchor_at=BASE, provenance="opening_import",
        evidence_payload={"opening_report": "m60-approved"}, occurred_at=BASE,
        business_date=BUSINESS_DATE, calendar_policy_version=1, correlation_id=CORRELATION,
        actor_service="m60.verifier", source_component="m60.verifier", source_record_id=key,
        idempotency_scope="m60.anchor", idempotency_key=key,
    )


def _actual(tenant, organization, account_public, *, public_id, key, balance, minute, provenance="operator_counted"):
    observed = BASE + timedelta(minutes=minute)
    return RecordActualBalanceCommand(
        public_id=public_id, tenant_id=tenant, organization_unit_id=organization,
        operational_account_public_id=account_public, actual_balance=balance, currency_code="XAF",
        observed_at=observed, provenance=provenance, evidence_payload={"evidence": key},
        occurred_at=observed, business_date=BUSINESS_DATE, calendar_policy_version=1,
        correlation_id=CORRELATION, actor_service="m60.verifier", source_component="m60.verifier",
        source_record_id=key, idempotency_scope="m60.actual", idempotency_key=key,
    )


def _insert_movements(session, tenant, organization, account_id):
    for index, (event_type, role, amount, source, target, minute) in enumerate((
        ("PAYMENT_SETTLED", "settlement_in", "40", None, account_id, 1),
        ("REFUND_SETTLED", "settlement_out", "10", account_id, None, 2),
    ), 1):
        source_id = session.execute(text("""INSERT INTO kernel_source_records(
          tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,source_occurred_at)
          VALUES(:tenant,:org,'m60.verifier','balance_movement',:external,:occurred) RETURNING id"""), {
            "tenant": tenant, "org": organization, "external": f"movement-{index}",
            "occurred": BASE + timedelta(minutes=minute),
        }).scalar_one()
        session.execute(text("""INSERT INTO financial_events(
          public_id,tenant_id,organization_unit_id,event_type_code,event_version,amount,currency_code,
          economic_role,source_operational_account_id,target_operational_account_id,source_record_id,
          occurred_at,business_date,calendar_policy_version,actor_service,idempotency_scope,idempotency_key,
          correlation_id,classification_snapshot,posting_context,metadata)
          VALUES(:public,:tenant,:org,:event,1,:amount,'XAF',:role,:source,:target,:source_record,:occurred,
          :business_date,1,'m60.verifier','m60.movement',:key,:correlation,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb)"""), {
            "public": f"60000000-0000-0000-0002-{index:012d}", "tenant": tenant, "org": organization,
            "event": event_type, "amount": amount, "role": role, "source": source, "target": target,
            "source_record": source_id, "occurred": BASE + timedelta(minutes=minute),
            "business_date": BUSINESS_DATE, "key": f"movement-{index}", "correlation": str(CORRELATION),
        })


def _expect_error(code, action):
    try:
        action()
    except OperationalBalanceValidationError as exc:
        if exc.code != code:
            raise RuntimeError(f"expected error={code} actual={exc.code}") from exc
    else:
        raise RuntimeError(f"expected error={code}")


def _exercise(engine):
    with Session(engine) as session, session.begin():
        tenant, organization, other_organization = _seed_scope(session)
        parent_command = _account(tenant, organization, public_id=UUID("60000000-0000-0000-0000-000000000010"), code="m60-cash", aggregation="parent_aggregate", key="parent")
        parent = TransactionalOperationalBalanceEngine.create_account(session, parent_command)
        leaf_command = _account(tenant, organization, parent=parent.public_id)
        leaf = TransactionalOperationalBalanceEngine.create_account(session, leaf_command)
        replay = TransactionalOperationalBalanceEngine.create_account(session, leaf_command)
        if not replay.replayed or replay.id != leaf.id:
            raise RuntimeError("account replay failed")
        _expect_error("idempotency_conflict", lambda: TransactionalOperationalBalanceEngine.create_account(session, replace(leaf_command, display_name="Changed")))
        anchor_command = _anchor(tenant, organization, leaf.public_id)
        anchor = TransactionalOperationalBalanceEngine.record_anchor(session, anchor_command)
        if not TransactionalOperationalBalanceEngine.record_anchor(session, anchor_command).replayed:
            raise RuntimeError("anchor replay failed")
        _expect_error("anchor_already_exists", lambda: TransactionalOperationalBalanceEngine.record_anchor(session, replace(anchor_command, public_id=UUID("60000000-0000-0000-0001-000000000002"), idempotency_key="second")))
        _expect_error("account_scope_mismatch", lambda: TransactionalOperationalBalanceEngine.record_actual(session, _actual(tenant, other_organization, leaf.public_id, public_id=UUID("60000000-0000-0000-0003-000000000009"), key="wrong-org", balance="1", minute=1)))
        _insert_movements(session, tenant, organization, leaf.id)
        before_actual = OperationalBalanceService.resolve(session, OperationalBalanceQuery(tenant, organization, leaf.public_id, BASE + timedelta(minutes=2)))
        if before_actual.expected_balance != Decimal("130") or before_actual.actual_balance is not None or before_actual.variance is not None:
            raise RuntimeError(f"missing-actual semantics failed={before_actual}")
        first_command = _actual(tenant, organization, leaf.public_id, public_id=UUID("60000000-0000-0000-0003-000000000001"), key="count-1", balance="128", minute=3)
        first = TransactionalOperationalBalanceEngine.record_actual(session, first_command)
        if not TransactionalOperationalBalanceEngine.record_actual(session, first_command).replayed:
            raise RuntimeError("actual replay failed")
        _expect_error("idempotency_conflict", lambda: TransactionalOperationalBalanceEngine.record_actual(session, replace(first_command, actual_balance=Decimal("129"))))
        position = OperationalBalanceService.resolve(session, OperationalBalanceQuery(tenant, organization, leaf.public_id, BASE + timedelta(minutes=3)))
        if (position.anchor_balance, position.inflows, position.outflows, position.expected_balance, position.actual_balance, position.variance, position.actual_provenance) != (Decimal("100"), Decimal("40"), Decimal("10"), Decimal("130"), Decimal("128"), Decimal("-2"), "operator_counted"):
            raise RuntimeError(f"expected/actual/variance projection failed={position}")
        TransactionalOperationalBalanceEngine.record_actual(session, _actual(tenant, organization, leaf.public_id, public_id=UUID("60000000-0000-0000-0003-000000000002"), key="statement-1", balance="130", minute=4, provenance="external_statement"))
        latest = OperationalBalanceService.resolve(session, OperationalBalanceQuery(tenant, organization, leaf.public_id, BASE + timedelta(minutes=5)))
        if latest.actual_balance != Decimal("130") or latest.variance != Decimal("0") or latest.actual_provenance != "external_statement":
            raise RuntimeError(f"latest actual selection failed={latest}")
        try:
            with session.begin_nested():
                session.execute(text("UPDATE operational_account_balance_observations SET actual_balance=999 WHERE id=:id"), {"id": first.id})
        except DBAPIError:
            pass
        else:
            raise RuntimeError("actual observation update was accepted")
        try:
            with session.begin_nested():
                session.execute(text("UPDATE operational_financial_accounts SET code='mutated' WHERE id=:id"), {"id": leaf.id})
        except DBAPIError:
            pass
        else:
            raise RuntimeError("operational account identity update was accepted")

    with engine.connect() as connection:
        counts = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in M60_TABLES}
        if counts != {"operational_account_authorities": 2, "operational_account_balance_anchors": 1, "operational_account_balance_observations": 2}:
            raise RuntimeError(f"unexpected M6.0 counts={counts}")
        account_public = UUID(str(connection.execute(text("SELECT public_id FROM operational_financial_accounts WHERE code='m60-drawer'")).scalar_one()))
        tenant = int(connection.execute(text("SELECT tenant_id FROM operational_financial_accounts WHERE public_id=:public"), {"public": str(account_public)}).scalar_one())
        organization = int(connection.execute(text("SELECT organization_unit_id FROM operational_financial_accounts WHERE public_id=:public"), {"public": str(account_public)}).scalar_one())
        before = connection.execute(text("SELECT count(*) FROM operational_account_balance_observations")).scalar_one()
    with Session(engine) as session:
        transaction = session.begin()
        TransactionalOperationalBalanceEngine.record_actual(session, _actual(tenant, organization, account_public, public_id=UUID("60000000-0000-0000-0003-000000000003"), key="rollback", balance="130", minute=6))
        session.flush()
        transaction.rollback()
    with engine.connect() as connection:
        after = connection.execute(text("SELECT count(*) FROM operational_account_balance_observations")).scalar_one()
        if before != after:
            raise RuntimeError("outer rollback leaked actual observation")


def _run():
    _verify_development()
    _create_clone()
    engine = None
    try:
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        engine = _engine(TEST_DATABASE_NAME)
        with engine.connect() as connection:
            if _revision(connection) != TARGET_REVISION:
                raise RuntimeError("disposable database did not reach M6.0")
        engine.dispose(); engine = None
        _migrate(TEST_DATABASE_NAME, PARENT_REVISION, downgrade=True)
        _migrate(TEST_DATABASE_NAME, TARGET_REVISION)
        engine = _engine(TEST_DATABASE_NAME)
        _exercise(engine)
        engine.dispose(); engine = None
        _drop(TEST_DATABASE_NAME)
        _verify_development()
        print(f"m60_operational_balance=PASS database={TEST_DATABASE_NAME} account_authority=PASS hierarchy=PASS anchor=PASS expected=PASS actual_provenance=PASS variance=PASS cutoff=PASS replay=PASS conflict=PASS tenant_org_scope=PASS immutability=PASS rollback=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if engine is not None:
            engine.dispose()
        print(f"M6.0 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("verify")
    subparsers.add_parser("create-and-verify")
    drop = subparsers.add_parser("drop")
    drop.add_argument("--confirm-database-name", required=True)
    args = parser.parse_args()
    if args.command == "status":
        return 0 if _status() else 1
    if args.command == "verify":
        _verify_development()
    elif args.command == "create-and-verify":
        _run()
    else:
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME)
        print(f"dropped={TEST_DATABASE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
