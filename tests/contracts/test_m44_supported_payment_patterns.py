from __future__ import annotations
import json
from datetime import date,datetime,timezone
from pathlib import Path
from uuid import UUID
import pytest
from core.domain.finance.payment_tender_contract import CreatePaymentTenderCommand,TransitionPaymentTenderCommand,PaymentTenderValidationError,CONTRACT_CODE
from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_settlement_contract import CreatePaymentSettlementCommand
from core.persistence.m44_payment_patterns import *
ROOT=Path(__file__).resolve().parents[2];BASE=datetime(2026,8,9,16,tzinfo=timezone.utc)
def tender(**changes):
    values=dict(public_id=UUID(int=1),tenant_id=1,organization_unit_id=2,payment_intent_public_id=UUID(int=2),tender_number=1,tender_amount="40",currency_code="XAF",payment_method_code="cash",occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=3),actor_service="tests",source_component="tests",source_record_id="tender",idempotency_scope="m44.tender",idempotency_key="one");values.update(changes);return CreatePaymentTenderCommand(**values)
def transition(**changes):
    values=dict(tenant_id=1,organization_unit_id=2,payment_tender_public_id=UUID(int=1),expected_row_version=1,target_state="succeeded",reason_code="completed",evidence_payload={"ok":True},occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=3),actor_service="tests",source_component="tests",source_record_id="transition",idempotency_scope="m44.transition",idempotency_key="one");values.update(changes);return TransitionPaymentTenderCommand(**values)
def test_contract_identity_and_fingerprint():assert CONTRACT_CODE=="XBOS_M44_SUPPORTED_PAYMENT_PATTERNS" and tender().request_fingerprint==tender().request_fingerprint
def test_tender_normalization():
    command=tender(payment_method_code=" CASH ",currency_code=" xaf ");assert command.payment_method_code=="cash" and command.currency_code=="XAF"
@pytest.mark.parametrize("changes,code",[({"tender_number":0},"invalid_tender_number"),({"payment_method_code":"Bad code"},"invalid_payment_method"),({"tenant_id":0},"invalid_scope"),({"actor_service":""},"actor_required"),({"instrument_reference":"x"*256},"instrument_reference_too_long")])
def test_invalid_tender(changes,code):
    with pytest.raises(PaymentTenderValidationError) as error:tender(**changes)
    assert error.value.code==code
@pytest.mark.parametrize("changes,code",[({"expected_row_version":0},"invalid_expected_version"),({"target_state":"pending"},"invalid_tender_state"),({"reason_code":"Bad reason"},"invalid_reason_code"),({"evidence_payload":{}},"tender_evidence_required"),({"target_state":"failed","evidence_payload":{"x":1}},"failure_code_required"),({"failure_code":"wrong"},"unexpected_failure_code")])
def test_invalid_transition(changes,code):
    with pytest.raises(PaymentTenderValidationError) as error:transition(**changes)
    assert error.value.code==code
def test_failed_transition_preserves_failure():assert transition(target_state="failed",failure_code="provider_failed").failure_code=="provider_failed"
def test_attempt_contract_accepts_tender_binding():
    c=CreatePaymentAttemptCommand(public_id=UUID(int=10),tenant_id=1,organization_unit_id=2,payment_intent_public_id=UUID(int=2),payment_tender_public_id=UUID(int=1),attempted_amount="40",currency_code="XAF",payment_method_code="mobile_money",payment_rail_code="mtn_momo",orchestrator_code="xbos_direct",occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=3),actor_service="tests",source_component="tests",source_record_id="attempt",idempotency_scope="m44.attempt",idempotency_key="one")
    assert c.canonical_payload()["payment_tender_public_id"]==str(UUID(int=1))
def test_settlement_contract_accepts_tender_binding():
    c=CreatePaymentSettlementCommand(public_id=UUID(int=20),tenant_id=1,organization_unit_id=2,payment_intent_public_id=UUID(int=2),payment_tender_public_id=UUID(int=1),operational_account_public_id=UUID(int=4),settlement_direction="incoming",gross_amount="40",fee_amount="0",net_amount="40",currency_code="XAF",payment_method_code="cash",payment_rail_code="cash",value_date=date(2026,8,9),occurred_at=BASE,business_date=date(2026,8,9),calendar_policy_version=1,correlation_id=UUID(int=3),actor_service="tests",source_component="tests",source_record_id="settlement",idempotency_scope="m44.settlement",idempotency_key="one")
    assert c.canonical_payload()["payment_tender_public_id"]==str(UUID(int=1))
def test_attempt_repository_preserves_m42_marker_and_uses_m44_binding():
    source=(ROOT/"core/domain/finance/payment_attempt_repository.py").read_text()
    assert '"NULL, :provider_account_id"' in source
    assert ":payment_tender_id, :provider_account_id" in source
def test_lineage_and_inventory():assert PARENT_REVISION=="m43_payment_settlements_013" and TARGET_REVISION=="m44_payment_patterns_014" and len(M44_TRIGGERS)==8
def test_contract_catalogues_every_approved_pattern():
    data=json.loads((ROOT/"contracts/finance/v1/m44_supported_payment_patterns.json").read_text());patterns=data["supported_patterns"]
    for key in ("cash","mobile_money","bank","card","mixed_split_tender","standalone_payment","payment_link","delayed_settlement"):assert key in patterns
@pytest.mark.parametrize("needle",["tender method is not allowed by intent","intent maximum tender count exceeded","tender composition exceeds intent amount","mixed-tender attempt requires explicit tender authority","settlement exceeds tender capacity","immutable tender identity or amount cannot be updated"])
def test_database_guards(needle):assert needle in (ROOT/"alembic_neutral/sql/m44_payment_patterns_up.sql").read_text()
def test_down_restores_parent_attempt_guard():
    sql=(ROOT/"alembic_neutral/sql/m44_payment_patterns_down.sql").read_text();assert "DROP TABLE IF EXISTS public.payment_tender_transitions" in sql and "retry must follow a terminal unsuccessful attempt for the same intent" in sql
def test_down_drops_settlement_triggers_before_their_functions():
    sql=(ROOT/"alembic_neutral/sql/m44_payment_patterns_down.sql").read_text()
    assert sql.index("DROP TRIGGER IF EXISTS trg_payment_pattern_settlement_guard") < sql.index("DROP FUNCTION IF EXISTS public.xbos_guard_payment_pattern_settlement_update")
    assert sql.index("DROP TRIGGER IF EXISTS trg_payment_pattern_settlement_validate") < sql.index("DROP FUNCTION IF EXISTS public.xbos_validate_payment_pattern_settlement")
def test_verifier_covers_patterns():
    source=(ROOT/"scripts/verify_m44_payment_patterns.py").read_text()
    for token in ("cash=PASS","mtn=PASS","orange=PASS","bank=PASS","card=PASS","split_tender=PASS","payment_link=PASS","delayed_settlement=PASS"):assert token in source
def test_no_xafpay_adapter_or_public_route():
    names={p.name.lower() for p in ROOT.rglob("*m44*") if p.is_file()};assert not any("xafpay" in n or "route" in n for n in names)
