from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pos_settlement_rejects_fake_xafpay_as_cash() -> None:
    controller = read("core/api/payments/payments_controller.py")
    assert 'line.get("method")' in controller
    assert '== "xafpay"' in controller
    assert "HTTP_409_CONFLICT" in controller
    assert "canonical confirmation" in controller


def test_both_wnd_surfaces_share_neutral_xafpay_orchestration_route() -> None:
    controller = read("core/api/payments/payments_controller.py")
    assert "WndXafPayV2Service.initiate_order" in controller
    assert '"/payments/xafpay/init"' not in controller
    router = read("core/api/payments/payments_router.py")
    assert '@router.post("/xafpay/init")' in router


def test_gateway_success_only_creates_neutral_settlement_once() -> None:
    service = read("core/integrations/xafpay_v2/service.py")
    assert 'event.event_type == "payment.succeeded"' in service
    assert "cls._settle(session, current, event, operational_account_public_id)" in service
    assert 'event.event_type in {"payment.created", "payment.pending", "payment.requires_action"}' in service
    assert 'effect = "NO_SETTLED_EFFECT"' in service


def test_frontend_overlay_never_calls_pos_settle_for_xafpay() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    assert 'apiFetch("/payments/xafpay/init"' in overlay
    replacement = overlay.split("new = '''", 1)[1].split("'''", 1)[0]
    assert "/payments/pos/settle" not in replacement


def test_cashier_xafpay_confirm_does_not_require_preexisting_provider_data() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    assert 'case "xafpay":' in overlay
    assert "return due > 0;" in overlay
    assert "Hosted Checkout/provider UI owns payer collection" in overlay


def test_cashier_hosts_the_accepted_checkout_in_a_modal_not_the_gateway_api() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    controller = read("core/api/payments/payments_controller.py")

    assert "setCheckoutUrl(initiated.paymentUrl)" in overlay
    assert 'role="dialog"' in overlay
    assert '<iframe title="XafPay secure checkout"' in overlay
    assert 'referrerPolicy="no-referrer"' in overlay
    assert 'public" / "xafpay-checkout"' in overlay
    assert '"/public"' in overlay
    assert "XAFPAY_V2_CHECKOUT_PRESENTATION_URL" in controller
    assert 'f"{presentation_url}#token=' in controller
    assert "/checkout/#token=" not in controller


def test_money_activity_static_route_precedes_dynamic_payment_id() -> None:
    router = read("core/api/payments/payments_router.py")
    assert router.index('@router.get("/activity")') < router.index('@router.get("/{payment_id}")')


def test_money_activity_projects_only_confirmed_xafpay_settlement_as_money() -> None:
    controller = read("core/api/payments/payments_controller.py")
    assert "a.orchestrator_code='xafpay'" in controller
    assert "s.settlement_state IN ('confirmed','partially_reversed')" in controller
    assert '"source": "payment_settlement"' in controller
    assert '"flow": "attention"' in controller


def test_payment_records_project_neutral_xafpay_attempts_without_settlement() -> None:
    controller = read("core/api/payments/payments_controller.py")
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    assert "_canonical_xafpay_attempts" in controller
    assert "canonical_payment_attempts" in controller
    assert '"financial_effect": "NONE_UNTIL_CANONICAL_SUCCESS"' in controller
    assert '"origin_channel": "pos"' in controller
    assert '"orchestrator": row["orchestrator_code"]' in controller
    assert '"rail": str(row["payment_rail_code"]' in controller
    assert "Origin/channel:" in overlay
    assert "attempt.orchestrator" in overlay


def test_definitive_failure_terminates_only_the_attempt_and_allows_governed_retry() -> None:
    service = read("core/integrations/xafpay_v2/service.py")
    wnd = read("core/integrations/xafpay_v2/wnd_service.py")
    failed_branch = service.split('event.event_type == "payment.failed"', 1)[1].split(
        'event.event_type == "payment.canceled"', 1
    )[0]
    assert '_transition_attempt(session, current, "failed"' in failed_branch
    assert "_transition_bound_tender" not in failed_branch
    assert 'prior.attempt_state not in {"failed", "cancelled", "expired"}' in wnd
    assert "XV15_XAFPAY_UNRESOLVED_ATTEMPT_BLOCKS_RETRY" in wnd
    assert "retry_of_attempt_public_id=prior.public_id" in wnd
    assert "payment_intent_public_id=prior.payment_intent_public_id" in wnd


def test_daily_ledger_projects_confirmed_xafpay_settlement_without_rewriting_events() -> None:
    router = read("core/api/accounting/accounting_router.py")
    assert "_confirmed_xafpay_settlement_rows" in router
    assert '"event_type": "PAYMENT_RECEIVED"' in router
    assert '"canonical_settlement": True' in router
    assert "settlement_state IN ('confirmed','partially_reversed')" in router
    assert "TreasuryRepository.record" not in router.split(
        "def _confirmed_xafpay_settlement_rows", 1
    )[1].split("def _serialize_repayment", 1)[0]


def test_receipt_uses_tender_dimensions_not_pos_origin() -> None:
    controller = read("core/api/payments/receipts_controller.py")
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    assert '"method": str(row["payment_method_code"]' in controller
    assert '"rail": str(row["payment_rail_code"]' in controller
    assert '"orchestrator": str(row["orchestrator_code"]' in controller
    assert '"origin_channel": "pos"' in controller
    assert 'XAFPAY / ${rail === "MTN MOMO" ? "MTN MoMo" : rail}' in overlay


def test_reconciliation_counts_only_confirmed_xafpay_settlement_truth() -> None:
    router = read("core/api/accounting/accounting_router.py")
    assert "xafpay_amount = sum" in router
    assert 'row["income"] = _f(row.get("income")) + xafpay_amount' in router
    assert 'row["confirmed_settlements"]' in router
    assert 'row["confirmed_settlement_count"]' in router
    assert 'Mobile Money · ${rails} via XafPay' in read(
        "scripts/prepare_xv15_frontend_runtime.py"
    )
