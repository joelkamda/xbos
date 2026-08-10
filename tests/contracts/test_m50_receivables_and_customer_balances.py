from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.domain.finance.aging_contract import AsOfAgingQuery
from core.domain.finance.allocation_contract import CreateValueSourceCommand
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.receivable_balance_service import CustomerReceivableBalanceService
from core.domain.finance.receivable_contract import (
    AgeReceivablesCommand,
    ApplyCustomerValueCommand,
    CUSTOMER_VALUE_TYPES,
    IssueCustomerValueCommand,
    OpenReceivableCommand,
    RECEIVABLE_TYPES,
    ReceiveReceivablePaymentCommand,
    ReceivableLifecycleError,
)
from core.domain.finance.receivable_engine import TransactionalReceivableLifecycleEngine
from core.persistence.m50_receivable_lifecycle import (
    DEVELOPMENT_DATABASE_NAME,
    PARENT_REVISION,
    SCHEMA_CHANGE,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
)
from core.domain.finance.value_application_contract import (
    ApplyUnappliedValueCommand,
    ReceiveAndApplyValueCommand,
    ValueApplicationInstruction,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts/finance/v1/m50_receivables_and_customer_balances.json").read_text())
STAMP = datetime(2026, 8, 10, 10, tzinfo=timezone.utc)
CUSTOMER = UUID("50000000-0000-0000-0000-000000000010")
MERCHANT = UUID("50000000-0000-0000-0000-000000000011")
RECEIVABLE = UUID("50000000-0000-0000-0000-000000000101")
SOURCE = UUID("50000000-0000-0000-0000-000000000201")
ALLOCATION = UUID("50000000-0000-0000-0000-000000000301")


def _obligation(kind="trade_receivable", debtor=CUSTOMER):
    return CreateObligationCommand(
        public_id=RECEIVABLE, tenant_id=50, organization_unit_id=51,
        debtor_party_id=debtor, creditor_party_id=MERCHANT, obligation_type=kind,
        original_amount=Decimal("100"), currency_code="XAF", due_at=STAMP,
        occurred_at=STAMP, business_date=STAMP.date(), calendar_policy_version=1,
        correlation_id=UUID(int=500), actor_service="m50.test", source_component="m50.test",
        source_record_id="r1", idempotency_scope="m50.receivable", idempotency_key="r1",
        lines=(ObligationLineCommand(1, "principal", "Receivable", 1, 100, 100, "r1-line"),),
    )


def _source(kind="payment", owner=CUSTOMER, settlement=None):
    return CreateValueSourceCommand(
        public_id=SOURCE, tenant_id=50, organization_unit_id=51, owner_party_id=owner,
        source_type=kind, source_amount=Decimal("120"), currency_code="XAF",
        payment_settlement_public_id=settlement, occurred_at=STAMP, business_date=STAMP.date(),
        calendar_policy_version=1, correlation_id=UUID(int=501), actor_service="m50.test",
        source_component="m50.test", source_record_id=f"s-{kind}",
        idempotency_scope="m50.value", idempotency_key=f"s-{kind}",
    )


def _application(source=SOURCE, obligation=RECEIVABLE):
    return ApplyUnappliedValueCommand(
        tenant_id=50, value_source_public_id=source, occurred_at=STAMP,
        business_date=STAMP.date(), calendar_policy_version=1, correlation_id=UUID(int=502),
        source_component="m50.test", idempotency_scope="m50.apply", actor_service="m50.test",
        applications=(ValueApplicationInstruction(ALLOCATION, obligation, "a1", "a1", Decimal("100")),),
    )


def test_contract_identity_and_source_checkpoint():
    assert CONTRACT["contract_code"] == "XBOS_M50_RECEIVABLES_AND_CUSTOMER_BALANCES"
    assert CONTRACT["milestone"] == "M5.0"
    assert CONTRACT["source_checkpoint"]["parent_commit"] == "0375f04"
    assert CONTRACT["source_checkpoint"]["branch"] == "track-b/m5-complete-financial-lifecycles"


def test_m50_is_schema_neutral_over_frozen_m4_head():
    assert SCHEMA_CHANGE is False and CONTRACT["schema_change"] is False
    assert PARENT_REVISION == TARGET_REVISION == CONTRACT["canonical_head"] == "m46_provider_financials_015"
    assert CONTRACT["migration"] is None
    assert not list((ROOT / "alembic_neutral/versions").glob("m50_*.py"))


def test_grouped_scope_preserves_every_approved_line_item():
    assert set(CONTRACT["scope_map"]) == {
        "original_m5_0", "original_m5_1", "original_m5_2", "original_m5_5",
        "original_m5_6", "interoperability",
    }


def test_existing_tables_remain_the_only_financial_authority():
    assert CONTRACT["authority"]["receivable_fact"] == "financial_obligations"
    assert CONTRACT["authority"]["customer_value_fact"] == "value_sources"
    assert CONTRACT["authority"]["application_fact"] == "payment_allocations"
    assert CONTRACT["authority"]["new_parallel_ledger"] is False


def test_approved_receivable_types_are_explicit():
    assert RECEIVABLE_TYPES == {"trade_receivable", "customer_receivable"}


def test_open_receivable_rejects_non_receivable_obligation():
    with pytest.raises(ReceivableLifecycleError) as caught:
        OpenReceivableCommand(_obligation("trade_payable"))
    assert caught.value.code == "invalid_receivable_type"


def test_open_receivable_accepts_both_approved_types():
    for kind in RECEIVABLE_TYPES:
        assert OpenReceivableCommand(_obligation(kind)).obligation.obligation_type == kind


def test_customer_value_types_are_explicit():
    assert CUSTOMER_VALUE_TYPES == {"customer_credit", "customer_deposit", "customer_advance"}


@pytest.mark.parametrize("kind", sorted(CUSTOMER_VALUE_TYPES))
def test_customer_value_issuance_accepts_each_approved_type(kind):
    assert IssueCustomerValueCommand(_source(kind)).value_source.source_type == kind


def test_customer_value_issuance_rejects_payment():
    with pytest.raises(ReceivableLifecycleError) as caught:
        IssueCustomerValueCommand(_source("payment"))
    assert caught.value.code == "invalid_customer_value_type"


def test_customer_value_cannot_impersonate_payment_settlement_evidence():
    with pytest.raises(ReceivableLifecycleError) as caught:
        IssueCustomerValueCommand(_source("customer_credit", settlement=UUID(int=600)))
    assert caught.value.code == "customer_value_settlement_forbidden"


def test_receivable_payment_requires_payment_source_type():
    command = ReceiveAndApplyValueCommand(_source("customer_deposit"), _application())
    with pytest.raises(ReceivableLifecycleError) as caught:
        ReceiveReceivablePaymentCommand(command)
    assert caught.value.code == "invalid_payment_source_type"


def test_receivable_payment_requires_application_target():
    with pytest.raises(ReceivableLifecycleError) as caught:
        ReceiveReceivablePaymentCommand(ReceiveAndApplyValueCommand(_source(), None))
    assert caught.value.code == "payment_application_required"


def test_receivable_payment_accepts_overpayment_capable_application():
    command = ReceiveReceivablePaymentCommand(ReceiveAndApplyValueCommand(_source(), _application()))
    assert command.receipt.value_source.source_amount == Decimal("120.00000000")


def test_age_command_reuses_deterministic_as_of_contract():
    command = AgeReceivablesCommand(AsOfAgingQuery(50, STAMP, date(2026, 8, 10)))
    assert command.query.as_of_business_date == date(2026, 8, 10)


class FakeObligations:
    @staticmethod
    def create(session, command):
        return (session, command)


class FakeValues:
    class allocation_engine:
        @staticmethod
        def create_value_source(session, command):
            return (session, command)

    @staticmethod
    def receive(session, command):
        return (session, command)

    @staticmethod
    def apply_existing(session, command):
        return (session, command)


class FakeNested:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeSession:
    def begin_nested(self): return FakeNested()


class FakeRepository:
    receivable = {"debtor_party_id": CUSTOMER, "currency_code": "XAF"}
    source = {"owner_party_id": CUSTOMER, "currency_code": "XAF", "source_type": "customer_credit"}

    @classmethod
    def receivable_authority(cls, *args, **kwargs): return cls.receivable

    @classmethod
    def customer_value_authority(cls, *args, **kwargs): return cls.source

    @staticmethod
    def is_receivable(*args, **kwargs): return True


class FakeEngine(TransactionalReceivableLifecycleEngine):
    obligations = FakeObligations
    values = FakeValues
    repository = FakeRepository


def test_open_delegates_to_frozen_obligation_engine():
    session = object(); command = OpenReceivableCommand(_obligation())
    assert FakeEngine.open(session, command) == (session, command.obligation)


def test_issue_customer_value_delegates_to_frozen_value_source_engine():
    session = object(); command = IssueCustomerValueCommand(_source("customer_credit"))
    assert FakeEngine.issue_customer_value(session, command) == (session, command.value_source)


def test_receive_payment_delegates_after_customer_and_currency_checks():
    session = FakeSession(); command = ReceiveReceivablePaymentCommand(ReceiveAndApplyValueCommand(_source(), _application()))
    assert FakeEngine.receive_payment(session, command) == (session, command.receipt)


def test_receive_payment_rejects_different_customer():
    original = FakeRepository.receivable
    FakeRepository.receivable = {**original, "debtor_party_id": UUID(int=999)}
    try:
        with pytest.raises(ReceivableLifecycleError) as caught:
            FakeEngine.receive_payment(FakeSession(), ReceiveReceivablePaymentCommand(ReceiveAndApplyValueCommand(_source(), _application())))
        assert caught.value.code == "customer_mismatch"
    finally:
        FakeRepository.receivable = original


def test_receive_payment_rejects_currency_mismatch():
    original = FakeRepository.receivable
    FakeRepository.receivable = {**original, "currency_code": "USD"}
    try:
        with pytest.raises(ReceivableLifecycleError) as caught:
            FakeEngine.receive_payment(FakeSession(), ReceiveReceivablePaymentCommand(ReceiveAndApplyValueCommand(_source(), _application())))
        assert caught.value.code == "currency_mismatch"
    finally:
        FakeRepository.receivable = original


def test_apply_customer_value_allows_governed_source_after_scope_checks():
    session = FakeSession(); command = ApplyCustomerValueCommand(_application())
    assert FakeEngine.apply_customer_value(session, command) == (session, command.application)


def test_apply_customer_value_requests_payment_residual_authority():
    source = (ROOT / "core/domain/finance/receivable_engine.py").read_text()
    assert "allow_payment_residual=True" in source


def test_balance_service_derives_net_customer_due():
    class Repository:
        @staticmethod
        def customer_position(*args, **kwargs): return Decimal("75"), Decimal("20")
    class Service(CustomerReceivableBalanceService): repository = Repository
    result = Service.get(object(), tenant_id=50, customer_party_id=CUSTOMER, currency_code="xaf")
    assert result.receivable_outstanding == Decimal("75")
    assert result.customer_value_available == Decimal("20")
    assert result.net_customer_due == Decimal("55")


def test_balance_repository_includes_unapplied_payment_residual():
    source = (ROOT / "core/domain/finance/receivable_repository.py").read_text()
    assert "('payment','customer_credit','customer_deposit','customer_advance')" in source


def test_balance_query_aggregates_each_authority_once():
    source = (ROOT / "core/domain/finance/receivable_repository.py").read_text()
    assert "obligation_applications AS" in source
    assert "source_applications AS" in source
    assert "GROUP BY pa.tenant_id,pa.obligation_id,pa.value_source_id" not in source


def test_aging_filters_non_receivables_without_raising():
    source = (ROOT / "core/domain/finance/receivable_engine.py").read_text()
    assert "repository.is_receivable" in source


def test_repository_queries_are_tenant_scoped():
    source = (ROOT / "core/domain/finance/receivable_repository.py").read_text()
    assert source.count("tenant_id=:tenant_id") >= 5
    assert "FOR UPDATE OF o" in source and "FOR UPDATE OF vs" in source


def test_orchestration_reuses_existing_authorities_without_committing():
    source = (ROOT / "core/domain/finance/receivable_engine.py").read_text()
    assert "TransactionalObligationEngine" in source
    assert "TransactionalValueApplicationEngine" in source
    assert "ObligationAgingService" in source
    assert ".commit(" not in source and ".rollback(" not in source


def test_development_and_disposable_database_names_are_frozen():
    assert DEVELOPMENT_DATABASE_NAME == "xbos_track_b_dev"
    assert TEST_DATABASE_NAME == "xbos_track_b_m50_receivables_test"


def test_single_gate_and_forbidden_surface_are_explicit():
    assert CONTRACT["acceptance"]["mode"] == "single_fail_fast_gate"
    assert {"public_api_route", "wnd_writer_switch", "outbox_dispatch", "currency_conversion"} <= set(CONTRACT["forbidden"])


def test_acceptance_runner_contains_fail_fast_markers():
    source = (ROOT / "XBOS_M5_0_RUN_ACCEPTANCE.cmd").read_text()
    assert "M50_SINGLE_GATE=PASS" in source
    assert "M50_SINGLE_GATE=FAIL" in source
    assert "python -m pytest -q" in source


def test_verifier_covers_grouped_capabilities_and_safe_drop():
    source = (ROOT / "scripts/verify_m50_receivables.py").read_text()
    for token in (
        "partial_payment=PASS", "later_repayment=PASS", "aging=PASS",
        "customer_credit=PASS", "deposit=PASS", "advance=PASS",
        "overpayment=PASS", "tenant_scope=PASS", "customer_scope=PASS",
        "capacity=PASS", "direct_sql=PASS", "dropped=true",
    ):
        assert token in source
    assert "refusing unapproved database" in source
