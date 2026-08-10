from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.allocation_contract import CreateValueSourceCommand
from core.domain.finance.obligation_contract import CreateObligationCommand, ObligationLineCommand
from core.domain.finance.payable_balance_service import SupplierPayableBalanceService
from core.domain.finance.payable_contract import (
    ApplyDisbursementCommand,
    DISBURSEMENT_SOURCE_TYPE,
    DisbursePayablesCommand,
    OpenPayableCommand,
    PAYABLE_TYPES,
    PAYEE_METADATA_KEY,
    PayableLifecycleError,
)
from core.domain.finance.payable_engine import TransactionalPayableLifecycleEngine
from core.persistence.m51_payable_lifecycle import (
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
CONTRACT = json.loads((ROOT / "contracts/finance/v1/m51_payables_and_governed_disbursements.json").read_text())
STAMP = datetime(2026, 8, 10, 10, tzinfo=timezone.utc)
PAYER = UUID("51000000-0000-0000-0000-000000000010")
SUPPLIER = UUID("51000000-0000-0000-0000-000000000011")
OTHER_SUPPLIER = UUID("51000000-0000-0000-0000-000000000012")
PAYABLE = UUID("51000000-0000-0000-0000-000000000101")
SETTLEMENT = UUID("51000000-0000-0000-0000-000000000201")
SOURCE = UUID("51000000-0000-0000-0000-000000000301")
ALLOCATION = UUID("51000000-0000-0000-0000-000000000401")


def _obligation(kind="trade_payable", creditor=SUPPLIER):
    return CreateObligationCommand(
        public_id=PAYABLE, tenant_id=51, organization_unit_id=52,
        debtor_party_id=PAYER, creditor_party_id=creditor, obligation_type=kind,
        original_amount=Decimal("100"), currency_code="XAF", due_at=STAMP,
        occurred_at=STAMP, business_date=STAMP.date(), calendar_policy_version=1,
        correlation_id=UUID(int=510), actor_service="m51.test", source_component="m51.test",
        source_record_id="p1", idempotency_scope="m51.payable", idempotency_key="p1",
        lines=(ObligationLineCommand(1, "principal", "Payable", 1, 100, 100, "p1-line"),),
    )


def _source(kind="disbursement", settlement=SETTLEMENT, metadata=None):
    return CreateValueSourceCommand(
        public_id=SOURCE, tenant_id=51, organization_unit_id=52, owner_party_id=PAYER,
        source_type=kind, source_amount=Decimal("100"), currency_code="XAF",
        payment_settlement_public_id=settlement, occurred_at=STAMP, business_date=STAMP.date(),
        calendar_policy_version=1, correlation_id=UUID(int=511), actor_service="m51.test",
        source_component="m51.test", source_record_id="d1", idempotency_scope="m51.disbursement",
        idempotency_key="d1", metadata=metadata if metadata is not None else {PAYEE_METADATA_KEY: str(SUPPLIER)},
    )


def _application(obligation=PAYABLE):
    return ApplyUnappliedValueCommand(
        tenant_id=51, value_source_public_id=SOURCE, occurred_at=STAMP,
        business_date=STAMP.date(), calendar_policy_version=1, correlation_id=UUID(int=512),
        source_component="m51.test", idempotency_scope="m51.application", actor_service="m51.test",
        applications=(ValueApplicationInstruction(ALLOCATION, obligation, "a1", "a1", Decimal("100")),),
    )


def _command(source=None, application=None):
    return DisbursePayablesCommand(ReceiveAndApplyValueCommand(source or _source(), application or _application()))


def test_contract_identity_and_checkpoint():
    assert CONTRACT["contract_code"] == "XBOS_M51_PAYABLES_AND_GOVERNED_DISBURSEMENTS"
    assert CONTRACT["milestone"] == "M5.1"
    assert CONTRACT["source_checkpoint"] == {
        "branch": "track-b/m5-complete-financial-lifecycles", "parent_commit": "9f3f2e9"
    }


def test_grouped_scope_preserves_original_m5_lines():
    assert CONTRACT["scope_map"] == {
        "original_m5_3": "payable lifecycle", "original_m5_4": "governed disbursements"
    }


def test_schema_neutral_boundary_keeps_m4_head():
    assert SCHEMA_CHANGE is False and CONTRACT["schema_change"] is False
    assert PARENT_REVISION == TARGET_REVISION == CONTRACT["canonical_head"] == "m46_provider_financials_015"
    assert not list((ROOT / "alembic_neutral/versions").glob("m51_*.py"))


def test_existing_facts_remain_authoritative():
    authority = CONTRACT["authority"]
    assert authority["payable_fact"] == "financial_obligations"
    assert authority["outgoing_settlement_fact"] == "payment_settlements"
    assert authority["disbursement_value_fact"] == "value_sources"
    assert authority["new_parallel_ledger"] is False


def test_approved_payable_types_are_explicit():
    assert PAYABLE_TYPES == {"trade_payable", "supplier_payable", "expense_payable"}


@pytest.mark.parametrize("kind", sorted(PAYABLE_TYPES))
def test_open_payable_accepts_approved_types(kind):
    assert OpenPayableCommand(_obligation(kind)).obligation.obligation_type == kind


def test_open_payable_rejects_receivable():
    with pytest.raises(PayableLifecycleError) as caught:
        OpenPayableCommand(_obligation("trade_receivable"))
    assert caught.value.code == "invalid_payable_type"


def test_disbursement_source_type_is_frozen():
    assert DISBURSEMENT_SOURCE_TYPE == "disbursement"
    with pytest.raises(PayableLifecycleError) as caught:
        _command(_source("payment"))
    assert caught.value.code == "invalid_disbursement_type"


def test_disbursement_requires_settlement_identity():
    with pytest.raises(PayableLifecycleError) as caught:
        _command(_source(settlement=None))
    assert caught.value.code == "outgoing_settlement_required"


@pytest.mark.parametrize("metadata", [{}, {PAYEE_METADATA_KEY: "bad"}, {PAYEE_METADATA_KEY: str(UUID(int=0))}])
def test_disbursement_requires_valid_non_nil_payee(metadata):
    with pytest.raises(PayableLifecycleError) as caught:
        _command(_source(metadata=metadata))
    assert caught.value.code == "payee_identity_required"


def test_disbursement_requires_application_targets():
    with pytest.raises(PayableLifecycleError) as caught:
        DisbursePayablesCommand(ReceiveAndApplyValueCommand(_source(), None))
    assert caught.value.code == "disbursement_application_required"


def test_payee_property_is_normalized_uuid():
    assert _command().payee_party_id == SUPPLIER


class FakeNested:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeSession:
    def begin_nested(self): return FakeNested()


class FakeObligations:
    @staticmethod
    def create(session, command): return session, command


class FakeValues:
    @staticmethod
    def receive(session, command): return session, command
    @staticmethod
    def apply_existing(session, command): return session, command


class FakeRepository:
    settlement = {
        "settlement_direction": "outgoing", "settlement_state": "confirmed",
        "organization_unit_id": 52, "currency_code": "XAF",
        "gross_amount": Decimal("100"), "reversed_amount": Decimal("0"),
    }
    payable = {"debtor_party_id": PAYER, "creditor_party_id": SUPPLIER, "currency_code": "XAF"}
    disbursement = {
        "owner_party_id": PAYER, "payee_party_id": str(SUPPLIER), "currency_code": "XAF"
    }

    @classmethod
    def settlement_authority(cls, *args, **kwargs): return cls.settlement
    @classmethod
    def payable_authority(cls, *args, **kwargs): return cls.payable
    @classmethod
    def disbursement_authority(cls, *args, **kwargs): return cls.disbursement


class FakeEngine(TransactionalPayableLifecycleEngine):
    obligations = FakeObligations
    values = FakeValues
    repository = FakeRepository


def test_open_delegates_to_frozen_obligation_engine():
    session = object(); command = OpenPayableCommand(_obligation())
    assert FakeEngine.open(session, command) == (session, command.obligation)


def test_disbursement_delegates_after_authority_checks():
    session = FakeSession(); command = _command()
    assert FakeEngine.disburse(session, command) == (session, command.disbursement)


@pytest.mark.parametrize("field,value,code", [
    ("settlement_direction", "incoming", "confirmed_outgoing_settlement_required"),
    ("settlement_state", "pending", "confirmed_outgoing_settlement_required"),
    ("organization_unit_id", 99, "organization_mismatch"),
    ("currency_code", "USD", "currency_mismatch"),
    ("gross_amount", Decimal("99"), "settlement_amount_mismatch"),
])
def test_disbursement_rejects_invalid_settlement_authority(field, value, code):
    original = FakeRepository.settlement
    FakeRepository.settlement = {**original, field: value}
    try:
        with pytest.raises(PayableLifecycleError) as caught:
            FakeEngine.disburse(FakeSession(), _command())
        assert caught.value.code == code
    finally:
        FakeRepository.settlement = original


@pytest.mark.parametrize("field,value,code", [
    ("debtor_party_id", UUID(int=991), "payer_mismatch"),
    ("creditor_party_id", OTHER_SUPPLIER, "payee_mismatch"),
    ("currency_code", "USD", "currency_mismatch"),
])
def test_disbursement_rejects_payable_scope_mismatch(field, value, code):
    original = FakeRepository.payable
    FakeRepository.payable = {**original, field: value}
    try:
        with pytest.raises(PayableLifecycleError) as caught:
            FakeEngine.disburse(FakeSession(), _command())
        assert caught.value.code == code
    finally:
        FakeRepository.payable = original


def test_apply_existing_uses_immutable_payer_and_payee_identity():
    session = FakeSession(); command = ApplyDisbursementCommand(_application())
    assert FakeEngine.apply_existing(session, command) == (session, command.application)


def test_supplier_position_service_is_derived():
    class Repository:
        @staticmethod
        def supplier_position(*args, **kwargs): return Decimal("75")
    class Service(SupplierPayableBalanceService): repository = Repository
    result = Service.get(object(), tenant_id=51, supplier_party_id=SUPPLIER, currency_code="xaf")
    assert result.outstanding_amount == Decimal("75") and result.currency_code == "XAF"


def test_repository_reads_are_tenant_scoped_and_lock_named_authority_rows():
    source = (ROOT / "core/domain/finance/payable_repository.py").read_text()
    assert source.count("tenant_id=:tenant_id") >= 6
    assert "FOR UPDATE OF o" in source and "FOR UPDATE OF ps" in source and "FOR UPDATE OF vs" in source


def test_payee_identity_is_read_from_immutable_value_source_metadata():
    source = (ROOT / "core/domain/finance/payable_repository.py").read_text()
    assert "metadata->>" in source and "payee_party_id" in source


def test_engine_uses_fixed_target_order_and_does_not_commit():
    source = (ROOT / "core/domain/finance/payable_engine.py").read_text()
    assert "sorted(application.applications" in source
    assert ".commit(" not in source and ".rollback(" not in source


def test_development_and_disposable_names_are_frozen():
    assert DEVELOPMENT_DATABASE_NAME == "xbos_track_b_dev"
    assert TEST_DATABASE_NAME == "xbos_track_b_m51_payables_test"


def test_single_gate_and_forbidden_surface_are_explicit():
    assert CONTRACT["acceptance"]["mode"] == "single_fail_fast_gate"
    assert {"unsettled_disbursement", "cross_supplier_disbursement", "currency_conversion"} <= set(CONTRACT["forbidden"])


def test_acceptance_verifier_has_persistent_fail_fast_markers():
    source = (ROOT / "scripts/verify_m51_payables.py").read_text()
    for token in ("create-and-verify", "M5.1 verification failed", "dropped=true", "_development_verify()"):
        assert token in source


def test_verifier_covers_full_grouped_scope():
    source = (ROOT / "scripts/verify_m51_payables.py").read_text()
    for marker in (
        "partial_disbursement=PASS", "later_disbursement=PASS", "batch=PASS",
        "pending_failed_rejected=PASS", "payer_payee=PASS", "tenant_scope=PASS",
        "capacity=PASS", "direct_sql=PASS", "rollback=PASS", "dropped=true",
    ):
        assert marker in source
