from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_xv12_adapter_is_additive_and_legacy_m45_untouched():
    assert (ROOT/'core/integrations/xafpay_v2/service.py').exists()
    legacy=(ROOT/'core/integrations/xafpay/adapter.py').read_text(encoding='utf-8')
    assert 'INITIATION_PATH = "/v1/payment-intents"' in legacy
    assert 'xafpay_v2' not in legacy


def test_xv12_signed_endpoint_has_exact_middleware_bypass():
    route='path == "/kernel/integrations/xafpay-v2/events"'
    for name in ('auth_middleware.py','tenant_middleware.py','branch_middleware.py'):
        source=(ROOT/'core/middleware'/name).read_text(encoding='utf-8')
        assert route in source
    kernel=(ROOT/'core/api/kernel_router.py').read_text(encoding='utf-8')
    assert 'xafpay_v2_router' in kernel
    assert 'prefix="/integrations/xafpay-v2"' in kernel


def test_xv12_gateway_never_supplies_xbos_scope_or_provider_authority():
    contract=(ROOT/'core/integrations/xafpay_v2/contract.py').read_text(encoding='utf-8')
    service=(ROOT/'core/integrations/xafpay_v2/service.py').read_text(encoding='utf-8')
    assert 'gateway_scope_authority_violation' in contract
    assert 'provider_account_id is not None or attempt.underlying_provider_code is not None' in service
    assert 'provider_authority_violation' in service


def test_xv12_provisioner_seeds_required_xaf_reference_data_idempotently():
    source=(ROOT/'scripts/provision_xv12_xafpay_v2.py').read_text(encoding='utf-8')
    assert 'INSERT INTO public.currency_assets' in source
    assert "'XAF', 'fiat', 'Central African CFA franc'" in source
    assert 'ON CONFLICT(code) DO UPDATE SET active=true' in source
    assert 'INSERT INTO public.tenant_currency_policies' in source
    assert "'half_even'" in source
    assert 'XV12_R1_XAF_CURRENCY_REFERENCE=PASS' in source


def test_xv12_provisioner_reuses_persisted_opened_at_for_exact_idempotent_replay():
    source=(ROOT/'scripts/provision_xv12_xafpay_v2.py').read_text(encoding='utf-8')
    assert 'SELECT opened_at' in source
    assert 'WHERE tenant_id=:tenant_id AND public_id=:public_id' in source
    assert 'account_opened_at = existing_opened_at or now' in source
    assert 'opened_at=account_opened_at' in source
    assert 'XV12_R1_CLEARING_ACCOUNT_PROVISION_REPLAY=PASS' in source


def test_xv12_create_payment_script_uses_canonical_payment_intent_engine_entrypoint():
    source=(ROOT/'scripts/run_xv12_r1_create_payment.py').read_text(encoding='utf-8')
    engine=(ROOT/'core/domain/finance/payment_intent_engine.py').read_text(encoding='utf-8')
    assert 'def create_intent(' in engine
    assert 'TransactionalPaymentIntentEngine.create_intent(' in source
    assert 'TransactionalPaymentIntentEngine.create(' not in source



def test_xv12_attempt_authority_lock_targets_attempt_row_only_with_optional_tender_join():
    repository=(ROOT/'core/integrations/xafpay_v2/repository.py').read_text(encoding='utf-8')
    attempt_section=repository.split('def attempt_authority',1)[1].split('def reserve_event',1)[0]
    assert 'LEFT JOIN public.canonical_payment_tenders t' in attempt_section
    assert 'suffix = "FOR UPDATE OF a" if lock else ""' in attempt_section
    assert 'suffix = "FOR UPDATE" if lock else ""' not in attempt_section

def test_xv12_r2_service_freezes_non_success_duplicate_conflict_and_ordering_rules():
    service=(ROOT/'core/integrations/xafpay_v2/service.py').read_text(encoding='utf-8')
    router=(ROOT/'core/integrations/xafpay_v2/router.py').read_text(encoding='utf-8')
    verifier=(ROOT/'scripts/verify_xv12_r2_state.py').read_text(encoding='utf-8')
    assert 'payment.failed", "payment.canceled", "payment.expired' in service
    assert 'LATE_NON_SUCCESS_AFTER_SUCCESS' in service
    assert 'event_identity_conflict' in service
    assert 'return {**dict(reservation.response_snapshot), "replayed": True}' in service
    assert 'event_identity_conflict' in router and 'status = 409' in router
    for marker in (
        'XV12_5_FAILED_NO_SUCCESS_EFFECT=PASS',
        'XV12_5_CANCELED_NO_SUCCESS_EFFECT=PASS',
        'XV12_5_EXPIRED_NO_SUCCESS_EFFECT=PASS',
        'XV12_6_DUPLICATE_EVENT_EXACTLY_ONE_EFFECT=PASS',
        'XV12_7_CONFLICT_EVIDENCE_PRESERVED=PASS',
        'XV12_8_LATE_PENDING_NO_BACKWARD_MUTATION=PASS',
        'XV12_8_LATE_FAILED_NO_BACKWARD_MUTATION=PASS',
    ):
        assert marker in verifier


def test_xv12_refund_identity_matches_frozen_gateway_rfd_prefix():
    contract=(ROOT/'core/integrations/xafpay_v2/contract.py').read_text(encoding='utf-8')
    assert '_REFUND_ID = re.compile(r"^rfd_' in contract
    assert '_REFUND_ID = re.compile(r"^ref_' not in contract

def test_xv12_r3_refund_uses_existing_xbos_reversal_authority_and_is_finance_read_only_until_event():
    service=(ROOT/'core/integrations/xafpay_v2/service.py').read_text(encoding='utf-8')
    refund_script=(ROOT/'scripts/run_xv12_r3_refund.py').read_text(encoding='utf-8')
    assert 'TransactionalPaymentSettlementEngine.reverse(' in service
    assert 'ReversePaymentSettlementCommand(' in service
    assert 'refund.succeeded' in service
    request_section=service.split('def request_refund(',1)[1].split('def consume_event(',1)[0]
    assert 'attempt_authority(session, attempt_public_id, lock=False)' in request_section
    assert 'settlement_for_attempt(' in request_section and 'lock=False' in request_section
    assert 'TransactionalPaymentSettlementEngine.reverse(' not in request_section
    assert 'XafPayV2Service.request_refund(' in refund_script


def test_xv12_r3_split_tender_binds_only_xafpay_leg_and_preserves_xbos_cash_authority():
    split=(ROOT/'scripts/run_xv12_r3_split_tender.py').read_text(encoding='utf-8')
    service=(ROOT/'core/integrations/xafpay_v2/service.py').read_text(encoding='utf-8')
    verifier=(ROOT/'scripts/verify_xv12_r3_state.py').read_text(encoding='utf-8')
    assert "payment_method_code='cash'" in split
    assert "payment_method_code='mobile_money'" in split
    assert 'payment_tender_public_id=xaf.public_id' in split
    assert 'attempted_amount=xaf_amount' in split
    assert 'TransactionalPaymentTenderEngine' in service
    settle=service.split('def _settle(',1)[1]
    assert 'payment_tender_public_id=attempt.payment_tender_public_id' in settle
    assert 'canonical_payment_tenders' in verifier
    assert 'XV12_11_SPLIT_TENDER_AUTHORITY=PASS' in verifier


def test_xv12_r3_gateway_outage_reuses_one_stable_xbos_attempt_identity():
    source=(ROOT/'scripts/run_xv12_r3_gateway_outage.py').read_text(encoding='utf-8')
    assert "if mode=='prepare'" in source
    assert "if mode=='down'" in source
    assert "if mode=='recover'" in source
    assert "exc.code!='gateway_transport_error'" in source
    assert "SELECT count(*) FROM canonical_payment_attempts WHERE public_id=:p" in source
    assert 'XV12_13_BLIND_XBOS_ATTEMPT_RETRY' in source
    assert 'XV12_13_XAFPAY_OUTAGE_RECOVERY_CREATE=PASS' in source


def test_xv12_r3_finance_kernel_and_legacy_xafpay_remain_outside_adapter_implementation():
    service=(ROOT/'core/integrations/xafpay_v2/service.py').read_text(encoding='utf-8')
    legacy=(ROOT/'core/integrations/xafpay/adapter.py').read_text(encoding='utf-8')
    assert 'core.domain.finance.payment_settlement_engine' in service
    assert 'core.domain.finance.payment_tender_engine' in service
    assert 'xafpay_v2' not in legacy
    assert (ROOT/'core/domain/finance/payment_settlement_engine.py').exists()
    assert (ROOT/'core/domain/finance/payment_tender_engine.py').exists()


def test_xv12_r3_final_state_verifier_freezes_repair_refund_split_and_outage_controls():
    verifier=(ROOT/'scripts/verify_xv12_r3_state.py').read_text(encoding='utf-8')
    for marker in (
        'XV12_9_REPAIR_XBOS_FINANCIAL_EFFECT=PASS',
        'XV12_10_REFUND_REQUEST_NO_CORRECTION=PASS',
        'XV12_10_REFUND_CORRECTION_EXACTLY_ONCE=PASS',
        'XV12_11_NON_XAFPAY_TENDER_REMAINS_XBOS_AUTHORITY=PASS',
        'XV12_11_SPLIT_TENDER_AUTHORITY=PASS',
        'XV12_13_XBOS_OUTAGE_EXACTLY_ONE_EFFECT=PASS',
        'XV12_13_XAFPAY_RECOVERY_EXACTLY_ONE_EFFECT=PASS',
        'XV12_12_TENANT_LOCATION_ISOLATION=PASS',
    ):
        assert marker in verifier
