"""Disposable acceptance rehearsal for grouped M5.3 tips and commissions."""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
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

from core.domain.finance.event_contract import FinancialEventIdempotencyConflict
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand, ObligationValidationError
from core.domain.finance.participant_earning_contract import CommissionBasis, EarningContext, ParticipantEarningError, RecognizeCommissionCommand, RecognizeTipCommand
from core.domain.finance.participant_earning_engine import TransactionalParticipantEarningEngine
from core.domain.finance.participant_earning_service import ParticipantEarningBalanceService
from database import engine as application_engine


DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m53_earnings_test"
TARGET_REVISION = "m46_provider_financials_015"
TENANT = 5301
ORGANIZATION = 5311
TENANT_PARTY = UUID("53000000-0000-0000-0000-000000000010")
BENEFICIARY = UUID("53000000-0000-0000-0000-000000000011")
SECOND_BENEFICIARY = UUID("53000000-0000-0000-0000-000000000012")
CORRELATION = UUID("53000000-0000-0000-0000-000000000099")
BASE = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)


def _application_url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _url(name): return _application_url().set(database=name)
def _engine(name, *, autocommit=False): return create_engine(_url(name), pool_pre_ping=True, **({"isolation_level": "AUTOCOMMIT"} if autocommit else {}))


def _exists(name):
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally: engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists: {TEST_DATABASE_NAME}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection: connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE template0'))
    finally: engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME: raise RuntimeError(f"refusing unapproved database: {name}")
    engine = _engine("postgres", autocommit=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally: engine.dispose()


@contextmanager
def _selected(name):
    previous = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = _url(name).render_as_string(hide_password=False)
    try: yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous


def _upgrade():
    with _selected(TEST_DATABASE_NAME): alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)


def _development_verify():
    if _application_url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != TARGET_REVISION: raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20: raise RuntimeError("canonical catalog count differs")
        for table in ("idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines", "financial_obligations"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() != 0: raise RuntimeError(f"development table is not empty: {table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={TARGET_REVISION}"); print("m53_participant_earnings_development=PASS")


def _seed(session):
    session.execute(text("""INSERT INTO tenants(id,code,name,country_code,country_name,currency,locale,timezone,settings,extra_metadata)
        VALUES(:tenant,'M53T','M5.3 Proof','CM','Cameroon','XAF','en-CM','Africa/Douala','{}'::json,'{}'::json)"""), {"tenant": TENANT})
    session.execute(text("""INSERT INTO organization_units(id,tenant_id,unit_type,code,name,timezone_name,active)
        VALUES(:org,:tenant,'legal_entity','M53','M5.3 Entity','Africa/Douala',true)"""), {"org": ORGANIZATION, "tenant": TENANT})
    session.execute(text("INSERT INTO currency_assets(code,asset_kind,display_name,minor_unit_scale,maximum_storage_scale,active) VALUES('XAF','fiat','Central African CFA franc',0,8,true) ON CONFLICT(code) DO NOTHING"))
    session.execute(text("""INSERT INTO tenant_currency_policies(tenant_id,currency_code,rounding_mode,cash_rounding_increment,active,effective_from,policy_version)
        VALUES(:tenant,'XAF','half_even',0,true,'2026-08-01',53)"""), {"tenant": TENANT})
    session.execute(text("""INSERT INTO accounting_periods(tenant_id,legal_entity_unit_id,period_code,period_start,period_end,period_state)
        VALUES(:tenant,:org,'2026-08','2026-08-01','2026-08-31','open')"""), {"tenant": TENANT, "org": ORGANIZATION})
    roles = (
        ("trade_or_contract_receivable", "m53-ar", "asset", "debit"),
        ("tip_payable", "m53-tip-payable", "liability", "credit"),
        ("tip_or_service_charge_income", "m53-tip-income", "income", "credit"),
        ("classified_expense", "m53-commission-expense", "expense", "debit"),
        ("trade_or_accrued_payable", "m53-accrued-payable", "liability", "credit"),
    )
    for index, (role, code, account_type, balance) in enumerate(roles, 1):
        account = session.execute(text("""INSERT INTO ledger_accounts(public_id,tenant_id,legal_entity_unit_id,account_code,account_name,account_type,normal_balance,currency_policy,fixed_currency_code,active,effective_from)
            VALUES(:public,:tenant,:org,:code,:name,:type,:balance,'fixed','XAF',true,'2026-01-01') RETURNING id"""), {
            "public": f"53000000-0000-0000-0003-{index:012d}", "tenant": TENANT, "org": ORGANIZATION,
            "code": code, "name": role.replace("_", " ").title(), "type": account_type, "balance": balance,
        }).scalar_one()
        session.execute(text("""INSERT INTO ledger_account_role_bindings(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,ledger_account_id,effective_from,active)
            VALUES(:tenant,:org,:role,'default','XAF',:account,'2026-01-01',true)"""), {"tenant": TENANT, "org": ORGANIZATION, "role": role, "account": account})
    kinds = {1: "commercial_transaction_component", 2: "commercial_adjustment", 3: "expense_transaction", 4: "expense_transaction", 5: "expense_transaction", 6: "commercial_adjustment"}
    sources = {}
    for number, kind in kinds.items():
        sources[number] = int(session.execute(text("""INSERT INTO kernel_source_records(public_id,tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,aggregate_version,source_occurred_at,metadata)
            VALUES(:public,:tenant,:org,'m53.verifier',:kind,:external,'1',:occurred,'{}'::jsonb) RETURNING id"""), {
            "public": f"53000000-0000-0000-0004-{number:012d}", "tenant": TENANT, "org": ORGANIZATION,
            "kind": kind, "external": f"earning-{number}", "occurred": BASE,
        }).scalar_one())
    return sources


def _context(number, source, amount):
    return EarningContext(UUID(f"53000000-0000-0000-0005-{number:012d}"), TENANT, ORGANIZATION, source, amount, "XAF", BASE, date(2026, 8, 10), 1, CORRELATION, "m53.earning", "m53.verifier")


def _payable(number, context, beneficiary, earning_type):
    return CreateObligationCommand(
        UUID(f"53000000-0000-0000-0006-{number:012d}"), TENANT, ORGANIZATION, TENANT_PARTY, beneficiary,
        "expense_payable", context.amount, "XAF", BASE + timedelta(days=1), BASE, date(2026, 8, 10), 1, CORRELATION,
        "m53.verifier", f"earning-{number}", "m53.payable", f"payable-{number}",
        (ObligationLineCommand(1, "earning", "Participant earning", 1, context.amount, context.amount, f"earning-line-{number}"),),
        actor_service="m53.verifier", metadata={"earning_type": earning_type, "beneficiary_party_id": str(beneficiary)},
    )


def _commands(sources):
    staff_context = _context(1, sources[1], "12")
    tenant_context = _context(2, sources[2], "3")
    percent_context = _context(3, sources[3], "10")
    fixed_context = _context(4, sources[4], "7")
    return (
        RecognizeTipCommand(staff_context, "staff_beneficiary", BENEFICIARY, _payable(1, staff_context, BENEFICIARY, "tip")),
        RecognizeTipCommand(tenant_context, "tenant_income"),
        RecognizeCommissionCommand(percent_context, BENEFICIARY, CommissionBasis("percentage", "200", "5"), _payable(3, percent_context, BENEFICIARY, "commission"), "sales_percent"),
        RecognizeCommissionCommand(fixed_context, SECOND_BENEFICIARY, CommissionBasis("fixed", "7", "0"), _payable(4, fixed_context, SECOND_BENEFICIARY, "commission"), "service_fixed"),
    )


def _exercise(engine):
    with Session(engine) as session, session.begin():
        sources = _seed(session)
        staff_tip, tenant_tip, percent_commission, fixed_commission = _commands(sources)
        results = (
            TransactionalParticipantEarningEngine.recognize_tip(session, staff_tip),
            TransactionalParticipantEarningEngine.recognize_tip(session, tenant_tip),
            TransactionalParticipantEarningEngine.recognize_commission(session, percent_commission),
            TransactionalParticipantEarningEngine.recognize_commission(session, fixed_commission),
        )
        if any(result.replayed for result in results): raise RuntimeError("first earning recognition replayed")
        if not TransactionalParticipantEarningEngine.recognize_tip(session, staff_tip).replayed: raise RuntimeError("tip replay failed")
        if not TransactionalParticipantEarningEngine.recognize_commission(session, percent_commission).replayed: raise RuntimeError("commission replay failed")
        if ParticipantEarningBalanceService.get(session, tenant_id=TENANT, beneficiary_party_id=BENEFICIARY, currency_code="XAF").outstanding_payable != 22: raise RuntimeError("primary beneficiary balance differs")
        if ParticipantEarningBalanceService.get(session, tenant_id=TENANT, beneficiary_party_id=SECOND_BENEFICIARY, currency_code="XAF").outstanding_payable != 7: raise RuntimeError("second beneficiary balance differs")
        changed_context = replace(staff_tip.context, amount=13)
        changed_payable = replace(staff_tip.payable, original_amount=13, lines=(ObligationLineCommand(1, "earning", "Participant earning", 1, 13, 13, "conflict-line"),))
        try: TransactionalParticipantEarningEngine.recognize_tip(session, RecognizeTipCommand(changed_context, "staff_beneficiary", BENEFICIARY, changed_payable))
        except FinancialEventIdempotencyConflict: pass
        else: raise RuntimeError("earning idempotency conflict was accepted")
        foreign_context = replace(percent_commission.context, tenant_id=TENANT + 1)
        foreign_payable = replace(percent_commission.payable, tenant_id=TENANT + 1)
        try: TransactionalParticipantEarningEngine.recognize_commission(session, replace(percent_commission, context=foreign_context, payable=foreign_payable))
        except ParticipantEarningError: pass
        else: raise RuntimeError("cross-tenant source was accepted")
        invalid_context = _context(6, sources[6], "2")
        invalid_payable = _payable(6, invalid_context, BENEFICIARY, "commission")
        try: TransactionalParticipantEarningEngine.recognize_commission(session, RecognizeCommissionCommand(invalid_context, BENEFICIARY, CommissionBasis("fixed", "2", "0"), invalid_payable, "invalid_source"))
        except ParticipantEarningError: pass
        else: raise RuntimeError("invalid commission source kind was accepted")
        counts_before = {table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in ("financial_events", "outbox_messages", "journal_entries", "journal_lines", "financial_obligations", "idempotency_records")}
        rollback_context = _context(5, sources[5], "10")
        conflicting_payable = replace(percent_commission.payable, idempotency_key="rollback-new", source_record_id="rollback-new")
        rollback_command = RecognizeCommissionCommand(rollback_context, BENEFICIARY, CommissionBasis("fixed", "10", "0"), conflicting_payable, "rollback_probe")
        try: TransactionalParticipantEarningEngine.recognize_commission(session, rollback_command)
        except ObligationValidationError: pass
        else: raise RuntimeError("payable public-id conflict was accepted")
        counts_after = {table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() for table in counts_before}
        if counts_after != counts_before: raise RuntimeError(f"atomic rollback changed counts before={counts_before} after={counts_after}")
        expected = {"financial_events": 4, "outbox_messages": 4, "journal_entries": 4, "journal_lines": 8, "financial_obligations": 3, "idempotency_records": 7}
        if counts_after != expected: raise RuntimeError(f"unexpected canonical counts={counts_after}")
        if session.execute(text("""SELECT count(*) FROM journal_entries je WHERE je.entry_state<>'posted' OR EXISTS (
            SELECT 1 FROM journal_lines jl WHERE jl.tenant_id=je.tenant_id AND jl.journal_entry_id=je.id
            GROUP BY jl.tenant_id,jl.journal_entry_id HAVING sum(jl.transaction_debit_amount)<>sum(jl.transaction_credit_amount) OR sum(jl.base_debit_amount)<>sum(jl.base_credit_amount))""")).scalar_one(): raise RuntimeError("unbalanced earning journal")


def _run():
    _development_verify(); _create(); engine = None
    try:
        _upgrade(); engine = _engine(TEST_DATABASE_NAME); _exercise(engine); engine.dispose(); engine = None; _drop(TEST_DATABASE_NAME); _development_verify()
    except Exception:
        if engine is not None: engine.dispose()
        print(f"M5.3 verification failed; retained disposable database={TEST_DATABASE_NAME}"); raise
    print("m53_participant_earnings=PASS database=xbos_track_b_m53_earnings_test staff_tip=PASS tenant_tip=PASS commission=PASS calculation=PASS beneficiary_balance=PASS tenant_scope=PASS source_kind=PASS replay=PASS conflict=PASS posting=PASS atomic_rollback=PASS canonical_head_unchanged=PASS dropped=true")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("verify", "status", "create-and-verify", "drop")); parser.add_argument("--confirm-database-name"); args = parser.parse_args()
    if args.command == "verify": _development_verify()
    elif args.command == "status": print(f"database={TEST_DATABASE_NAME} exists={str(_exists(TEST_DATABASE_NAME)).lower()}")
    elif args.command == "drop":
        if args.confirm_database_name != TEST_DATABASE_NAME: raise RuntimeError("exact disposable database confirmation required")
        _drop(TEST_DATABASE_NAME); print(f"dropped={TEST_DATABASE_NAME}")
    else: _run()
    return 0


if __name__ == "__main__": raise SystemExit(main())
