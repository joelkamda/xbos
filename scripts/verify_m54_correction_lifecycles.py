"""Read-only development gate and disposable M5.4 correction-lifecycle rehearsal."""
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
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from core.domain.finance.atomic_posting_engine import AtomicPostedFinancialEventEngine
from core.domain.finance.correction_contract import ClassifyLifecycleDispositionCommand, CorrectionContext, CorrectionDocumentReference, CorrectionLifecycleError, RecognizeChargebackCommand, RecognizeCommercialReturnCommand, RecognizeRefundCommand, ReverseFinancialFactCommand, WriteOffObligationCommand
from core.domain.finance.correction_engine import TransactionalCorrectionLifecycleEngine
from core.domain.finance.correction_service import LifecycleDispositionService
from core.domain.finance.event_contract import CanonicalFinancialEventCommand, FinancialEventIdempotencyConflict
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand, ObligationValidationError, TransitionObligationCommand
from core.domain.finance.obligation_engine import TransactionalObligationEngine
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_settlement_contract import CreatePaymentSettlementCommand, TransitionPaymentSettlementCommand
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.provider_financial_contract import CreateProviderSettlementComponentCommand
from database import engine as application_engine
from scripts.verify_m46_provider_financials import _seed_confirmed_settlement, _seed_scope

DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"
TEST_DATABASE_NAME = "xbos_track_b_m54_corrections_test"
TARGET_REVISION = "m46_provider_financials_015"
BASE = datetime(2026, 8, 10, 14, tzinfo=timezone.utc)
CORRELATION = UUID("54000000-0000-0000-0000-000000000099")
HASHES = {number: f"{number:064x}" for number in range(1, 20)}


def _url(): return make_url(application_engine.url.render_as_string(hide_password=False))
def _engine(name, isolation=None): return create_engine(_url().set(database=name), isolation_level=isolation, pool_pre_ping=True)


def _exists(name):
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection: return bool(connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}).scalar_one_or_none())
    finally: engine.dispose()


def _create():
    if _exists(TEST_DATABASE_NAME): raise RuntimeError(f"disposable database already exists={TEST_DATABASE_NAME}")
    application_engine.dispose()
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection: connection.exec_driver_sql(f'CREATE DATABASE "{TEST_DATABASE_NAME}" TEMPLATE "{DEVELOPMENT_DATABASE_NAME}"')
    finally: engine.dispose()


def _drop(name):
    if name != TEST_DATABASE_NAME: raise RuntimeError(f"unsafe disposable target={name}")
    engine = _engine("postgres", "AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()"), {"name": name})
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}"')
    finally: engine.dispose()


@contextmanager
def _selected(name):
    previous = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = _url().set(database=name).render_as_string(hide_password=False)
    try: yield
    finally:
        if previous is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = previous


def _development_verify():
    if _url().database != DEVELOPMENT_DATABASE_NAME: raise RuntimeError(f"expected database={DEVELOPMENT_DATABASE_NAME}")
    with application_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != TARGET_REVISION: raise RuntimeError(f"expected revision={TARGET_REVISION}; actual={revision}")
        if connection.execute(text("SELECT count(*) FROM financial_event_type_versions")).scalar_one() != 20: raise RuntimeError("canonical catalog differs")
        for table in ("idempotency_records", "financial_events", "outbox_messages", "journal_entries", "journal_lines", "financial_obligations", "payment_settlements", "provider_settlement_components"):
            if connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one(): raise RuntimeError(f"development table is not empty={table}")
    print(f"database={DEVELOPMENT_DATABASE_NAME}"); print(f"revision={TARGET_REVISION}"); print("m54_correction_lifecycles_development=PASS")


def _document(kind, number): return CorrectionDocumentReference(kind, f"M54-{number:03d}", HASHES[number])


def _source(session, tenant, organization, number, kind, document):
    return int(session.execute(text("""INSERT INTO kernel_source_records(public_id,tenant_id,organization_unit_id,source_component,aggregate_type,aggregate_external_id,aggregate_version,source_occurred_at,metadata)
        VALUES(:public,:tenant,:org,'m54.verifier',:kind,:external,'1',:occurred,jsonb_build_object('document_type',:dtype,'document_number',:dnumber,'evidence_hash',:hash)) RETURNING id"""), {
        "public": f"54000000-0000-0000-0001-{number:012d}", "tenant": tenant, "org": organization, "kind": kind,
        "external": f"m54-{number}", "occurred": BASE, "dtype": document.document_type, "dnumber": document.document_number, "hash": document.evidence_hash,
    }).scalar_one())


def _roles(session, tenant, organization, operational_id):
    roles = (
        ("trade_or_contract_receivable", "m54-ar", "asset", "debit", None), ("classified_revenue", "m54-revenue", "income", "credit", None),
        ("sales_returns_and_allowances", "m54-returns", "contra", "debit", None), ("classified_expense", "m54-expense", "expense", "debit", None),
        ("trade_or_accrued_payable", "m54-ap", "liability", "credit", None), ("writeoff_expense_or_allowance_reserve", "m54-loss", "expense", "debit", None),
        ("trade_receivable", "m54-trade-ar", "asset", "debit", None), ("trade_payable", "m54-trade-ap", "liability", "credit", None),
        ("payable_forgiveness_gain_or_adjustment", "m54-gain", "income", "credit", None), ("refund_payable_or_unapplied_receipts", "m54-refund", "liability", "credit", None),
        ("cash_bank_or_provider_asset", "m54-cash", "asset", "debit", operational_id),
    )
    for index, (role, code, account_type, balance, operational) in enumerate(roles, 1):
        account = session.execute(text("""INSERT INTO ledger_accounts(public_id,tenant_id,legal_entity_unit_id,account_code,account_name,account_type,normal_balance,currency_policy,fixed_currency_code,active,effective_from)
            VALUES(:public,:tenant,:org,:code,:name,:type,:balance,'fixed','XAF',true,'2026-01-01')
            ON CONFLICT(tenant_id,legal_entity_unit_id,account_code) DO UPDATE SET active=true RETURNING id"""), {"public": f"54000000-0000-0000-0002-{index:012d}", "tenant": tenant, "org": organization, "code": code, "name": role, "type": account_type, "balance": balance}).scalar_one()
        session.execute(text("""INSERT INTO ledger_account_role_bindings(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,ledger_account_id,operational_account_id,effective_from,active)
            VALUES(:tenant,:org,:role,'default','XAF',:account,:operational,'2026-01-01',true)
            ON CONFLICT(tenant_id,legal_entity_unit_id,account_role,binding_key,currency_code,effective_from) DO UPDATE SET active=true"""), {"tenant": tenant, "org": organization, "role": role, "account": account, "operational": operational})


def _outgoing_refund(session, tenant, organization, operational):
    intent = CreatePaymentIntentCommand(
        public_id=UUID("54000000-0000-0000-0003-000000000001"), tenant_id=tenant,
        organization_unit_id=organization, requested_amount="30", currency_code="XAF",
        payment_method_policy={"allowed_methods": ["cash"], "max_tenders": 1},
        occurred_at=BASE, business_date=date(2026, 8, 10), calendar_policy_version=1,
        correlation_id=CORRELATION, source_component="m54.verifier", source_record_id="refund-intent",
        idempotency_scope="m54.intent", idempotency_key="refund-intent",
        expires_at=BASE + timedelta(hours=4), actor_service="m54.verifier",
    )
    TransactionalPaymentIntentEngine.create_intent(session, intent)
    settlement = CreatePaymentSettlementCommand(UUID("54000000-0000-0000-0004-000000000001"), tenant, organization, intent.public_id, operational, "outgoing", "30", "0", "30", "XAF", "cash", "cash", date(2026, 8, 10), BASE + timedelta(minutes=20), date(2026, 8, 10), 1, CORRELATION, "m54.verifier", "refund-settlement", "m54.settlement", "refund-settlement", actor_service="m54.verifier")
    TransactionalPaymentSettlementEngine.create(session, settlement)
    TransactionalPaymentSettlementEngine.transition(session, TransitionPaymentSettlementCommand(tenant, organization, settlement.public_id, 1, "confirmed", "final", "available", "cash_refunded", {"receipt": "M54-R"}, BASE + timedelta(minutes=21), date(2026, 8, 10), 1, CORRELATION, "m54.verifier", "refund-confirmed", "m54.settlement.transition", "refund-confirmed", actor_service="m54.verifier"))
    return settlement


def _context(tenant, organization, source, number, amount, document):
    return CorrectionContext(UUID(f"54000000-0000-0000-0005-{number:012d}"), tenant, organization, source, amount, "XAF", BASE + timedelta(minutes=30 + number), date(2026, 8, 10), 1, CORRELATION, "m54.correction", "m54.verifier", document)


def _original_event(session, tenant, organization, source, number, event_type, amount, role, profile, classification):
    return AtomicPostedFinancialEventEngine.emit_and_post(session, CanonicalFinancialEventCommand(UUID(f"54000000-0000-0000-0006-{number:012d}"), tenant, organization, event_type, 1, Decimal(amount), "XAF", role, source, BASE + timedelta(minutes=number), date(2026, 8, 10), 1, f"m54.original.{number}", f"original-{number}", CORRELATION, classification, {"posting_profile_code": profile}, actor_service="m54.verifier"))


def _obligation(tenant, organization, number, amount, obligation_type):
    public = UUID(f"54000000-0000-0000-0007-{number:012d}")
    command = CreateObligationCommand(public, tenant, organization, UUID(int=5401), UUID(int=5402), obligation_type, amount, "XAF", BASE + timedelta(days=30), BASE, date(2026, 8, 10), 1, CORRELATION, "m54.verifier", f"obligation-{number}", "m54.obligation", f"obligation-{number}", (ObligationLineCommand(1, "principal", "M5.4 obligation", 1, amount, amount, f"line-{number}"),), actor_service="m54.verifier")
    return command


def _exercise(engine):
    with Session(engine) as session, session.begin():
        tenant, organization, provider, operational = _seed_scope(session)
        operational_id = int(session.execute(text("SELECT id FROM operational_financial_accounts WHERE public_id=:public"), {"public": str(operational)}).scalar_one())
        _roles(session, tenant, organization, operational_id)
        incoming = _seed_confirmed_settlement(session, tenant, organization, provider, operational)
        outgoing = _outgoing_refund(session, tenant, organization, operational)

        refund_doc = _document("refund_notice", 1); return_doc = _document("credit_note", 2); reversal_doc = _document("reversal_notice", 3)
        receivable_doc = _document("writeoff_notice", 4); payable_doc = _document("writeoff_notice", 5)
        refund_source = _source(session, tenant, organization, 1, "payment_refund", refund_doc)
        return_source = _source(session, tenant, organization, 2, "commercial_adjustment", return_doc)
        reversal_source = _source(session, tenant, organization, 3, "financial_event_reversal", reversal_doc)
        receivable_source = _source(session, tenant, organization, 4, "financial_obligation_adjustment", receivable_doc)
        payable_source = _source(session, tenant, organization, 5, "financial_obligation_adjustment", payable_doc)
        revenue_source = _source(session, tenant, organization, 6, "commercial_transaction_line", _document("correction_note", 6))
        expense_source = _source(session, tenant, organization, 7, "expense_transaction", _document("correction_note", 7))

        revenue = _original_event(session, tenant, organization, revenue_source, 1, "COMMERCIAL_REVENUE_RECOGNIZED", "40", "recognition", "commercial_recognition", {"revenue_nature": {"code": "service"}})
        expense = _original_event(session, tenant, organization, expense_source, 2, "EXPENSE_RECOGNIZED", "15", "recognition", "expense_accrual", {"expense_nature": {"code": "operations"}})
        refund_command = RecognizeRefundCommand(_context(tenant, organization, refund_source, 1, "30", refund_doc), incoming.public_id, outgoing.public_id, "customer_request")
        refund_result = TransactionalCorrectionLifecycleEngine.recognize_refund(session, refund_command)
        if refund_result.replayed or not TransactionalCorrectionLifecycleEngine.recognize_refund(session, refund_command).replayed: raise RuntimeError("refund replay failed")
        revenue_event = revenue.financial_event_result.event; expense_event = expense.financial_event_result.event
        return_result = TransactionalCorrectionLifecycleEngine.recognize_return(session, RecognizeCommercialReturnCommand(_context(tenant, organization, return_source, 2, "10", return_doc), revenue_event.public_id, "goods_returned"))
        reverse_result = TransactionalCorrectionLifecycleEngine.reverse_fact(session, ReverseFinancialFactCommand(_context(tenant, organization, reversal_source, 3, "15", reversal_doc), expense_event.public_id, "duplicate"))
        if return_result.financial_event_result.event.original_event_id != revenue_event.id or reverse_result.financial_event_result.event.original_event_id != expense_event.id: raise RuntimeError("correction original link missing")

        obligations = []
        for number, amount, obligation_type, role, source, document in ((1, "12", "trade_receivable", "receivable", receivable_source, receivable_doc), (2, "8", "expense_payable", "payable", payable_source, payable_doc)):
            created = TransactionalObligationEngine.create(session, _obligation(tenant, organization, number, amount, obligation_type))
            transition = TransitionObligationCommand(tenant, created.obligation.public_id, "written_off", 1, "approved_loss", "m54.writeoff.transition", f"writeoff-{number}", actor_service="m54.verifier")
            result = TransactionalCorrectionLifecycleEngine.write_off(session, WriteOffObligationCommand(_context(tenant, organization, source, 3 + number, amount, document), created.obligation.public_id, role, "approved_loss", transition))
            if result.transitioned_obligation.obligation.obligation_state != "written_off": raise RuntimeError("write-off did not transition obligation")
            obligations.append(result)

        chargeback_payload = {"document_type": "chargeback_notice", "document_number": "M54-CB-1", "provider": "test"}
        chargeback = CreateProviderSettlementComponentCommand(UUID("54000000-0000-0000-0008-000000000001"), tenant, organization, incoming.public_id, provider, "chargeback_loss", "chargeback_loss", "5", "XAF", "m54-chargeback-1", date(2026, 8, 10), chargeback_payload, BASE + timedelta(hours=1), date(2026, 8, 10), 1, CORRELATION, "m54.verifier", "chargeback", "m54.chargeback", "chargeback", actor_service="m54.verifier")
        chargeback_doc = CorrectionDocumentReference("chargeback_notice", "M54-CB-1", chargeback.evidence_hash)
        if TransactionalCorrectionLifecycleEngine.recognize_chargeback(session, RecognizeChargebackCommand(chargeback, chargeback_doc)).replayed: raise RuntimeError("first chargeback replayed")

        for action, expected in (("cancel", False), ("void", False), ("reverse", True)):
            result = LifecycleDispositionService.classify(ClassifyLifecycleDispositionCommand(action, action == "reverse", False, False))
            if result.creates_financial_event != expected: raise RuntimeError("disposition semantics differ")
        try: LifecycleDispositionService.classify(ClassifyLifecycleDispositionCommand("cancel", True, False, False))
        except CorrectionLifecycleError: pass
        else: raise RuntimeError("posted truth was cancellable")

        try: TransactionalCorrectionLifecycleEngine.recognize_refund(session, replace(refund_command, context=replace(refund_command.context, event_public_id=UUID(int=999), amount=Decimal("71"))))
        except CorrectionLifecycleError: pass
        else: raise RuntimeError("refund capacity exceeded original")
        try: TransactionalCorrectionLifecycleEngine.recognize_return(session, replace(RecognizeCommercialReturnCommand(_context(tenant, organization, return_source, 9, "1", return_doc), revenue_event.public_id, "probe"), context=replace(_context(tenant, organization, return_source, 9, "1", return_doc), tenant_id=tenant + 1)))
        except CorrectionLifecycleError: pass
        else: raise RuntimeError("cross-tenant correction accepted")

        states = session.execute(text("SELECT obligation_state,count(*) FROM financial_obligations GROUP BY obligation_state")).all()
        if dict(states).get("written_off") != 2: raise RuntimeError(f"write-off states differ={states}")
        if session.execute(text("""SELECT count(*) FROM journal_entries je WHERE je.entry_state<>'posted' OR EXISTS (
            SELECT 1 FROM journal_lines jl WHERE jl.tenant_id=je.tenant_id AND jl.journal_entry_id=je.id GROUP BY jl.tenant_id,jl.journal_entry_id
            HAVING sum(jl.transaction_debit_amount)<>sum(jl.transaction_credit_amount) OR sum(jl.base_debit_amount)<>sum(jl.base_credit_amount))""")).scalar_one(): raise RuntimeError("unbalanced correction journal")


def _run():
    _development_verify(); _create(); engine = None
    try:
        with _selected(TEST_DATABASE_NAME): alembic_command.upgrade(Config(str(ROOT / "alembic.ini")), TARGET_REVISION)
        engine = _engine(TEST_DATABASE_NAME); _exercise(engine); engine.dispose(); engine = None; _drop(TEST_DATABASE_NAME); _development_verify()
    except Exception:
        if engine is not None: engine.dispose()
        print(f"M5.4 verification failed; retained disposable database={TEST_DATABASE_NAME}"); raise
    print("m54_correction_lifecycles=PASS database=xbos_track_b_m54_corrections_test disposition=PASS refunds=PASS reversals=PASS chargebacks=PASS writeoffs=PASS documents=PASS tenant_scope=PASS replay=PASS capacity=PASS posting=PASS canonical_head_unchanged=PASS dropped=true")


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
