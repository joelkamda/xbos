"""Disposable acceptance rehearsal for grouped M5.2 commercial terms."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
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

from core.domain.finance.commercial_terms_contract import CommercialTermComponent, CommercialTermsError, RecognizeCommercialTermsCommand
from core.domain.finance.commercial_terms_engine import TransactionalCommercialTermsEngine
from core.domain.finance.event_contract import FinancialEventIdempotencyConflict
from database import engine as application_engine


DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m52_commercial_terms_test"
TARGET_REVISION = "m46_provider_financials_015"
BASE = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
CORRELATION = UUID("52000000-0000-0000-0000-000000000099")
TENANT = 5201
ORGANIZATION = 5211


def _application_url():
    return make_url(application_engine.url.render_as_string(hide_password=False))


def _url(database_name):
    return _application_url().set(database=database_name)


def _engine(database_name, *, autocommit=False):
    return create_engine(_url(database_name), pool_pre_ping=True, **({"isolation_level": "AUTOCOMMIT"} if autocommit else {}))


def _exists(database_name):
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": database_name}).scalar_one_or_none())
    finally:
        engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME):
        raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally:
        engine.dispose()


def _drop(database_name):
    if database_name != TEST_DATABASE_NAME:
        raise RuntimeError(f"refusing unapproved database: {database_name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": database_name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        engine.dispose()


@contextmanager
def _selected(database_name):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(database_name).render_as_string(hide_password=False)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _upgrade():
    with _selected(TEST_DATABASE_NAME):
        alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME:
        raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != TARGET_REVISION:
            raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20:
            raise RuntimeError("canonical catalog count differs")
        for table in ("idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() != 0:
                raise RuntimeError(f"development table is not empty: {table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}")
    print(f"revision={TARGET_REVISION}")
    print("m52_commercial_terms_development=PASS")


def _seed(session):
    tenant = TENANT
    organization = ORGANIZATION
    session.execute(text("""INSERT INTO tenants(id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
        VALUES(:tenant,'M52T','M5.2 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)"""), {"tenant": tenant})
    session.execute(text("""INSERT INTO organization_units(id,tenant_id,unit_type,code,name,timezone_name,active)
        VALUES(:org,:tenant,'legal_entity','M52','M5.2 Entity','Africa/Douala',true)"""), {"org": organization, "tenant": tenant})
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    session.execute(text("""INSERT INTO tenant_currency_policies(tenant_id,currency_code,rounding_mode,cash_rounding_increment,active,effective_from,policy_version)
        VALUES(:tenant,'XAF','half_even',0,true,'2026-08-01',52) ON CONFLICT(tenant_id,currency_code,policy_version) DO UPDATE SET active=true"""), {"tenant": tenant})
    session.execute(text("""INSERT INTO accounting_periods(tenant_id,legal_entity_unit_id,period_code,period_start,period_end,period_state)
        VALUES(:tenant,:org,'2026-08','2026-08-01','2026-08-31','open') ON CONFLICT(tenant_id,legal_entity_unit_id,period_code) DO NOTHING"""), {"tenant": tenant, "org": organization})
    roles = (
        ("trade_or_contract_receivable", "m52-ar", "asset", "debit"),
        ("sales_discount_contra_revenue", "m52-discount", "contra", "debit"),
        ("marketing_or_promotional_expense", "m52-promotion", "expense", "debit"),
        ("complimentary_contra_revenue", "m52-complimentary", "contra", "debit"),
        ("service_recovery_expense", "m52-recovery", "expense", "debit"),
        ("classified_revenue", "m52-service-fee", "income", "credit"),
        ("tax_payable", "m52-tax", "liability", "credit"),
    )
    for index, (role, code, account_type, balance) in enumerate(roles, 1):
        account = session.execute(text("""INSERT INTO ledger_accounts(public_id,tenant_id,legal_entity_unit_id,account_code,account_name,account_type,normal_balance,currency_policy,fixed_currency_code,active,effective_from)
            VALUES(:public,:tenant,:org,:code,:name,:type,:balance,'fixed','XAF',true,'2026-01-01')
            ON CONFLICT(tenant_id,legal_entity_unit_id,account_code) DO UPDATE SET active=true RETURNING id"""), {
            "public": f"52000000-0000-0000-0002-{index:012d}", "tenant": tenant, "org": organization,
            "code": code, "name": role.replace("_", " ").title(), "type": account_type, "balance": balance,
        }).scalar_one()
        session.execute(text("""INSERT INTO ledger_account_role_bindings(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,ledger_account_id,effective_from,active)
            VALUES(:tenant,:org,:role,'default','XAF',:account,'2026-01-01',true)
            ON CONFLICT(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,effective_from) DO UPDATE SET active=true"""), {"tenant": tenant, "org": organization, "role": role, "account": account})
    source_specs = ((1, "commercial_adjustment"), (2, "commercial_adjustment"), (3, "commercial_transaction_line"), (4, "commercial_transaction_component"), (5, "commercial_adjustment"))
    source_ids = {}
    for number, kind in source_specs:
        source_ids[number] = int(session.execute(text("""INSERT INTO kernel_source_records(public_id,tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,aggregate_version,source_occurred_at,metadata)
            VALUES(:public,:tenant,:org,'m52.verifier',:kind,:external,'1',:occurred,'{}'::jsonb) RETURNING id"""), {
            "public": f"52000000-0000-0000-0003-{number:012d}", "tenant": tenant, "org": organization,
            "kind": kind, "external": f"component-{number}", "occurred": BASE,
        }).scalar_one())
    return tenant, organization, source_ids


def _component(kind, number, source, amount, *, policy=None):
    classification = {
        "discount": {"discount_reason": {"code": "approved_campaign"}},
        "complimentary": {"complimentary_reason": {"code": "guest_recovery"}, "complimentary_policy": {"code": policy or "promotion"}},
        "customer_service_fee": {"revenue_nature": {"code": "customer_service_fee"}},
        "output_tax": {"tax_jurisdiction": {"code": "CM"}, "tax_code": {"code": "VAT"}},
    }[kind]
    return CommercialTermComponent(UUID(f"52000000-0000-0000-0004-{number:012d}"), source, kind, amount, classification)


def _command(tenant, organization, sources):
    components = (
        _component("discount", 1, sources[1], "10"),
        _component("complimentary", 2, sources[2], "15"),
        _component("customer_service_fee", 3, sources[3], "5"),
        _component("output_tax", 4, sources[4], "18"),
    )
    return RecognizeCommercialTermsCommand(tenant, organization, "100", "98", "XAF", BASE, date(2026, 8, 10), 1, CORRELATION, "m52.terms", "m52.verifier", components)


def _exercise(engine):
    with Session(engine) as session, session.begin():
        tenant, organization, sources = _seed(session)
        command = _command(tenant, organization, sources)
        first = TransactionalCommercialTermsEngine.recognize(session, command)
        if first.replayed or first.summary.customer_collectible != Decimal("98"):
            raise RuntimeError("commercial formula or first emission failed")
        replay = TransactionalCommercialTermsEngine.recognize(session, command)
        if not replay.replayed:
            raise RuntimeError("component replay failed")
        conflict_component = replace(command.components[0], amount=Decimal("11"))
        try:
            TransactionalCommercialTermsEngine.recognize(session, replace(command, customer_collectible_amount=Decimal("97"), components=(conflict_component, *command.components[1:])))
        except FinancialEventIdempotencyConflict:
            pass
        else:
            raise RuntimeError("conflicting component replay was accepted")
        try:
            replace(command, customer_collectible_amount=Decimal("99"))
        except CommercialTermsError:
            pass
        else:
            raise RuntimeError("collectible mismatch was accepted")
        try:
            replace(command, gross_sales_amount=Decimal("20"), customer_collectible_amount=Decimal("18"))
        except CommercialTermsError:
            pass
        else:
            raise RuntimeError("allowance capacity was exceeded")
        try:
            TransactionalCommercialTermsEngine.recognize(session, replace(command, tenant_id=tenant + 999))
        except CommercialTermsError:
            pass
        else:
            raise RuntimeError("cross-tenant source was accepted")
        before = session.execute(text("SELECT count(*) FROM financial_events")).scalar_one()
        invalid = _component("output_tax", 5, sources[5], "1")
        try:
            TransactionalCommercialTermsEngine.recognize(session, replace(command, customer_collectible_amount=Decimal("99"), components=(*command.components, invalid)))
        except CommercialTermsError:
            pass
        else:
            raise RuntimeError("wrong source kind was accepted")
        if session.execute(text("SELECT count(*) FROM financial_events")).scalar_one() != before:
            raise RuntimeError("atomic rollback failed")
        counts = {table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ("financial_events", "outbox_messages", "journal_entries", "journal_lines")}
        if counts != {"financial_events": 4, "outbox_messages": 4, "journal_entries": 4, "journal_lines": 8}:
            raise RuntimeError(f"unexpected canonical counts={counts}")
        if session.execute(text("""SELECT count(*) FROM journal_entries je
            WHERE je.entry_state<>'posted' OR EXISTS (
              SELECT 1 FROM journal_lines jl
              WHERE jl.tenant_id=je.tenant_id AND jl.journal_entry_id=je.id
              GROUP BY jl.tenant_id,jl.journal_entry_id
              HAVING sum(jl.transaction_debit_amount)<>sum(jl.transaction_credit_amount)
                  OR sum(jl.base_debit_amount)<>sum(jl.base_credit_amount)
            )""")).scalar_one():
            raise RuntimeError("unbalanced commercial journal")


def _run():
    _development_verify()
    _create()
    engine = None
    try:
        _upgrade()
        engine = _engine(TEST_DATABASE_NAME)
        _exercise(engine)
        engine.dispose(); engine = None
        _drop(TEST_DATABASE_NAME)
        _development_verify()
    except Exception:
        if engine is not None:
            engine.dispose()
        print(f"M5.2 verification failed; retained disposable database={TEST_DATABASE_NAME}")
        raise
    print("m52_commercial_terms=PASS database=xbos_track_b_m52_commercial_terms_test formula=PASS allowances=PASS fees=PASS tax=PASS provider_fee_separation=PASS tenant_scope=PASS replay=PASS conflict=PASS posting=PASS atomic_rollback=PASS canonical_head_unchanged=PASS dropped=true")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "create-and-verify", "drop"))
    parser.add_argument("--confirm-database-name")
    args = parser.parse_args()
    if args.command == "verify":
        _development_verify()
    elif args.command == "status":
        print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME:
            raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    else:
        _run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
