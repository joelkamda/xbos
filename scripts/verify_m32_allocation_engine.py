"""Disposable and development gates for M3.2 allocation authority."""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from core.domain.finance.allocation_contract import (
    AllocateValueCommand, AllocationValidationError, CreateValueSourceCommand, ReverseAllocationCommand,
)
from core.domain.finance.allocation_engine import TransactionalAllocationEngine
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from database import engine as application_engine

TEST_DATABASE_NAME = "xbos_track_b_m32_allocation_test"
DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
PARENT_REVISION = "m30_obligation_foundation_008"
TARGET_REVISION = "m32_allocation_engine_009"
DEVELOPMENT_REVISIONS = {PARENT_REVISION, TARGET_REVISION, "m34_obligation_aging_010"}
TENANT = 3201
ORG_A = 3211
ORG_B = 3212
NOW = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _url(name):
    return _application_url().set(database=name)


def _engine(name, autocommit=False):
    return create_engine(_url(name), pool_pre_ping=True, **({"isolation_level": "AUTOCOMMIT"} if autocommit else {}))


def _exists(name):
    engine = _engine("postgres", True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally:
        engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME:
        raise RuntimeError(f"refusing unapproved database: {name}")
    engine = _engine("postgres", True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        engine.dispose()


@contextmanager
def _selected(name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _migrate(revision):
    with _selected(TEST_DATABASE_NAME):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), revision)


def _downgrade(revision):
    with _selected(TEST_DATABASE_NAME):
        alembic_command.downgrade(Config(str(ROOT / "alembic.ini")), revision)


def _seed(engine):
    with engine.begin() as c:
        c.execute(text("""INSERT INTO public.tenants
          (id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
          VALUES (:tenant,'M32T','M3.2 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)"""), {"tenant": TENANT})
        c.execute(text("""INSERT INTO public.currency_assets
          (code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active,metadata)
          VALUES ('XAF','fiat','Central African CFA franc',0,8,TRUE,'{}'::jsonb)"""))
        c.execute(text("""INSERT INTO public.organization_units
          (id,tenant_id,unit_type,code,name,timezone_name,active) VALUES
          (:a,:tenant,'legal_entity','M32A','M3.2 Entity A','Africa/Douala',TRUE),
          (:b,:tenant,'legal_entity','M32B','M3.2 Entity B','Africa/Douala',TRUE)"""), {"tenant": TENANT, "a": ORG_A, "b": ORG_B})


def _obligation(public_id, amount, key, org=ORG_A):
    return CreateObligationCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=org,
        debtor_party_id=UUID("32000000-0000-0000-0000-000000000010"),
        creditor_party_id=UUID("32000000-0000-0000-0000-000000000011"), obligation_type="trade_receivable",
        original_amount=Decimal(amount), currency_code="XAF", due_at=NOW+timedelta(days=30), occurred_at=NOW,
        business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=UUID("32000000-0000-0000-0000-000000000099"), actor_service="m32.verifier",
        source_component="m32.verifier", source_record_id=key, idempotency_scope="m32.obligation",
        idempotency_key=key, lines=(ObligationLineCommand(1,"principal","Principal",Decimal("1"),Decimal(amount),Decimal(amount),key+"-line"),))


def _source(public_id, amount, key, org=ORG_A):
    return CreateValueSourceCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=org,
        owner_party_id=UUID("32000000-0000-0000-0000-000000000010"), source_type="payment",
        source_amount=Decimal(amount), currency_code="XAF", occurred_at=NOW, business_date=date(2026,8,9),
        calendar_policy_version=1, correlation_id=UUID("32000000-0000-0000-0000-000000000099"),
        actor_service="m32.verifier", source_component="m32.verifier", source_record_id=key,
        idempotency_scope="m32.source", idempotency_key=key)


def _allocate(public_id, source, obligation, amount, key, org=ORG_A, policy=None):
    return AllocateValueCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=org,
        value_source_public_id=source, obligation_public_id=obligation, allocation_amount=Decimal(amount),
        currency_code="XAF", occurred_at=NOW, business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=UUID("32000000-0000-0000-0000-000000000099"), actor_service="m32.verifier",
        source_component="m32.verifier", source_record_id=key, idempotency_scope="m32.allocate", idempotency_key=key,
        cross_organization_policy_code=policy, cross_organization_policy_version=1 if policy else None)


def _reverse(public_id, allocation, amount, key):
    return ReverseAllocationCommand(
        public_id=public_id, tenant_id=TENANT, organization_unit_id=ORG_A,
        payment_allocation_public_id=allocation, reversal_amount=Decimal(amount), currency_code="XAF",
        reason_code="customer_refund", occurred_at=NOW, business_date=date(2026,8,9), calendar_policy_version=1,
        correlation_id=UUID("32000000-0000-0000-0000-000000000099"), actor_service="m32.verifier",
        source_component="m32.verifier", source_record_id=key, idempotency_scope="m32.reverse", idempotency_key=key)


def _expect(session, action, code):
    try:
        with session.begin_nested():
            action()
    except AllocationValidationError as exc:
        if exc.code != code:
            raise RuntimeError(f"expected {code}, found {exc.code}") from exc
    else:
        raise RuntimeError(f"expected rejection: {code}")


def _exercise(engine):
    o1=UUID("32000000-0000-0000-0000-000000000101"); o2=UUID("32000000-0000-0000-0000-000000000102")
    s1=UUID("32000000-0000-0000-0000-000000000201"); s2=UUID("32000000-0000-0000-0000-000000000202")
    a1=UUID("32000000-0000-0000-0000-000000000301"); a2=UUID("32000000-0000-0000-0000-000000000302"); a3=UUID("32000000-0000-0000-0000-000000000303")
    with Session(engine) as session, session.begin():
        TransactionalObligationEngine.create(session,_obligation(o1,"1000","o1"))
        TransactionalObligationEngine.create(session,_obligation(o2,"400","o2"))
        TransactionalAllocationEngine.create_value_source(session,_source(s1,"1000","s1"))
        TransactionalAllocationEngine.create_value_source(session,_source(s2,"400","s2"))
        first=TransactionalAllocationEngine.allocate(session,_allocate(a1,s1,o1,"600","a1"))
        replay=TransactionalAllocationEngine.allocate(session,_allocate(a1,s1,o1,"600","a1"))
        if not replay.replayed or replay.fact.public_id != first.fact.public_id:
            raise RuntimeError("allocation replay failed")
        TransactionalAllocationEngine.allocate(session,_allocate(a2,s1,o2,"400","a2"))
        TransactionalAllocationEngine.allocate(session,_allocate(a3,s2,o1,"400","a3"))
        _expect(session,lambda: TransactionalAllocationEngine.allocate(session,_allocate(UUID("32000000-0000-0000-0000-000000000304"),s1,o1,"1","over-source")),"source_capacity_exceeded")
        reversal=UUID("32000000-0000-0000-0000-000000000401")
        TransactionalAllocationEngine.reverse(session,_reverse(reversal,a1,"100","r1"))
        _expect(session,lambda: TransactionalAllocationEngine.reverse(session,_reverse(UUID("32000000-0000-0000-0000-000000000402"),a1,"501","over-reversal")),"reversal_capacity_exceeded")
        states=dict(session.execute(text("SELECT public_id,obligation_state FROM financial_obligations")).all())
        if states[o1] != "partially_satisfied" or states[o2] != "satisfied":
            raise RuntimeError(f"satisfaction projection differs: {states}")
        counts=[session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ("value_sources","payment_allocations","allocation_reversals")]
        if counts != [2,3,1]:
            raise RuntimeError(f"atomic fact counts differ: {counts}")

        # Exact, active, versioned policy authorizes only the declared direction.
        cross_source=UUID("32000000-0000-0000-0000-000000000203")
        cross_obligation=UUID("32000000-0000-0000-0000-000000000103")
        TransactionalObligationEngine.create(session,_obligation(cross_obligation,"50","cross-o"))
        TransactionalAllocationEngine.create_value_source(session,_source(cross_source,"50","cross-s",ORG_B))
        session.execute(text("""INSERT INTO allocation_scope_policies
          (tenant_id,policy_code,policy_version,source_organization_unit_id,target_organization_unit_id,
           currency_code,effective_from,active) VALUES
          (:tenant,'shared_cash',1,:source_org,:target_org,'XAF',:day,TRUE)"""),
          {"tenant":TENANT,"source_org":ORG_B,"target_org":ORG_A,"day":date(2026,8,9)})
        TransactionalAllocationEngine.allocate(session,_allocate(
          UUID("32000000-0000-0000-0000-000000000305"),cross_source,cross_obligation,"50","cross-a",policy="shared_cash"))

    # Outer rollback proves facts and idempotency share the caller transaction.
    with Session(engine) as session:
        transaction=session.begin()
        transient=UUID("32000000-0000-0000-0000-000000000299")
        TransactionalAllocationEngine.create_value_source(session,_source(transient,"5","rollback"))
        transaction.rollback()
        if session.execute(text("SELECT count(*) FROM value_sources WHERE public_id=:id"),{"id":str(transient)}).scalar_one():
            raise RuntimeError("outer rollback leaked value source")

    # Direct SQL cannot mutate facts or claim a policy for same-organization allocation.
    with engine.connect() as connection:
        try:
            with connection.begin():
                connection.execute(text("UPDATE payment_allocations SET allocation_amount=1 WHERE public_id=:id"),{"id":str(a1)})
        except Exception:
            pass
        else:
            raise RuntimeError("allocation immutability bypass succeeded")

    # Two writers compete for one source. Aggregate locking permits one commit only.
    concurrent_source=UUID("32000000-0000-0000-0000-000000000204")
    concurrent_o1=UUID("32000000-0000-0000-0000-000000000104")
    concurrent_o2=UUID("32000000-0000-0000-0000-000000000105")
    with Session(engine) as session, session.begin():
        TransactionalObligationEngine.create(session,_obligation(concurrent_o1,"100","co1"))
        TransactionalObligationEngine.create(session,_obligation(concurrent_o2,"100","co2"))
        TransactionalAllocationEngine.create_value_source(session,_source(concurrent_source,"100","cs"))

    def compete(index, obligation):
        try:
            with Session(engine) as session, session.begin():
                TransactionalAllocationEngine.allocate(session,_allocate(
                  UUID(f"32000000-0000-0000-0000-00000000031{index}"),concurrent_source,obligation,"100",f"race-{index}"))
            return "committed"
        except Exception:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda pair: compete(*pair), [(1,concurrent_o1),(2,concurrent_o2)]))
    if sorted(outcomes) != ["committed","rejected"]:
        raise RuntimeError(f"concurrent source capacity differs: {outcomes}")

    # A direct insert beyond remaining source/obligation capacity must fail at the trigger.
    try:
        with engine.begin() as connection:
            source_id=connection.execute(text("SELECT id FROM value_sources WHERE public_id=:id"),{"id":str(concurrent_source)}).scalar_one()
            obligation_id=connection.execute(text("SELECT id FROM financial_obligations WHERE public_id=:id"),{"id":str(concurrent_o1)}).scalar_one()
            connection.execute(text("""INSERT INTO payment_allocations
                  (public_id,tenant_id,organization_unit_id,value_source_id,obligation_id,allocation_amount,currency_code,
                   occurred_at,business_date,calendar_policy_version,correlation_id,actor_service,source_component,
                   source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
                  VALUES (:public_id,:tenant,:org,:source,:obligation,1,'XAF',:occurred,:day,1,:correlation,
                   'm32.verifier','m32.direct','over-capacity','m32.direct','over-capacity',:fingerprint,'{}'::jsonb)"""),
                  {"public_id":str(UUID("32000000-0000-0000-0000-000000000399")),"tenant":TENANT,"org":ORG_A,
                   "source":source_id,"obligation":obligation_id,"occurred":NOW,"day":date(2026,8,9),
                   "correlation":str(UUID("32000000-0000-0000-0000-000000000099")),"fingerprint":"f"*64})
    except Exception:
        pass
    else:
        raise RuntimeError("direct SQL capacity bypass succeeded")


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected development database {DEVELOPMENT_DATABASE_NAME}")
    tables=("financial_dimension_types","financial_dimension_values","posting_dimension_policies","idempotency_records",
            "financial_events","outbox_messages","journal_entries","journal_lines","financial_obligations",
            "financial_obligation_lines","value_sources","payment_allocations","allocation_reversals","allocation_scope_policies")
    with application_engine.connect() as c:
        revision=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision not in DEVELOPMENT_REVISIONS:
            raise RuntimeError(f"unexpected development revision: {revision}")
        catalog=c.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one()
        if catalog != 20:
            raise RuntimeError(f"catalog count differs: {catalog}")
        for table in tables:
            if table == "allocation_scope_policies" and revision == PARENT_REVISION:
                continue
            count=c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            if count != 0:
                raise RuntimeError(f"development table is not empty: {table}={count}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={revision}")
    print("m32_allocation_development=PASS")


def _create_and_verify():
    _development_verify(); _create(); engine=None
    try:
        _migrate(TARGET_REVISION); engine=_engine(TEST_DATABASE_NAME); _seed(engine); _exercise(engine)
        engine.dispose(); engine=None
        _downgrade(PARENT_REVISION); _migrate(TARGET_REVISION)
        _drop(TEST_DATABASE_NAME); _development_verify()
        print("m32_allocation_engine=PASS database=xbos_track_b_m32_allocation_test partial_split=PASS one_to_many=PASS many_to_one=PASS replay=PASS source_capacity=PASS obligation_capacity=PASS reversal=PASS policy=PASS concurrency=PASS direct_sql=PASS projection=PASS rollback=PASS upgrade_downgrade_upgrade=PASS dropped=true")
    except Exception:
        if engine is not None: engine.dispose()
        print(f"M3.2 verification failed; retained disposable database={TEST_DATABASE_NAME}",file=sys.stderr)
        raise


def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("status"); sub.add_parser("verify"); sub.add_parser("create-and-verify")
    drop=sub.add_parser("drop"); drop.add_argument("--confirm-database-name",required=True)
    args=parser.parse_args()
    if args.command=="status": print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command=="verify": _development_verify()
    elif args.command=="drop": _drop(args.confirm_database_name); print(f"dropped={args.confirm_database_name}")
    else: _create_and_verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
