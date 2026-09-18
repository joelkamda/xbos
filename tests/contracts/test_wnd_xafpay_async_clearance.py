from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_d_checkout_creation_has_no_order_paid_or_settlement_authority():
    wnd = read("core/integrations/xafpay_v2/wnd_service.py")
    client = read("core/integrations/xafpay_v2/client.py")
    assert "create_checkout(request)" in wnd
    assert "finalize_wnd_projection" not in wnd
    assert "PaymentSettlement" not in client
    assert "mark_paid" not in wnd


def test_e_pending_event_has_no_settlement_branch():
    service = read("core/integrations/xafpay_v2/service.py")
    pending = service.split(
        'elif event.event_type in {"payment.created", "payment.pending"}:', 1
    )[1].split('elif event.event_type in {"refund.succeeded"', 1)[0]
    assert 'effect = "NO_SETTLED_EFFECT"' in pending
    assert "cls._settle(" not in pending


def test_f_pending_does_not_clear_wnd_projection():
    service = read("core/integrations/xafpay_v2/service.py")
    success = service.split('if event.event_type == "payment.succeeded":', 1)[1].split(
        'elif event.event_type in {"payment.failed"', 1
    )[0]
    assert "finalize_wnd_projection" in success
    prefix = service.split('if event.event_type == "payment.succeeded":', 1)[0]
    assert "finalize_wnd_projection" not in prefix


def test_g_success_is_the_only_payment_event_that_calls_settle():
    service = read("core/integrations/xafpay_v2/service.py")
    assert service.count("cls._settle(session, current, event, operational_account_public_id)") == 1
    assert 'if event.event_type == "payment.succeeded":' in service


def test_h_commercial_clearance_requires_zero_residual_balance():
    repository = read("core/integrations/xafpay_v2/repository.py")
    assert "total_paid=LEAST(amount,total_paid+:confirmed_amount)" in repository
    assert "balance_due=GREATEST(0,amount-(total_paid+:confirmed_amount))" in repository
    assert "if remaining <= 0:" in repository
    paid_block = repository.split("if remaining <= 0:", 1)[1].split("has_ar =", 1)[0]
    assert "UPDATE orders SET status='paid'" in paid_block
    assert "UPDATE sales SET status='paid'" in paid_block


def test_j_failure_path_has_no_success_settlement():
    service = read("core/integrations/xafpay_v2/service.py")
    failure = service.split(
        'elif event.event_type in {"payment.failed", "payment.canceled", "payment.expired"}:', 1
    )[1].split('elif event.event_type == "payment.requires_action":', 1)[0]
    assert "cls._settle(" not in failure
    assert "finalize_wnd_projection" not in failure


def test_k_failure_does_not_rewrite_commercial_balance_as_paid():
    service = read("core/integrations/xafpay_v2/service.py")
    failure = service.split(
        'elif event.event_type in {"payment.failed", "payment.canceled", "payment.expired"}:', 1
    )[1].split('elif event.event_type == "payment.requires_action":', 1)[0]
    assert "_transition_attempt" in failure
    assert "payment_intents" not in failure
    assert "orders SET status='paid'" not in failure


def test_x_xafpay_cannot_enter_local_manual_success_path():
    domain = read("core/domain/payments/service.py")
    controller = read("core/api/payments/payments_controller.py")
    assert 'method == "xafpay"' in domain
    assert "XafPay external payment cannot enter the local manual-success path" in domain
    assert 'str(line.get("method") or "").strip().lower() == "xafpay"' in controller
    assert "canonical Gateway settlement" in controller


def test_receipt_projects_only_confirmed_canonical_xafpay_settlement():
    receipts = read("core/api/payments/receipts_controller.py")
    assert "payment_settlements" in receipts
    assert "a.orchestrator_code='xafpay'" in receipts
    assert "s.settlement_state IN ('confirmed','partially_reversed')" in receipts
    assert '"settlement_mode": "canonical_external"' in receipts
