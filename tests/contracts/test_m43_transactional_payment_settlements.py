from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.payment_settlement_contract import (
    CONTRACT_CODE, CreatePaymentSettlementCommand, PaymentSettlementValidationError,
    ReversePaymentSettlementCommand, TransitionPaymentSettlementCommand,
)
from core.persistence.m43_payment_settlements import (
    M43_COLUMNS, M43_TABLES, M43_TRIGGERS, PARENT_REVISION, TARGET_REVISION,
)

ROOT=Path(__file__).resolve().parents[2]
BASE=datetime(2026,8,9,14,tzinfo=timezone.utc)


def create(**changes):
    values=dict(public_id=UUID("43000000-0000-0000-0000-000000000001"),tenant_id=1,organization_unit_id=2,
        payment_intent_public_id=UUID("43000000-0000-0000-0000-000000000002"),
        payment_attempt_public_id=UUID("43000000-0000-0000-0000-000000000003"),
        operational_account_public_id=UUID("43000000-0000-0000-0000-000000000004"),settlement_direction="incoming",
        gross_amount="100",fee_amount="2",net_amount="98",currency_code="XAF",payment_method_code="mobile_money",
        payment_rail_code="mtn_momo",external_settlement_reference="provider-1",value_date=date(2026,8,10),
        occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,
        correlation_id=UUID("43000000-0000-0000-0000-000000000005"),actor_service="tests",
        source_component="tests",source_record_id="settlement-1",idempotency_scope="m43.create",idempotency_key="one")
    values.update(changes); return CreatePaymentSettlementCommand(**values)


def transition(**changes):
    values=dict(tenant_id=1,organization_unit_id=2,payment_settlement_public_id=UUID("43000000-0000-0000-0000-000000000001"),
        expected_row_version=1,target_state="confirmed",finality_status="final",availability_state="available",
        reason_code="provider_confirmed",external_settlement_reference="provider-1",evidence_payload={"status":"success"},
        occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,
        correlation_id=UUID("43000000-0000-0000-0000-000000000005"),actor_service="tests",
        source_component="tests",source_record_id="transition-1",idempotency_scope="m43.transition",idempotency_key="one")
    values.update(changes); return TransitionPaymentSettlementCommand(**values)


def reversal(**changes):
    values=dict(public_id=UUID("43000000-0000-0000-0000-000000000006"),tenant_id=1,organization_unit_id=2,
        payment_settlement_public_id=UUID("43000000-0000-0000-0000-000000000001"),reversal_amount="25",currency_code="XAF",
        reason_code="provider_reversal",occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,
        correlation_id=UUID("43000000-0000-0000-0000-000000000005"),actor_service="tests",
        source_component="tests",source_record_id="reversal-1",idempotency_scope="m43.reversal",idempotency_key="one")
    values.update(changes); return ReversePaymentSettlementCommand(**values)


def test_contract_identity_and_fingerprint_are_deterministic():
    command=create(); assert CONTRACT_CODE=="XBOS_M43_TRANSACTIONAL_PAYMENT_SETTLEMENTS"
    assert command.request_fingerprint==create().request_fingerprint and len(command.request_fingerprint)==64


def test_money_and_codes_are_normalized():
    command=create(currency_code=" xaf ",payment_method_code=" Mobile_Money ")
    assert command.currency_code=="XAF" and command.payment_method_code=="mobile_money" and command.net_amount==Decimal("98.00000000")


@pytest.mark.parametrize("changes,code",[
    ({"settlement_direction":"sideways"},"invalid_settlement_direction"),
    ({"gross_amount":"0"},"invalid_settlement_amount"),
    ({"fee_amount":"-1"},"invalid_settlement_amount"),
    ({"net_amount":"97"},"settlement_amount_mismatch"),
    ({"currency_code":"XA"},"invalid_currency"),
    ({"payment_method_code":"Bad code"},"invalid_settlement_routing"),
    ({"payment_rail_code":""},"invalid_settlement_routing"),
    ({"external_settlement_reference":"   "},"empty_provider_identity"),
    ({"tenant_id":0},"invalid_scope"),
    ({"actor_service":""},"actor_required"),
])
def test_invalid_create_commands(changes,code):
    with pytest.raises(PaymentSettlementValidationError) as error: create(**changes)
    assert error.value.code==code


def test_value_date_and_occurrence_are_distinct_contract_fields():
    payload=create().canonical_payload(); assert payload["value_date"]=="2026-08-10" and payload["occurred_at"].startswith("2026-08-09")


@pytest.mark.parametrize("changes,code",[
    ({"expected_row_version":0},"invalid_expected_version"),
    ({"target_state":"reversed"},"invalid_settlement_target_state"),
    ({"reason_code":"Bad reason"},"invalid_reason_code"),
    ({"evidence_payload":{}},"settlement_evidence_required"),
    ({"target_state":"confirmed","finality_status":"provisional"},"confirmation_not_final"),
    ({"target_state":"failed","finality_status":"rejected","availability_state":"unavailable"},"failure_code_required"),
    ({"failure_code":"wrong"},"unexpected_failure_code"),
])
def test_invalid_transition_commands(changes,code):
    with pytest.raises(PaymentSettlementValidationError) as error: transition(**changes)
    assert error.value.code==code


def test_valid_failed_transition_preserves_failure_semantics():
    command=transition(target_state="failed",finality_status="rejected",availability_state="unavailable",failure_code="provider_rejected")
    assert command.failure_code=="provider_rejected"


@pytest.mark.parametrize("changes,code",[
    ({"reversal_amount":"0"},"invalid_reversal_amount"),
    ({"reversal_amount":"-1"},"invalid_reversal_amount"),
    ({"currency_code":"xx"},"invalid_reversal_identity"),
    ({"reason_code":"Bad reason"},"invalid_reversal_identity"),
])
def test_invalid_reversal_commands(changes,code):
    with pytest.raises(PaymentSettlementValidationError) as error: reversal(**changes)
    assert error.value.code==code


def test_reversal_fingerprint_changes_with_amount():
    assert reversal().request_fingerprint!=reversal(reversal_amount="26").request_fingerprint


def test_migration_lineage_and_inventory():
    assert PARENT_REVISION=="m42_payment_attempts_012" and TARGET_REVISION=="m43_payment_settlements_013"
    assert M43_TABLES==("payment_settlement_transitions",) and len(M43_COLUMNS)==5 and len(M43_TRIGGERS)==8


def test_contract_json_matches_head_and_scope():
    data=json.loads((ROOT/"contracts/finance/v1/m43_transactional_payment_settlements.json").read_text())
    assert data["canonical_head"]==TARGET_REVISION and data["entities"]["settlement_transition"]["append_only"] is True


@pytest.mark.parametrize("needle",[
    "settlement requires matching successful attempt authority",
    "confirmed external settlement requires provider transaction identity",
    "settlement reversal exceeds original gross amount",
    "immutable settlement identity or monetary truth cannot be updated",
    "payment_settlement_transitions",
])
def test_database_guards_are_present(needle):
    sql=(ROOT/"alembic_neutral/sql/m43_payment_settlements_up.sql").read_text(); assert needle in sql


def test_down_migration_removes_every_m43_object():
    sql=(ROOT/"alembic_neutral/sql/m43_payment_settlements_down.sql").read_text()
    assert "DROP TABLE IF EXISTS public.payment_settlement_transitions" in sql
    for column in M43_COLUMNS: assert f"DROP COLUMN IF EXISTS {column}" in sql


def test_verifier_covers_required_acceptance_dimensions():
    source=(ROOT/"scripts/verify_m43_payment_settlements.py").read_text()
    for token in ("inbound=PASS","outbound=PASS","provider_identity=PASS","value_date=PASS","reversal_capacity=PASS","upgrade_downgrade_upgrade=PASS"):
        assert token in source


def test_m43_has_no_public_route_or_provider_adapter():
    paths={path.name for path in ROOT.rglob("*m43*") if path.is_file()}
    assert not any("route" in name or "xafpay" in name for name in paths)
