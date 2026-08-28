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
    assert 'line?.method !== "xafpay"' in replacement
    assert 'external_pending_amount: xafpayAmount' in replacement
    assert 'amount: xafpayAmount' in replacement


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


def test_r2_split_ui_has_four_tenders_and_residual_is_read_only() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    assert 'aria-label="XafPay allocation"' in overlay
    assert 'placeholder="Cash"' not in overlay  # inherited Cash input remains unchanged
    assert 'Remaining:' in overlay
    assert 'setSplitXafPay' in overlay
    assert 'method: "unpaid"' not in overlay.split("split_panel =", 1)[1].split(
        "payment_screen =", 1
    )[0]


def test_r2_split_preserves_local_tenders_and_externalizes_only_xafpay() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    controller = read("core/api/payments/payments_controller.py")
    assert 'line?.method !== "xafpay"' in overlay
    assert 'external_pending_amount: xafpayAmount' in overlay
    assert 'amount: xafpayAmount' in overlay
    assert 'const localLines = (location.state?.lines || []).filter' in overlay
    assert 'line?.method !== "xafpay"' in overlay
    assert 'requested_amount = _d(payload.get("amount"))' in controller
    assert "requested_amount > available_balance" in controller


def test_r2_canonical_success_applies_only_external_leg() -> None:
    repository = read("core/integrations/xafpay_v2/repository.py")
    assert "total_paid=LEAST(amount,total_paid+:confirmed_amount)" in repository
    assert "balance_due=GREATEST(0,amount-(total_paid+:confirmed_amount))" in repository
    assert '"receivable" if has_ar else "pending_payment"' in repository
    assert "total_paid=amount,balance_due=0" not in repository


def test_r2_pending_external_allocation_is_not_accounts_receivable() -> None:
    controller = read("core/api/payments/payments_controller.py")
    service = read("core/domain/payments/service.py")
    assert "external_pending_amount" in controller
    assert "accounts_receivable_amount" in controller
    assert "accounts_receivable_amount > 0" in service
    assert "amount=accounts_receivable_amount" in service


def test_r2_result_archive_and_modal_recovery_use_server_financial_truth() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    controller = read("core/api/payments/payments_controller.py")
    sales = read("core/api/sales/sales_controller.py")
    assert "Checking current payment state" in overlay
    assert "sale.payment_state" in overlay
    assert "xafpay.checkout.status" in overlay
    assert "financially_confirmed" in controller
    assert "collectible_now" in controller
    assert 'payment_state = "PAYMENT_PENDING"' in sales
    assert 'payment_state = "RECEIVABLE"' in sales


def test_r2_cash_gross_tender_and_open_collection_controls_remain_distinct() -> None:
    service = read("core/domain/payments/service.py")
    receipts = read("core/api/payments/receipts_controller.py")
    accounting = read("core/api/accounting/accounting_router.py")
    assert "cumulative_tendered_total, current_tendered_total" in service
    assert 'cash_given = max(attempt.amount, _d(meta.get("tendered")))' in service
    assert "ledger_amount = cash_given - retained_adjustment" in service
    assert '"cash_given"' in receipts
    assert '"collection_controls"' in accounting
    assert '"open_balance_controls"' in accounting
    assert '"financial_effect": "NONE"' in accounting
    assert '"confirmed_money": 0' in accounting


def test_r2_pending_recovery_is_obligation_scoped_not_a_global_modal_flag() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    controller = read("core/api/payments/payments_controller.py")
    router = read("core/api/payments/payments_router.py")
    assert "xbos_xafpay_recovery" not in overlay
    assert "paymentId=${encodeURIComponent(paymentRecordId)}" in overlay
    assert 'get("paymentId")' in overlay
    assert "/xafpay/orders/{order_id}/recovery" in router
    assert "a.metadata->>'order_id'=:order_id" in controller
    assert '"unresolved": unresolved' in controller
    assert '"payment_record_id": str(row["payment_record_id"])' in controller
    assert '"XAFPAY_UNRESOLVED_OBLIGATION"' in controller
    assert "!xafpayRecovery?.unresolved" in overlay
    assert "Resume XafPay" in overlay
    assert "Check status" in overlay
    assert "recovery?.unresolved !== true" in overlay
    assert "recovery?.attempt_public_id" in overlay
    assert "localStorage" not in overlay
    assert "sessionStorage" not in overlay
    assert "Other orders remain available" in overlay


def test_r2_pending_status_actions_share_one_server_scoped_recovery_contract() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    controller = read("core/api/payments/payments_controller.py")
    assert "checkXafpayCanonicalStatus" in overlay
    assert "loadXafpayRecovery" in overlay
    assert "xafpayOperatorResult" in overlay
    assert "Still awaiting confirmation" in overlay
    assert "Processing" in overlay and "provider confirmation pending" in overlay
    assert "Unknown" in overlay and "confirmation unresolved" in overlay
    assert "Paid / confirmed" in overlay
    assert "xafpayStatusResult" in overlay
    assert "xafpayCheckResult" in overlay
    assert "PaymentActivityLedger" in overlay
    assert '"recovery": recovery' in controller
    assert '"attempt_public_id": latest["id"]' in controller
    assert '"payment_record_id": str(intent.id)' in controller
    assert "PaymentService.settle" not in overlay


def test_r2_money_activity_preserves_inline_status_result_across_check() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    activity_block = overlay.split("activity_ledger =", 1)[1].split(
        "payment_screen =", 1
    )[0]
    assert 'action === "status" ? "Checking..."' in activity_block
    assert "Still processing" in activity_block
    assert "no payment confirmed yet" in activity_block
    assert "Awaiting confirmation" in activity_block
    assert "Confirmation unresolved" in activity_block
    assert "Payment failed" in activity_block
    assert "Payment session / attempt expired" in activity_block
    assert "Payment confirmed" in activity_block
    assert "Last checked:" in activity_block
    assert "await onRefresh?.()" not in activity_block


def test_r2_xafpay_cancel_request_is_canonical_and_fail_closed() -> None:
    controller = read("core/api/payments/payments_controller.py")
    router = read("core/api/payments/payments_router.py")
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    assert "/xafpay/attempts/{attempt_public_id}/cancel-request" in router
    assert "request_xafpay_cancellation" in controller
    assert "await self.xafpay_attempt_status" in controller
    assert '"cancellation_state": "UNCONFIRMED"' in controller
    assert '"replacement_tender_allowed": False' in controller
    assert "This payment may still complete" in controller
    assert "Do not collect another payment yet" in controller
    assert '"cancellation_state": "TERMINAL_CONFIRMED"' in controller
    assert '"replacement_tender_allowed": True' in controller
    assert "db.commit" not in controller.split("async def request_xafpay_cancellation", 1)[1].split(
        "# =====================================================", 1
    )[0]
    assert "requestXafpayCancellation" in overlay
    assert overlay.count("Cancel XafPay payment") >= 4
    assert "Cancelling..." in overlay
    assert "Leave confirmation pending" in overlay


def test_r2_tranzak_has_no_authoritative_cancel_capability() -> None:
    port = (ROOT.parent / "xafpay-gateway-v2" / "packages/providers/src/port.ts").read_text(encoding="utf-8")
    tranzak = (ROOT.parent / "xafpay-gateway-v2" / "packages/providers/src/tranzak/provider.ts").read_text(encoding="utf-8")
    assert "queryPayment" in port
    assert "cancelPayment" not in port
    assert "refreshPayment" in tranzak
    assert "cancelPayment" not in tranzak


def test_r2_checkout_open_is_distinct_from_provider_submission() -> None:
    controller = read("core/api/payments/payments_controller.py")
    client = read("core/integrations/xafpay_v2/client.py")
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")
    gateway_controller = (ROOT.parent / "xafpay-gateway-v2" / "apps/api/src/payments/xbos-v2-payment.controller.ts").read_text(encoding="utf-8")
    gateway_repository = (ROOT.parent / "xafpay-gateway-v2" / "packages/database/src/xbos-v2-gateway-repository.ts").read_text(encoding="utf-8")

    assert "payment_execution_status" in client
    assert "/execution-status" in client
    assert 'else "CHECKOUT_OPEN"' in controller
    assert 'unresolved = provider_submitted and state in' in controller
    assert '"provider_submitted": provider_submitted' in controller
    assert "CHECKOUT_OPEN" in overlay
    assert "No provider request has been submitted" in overlay
    assert 'preSubmission ? "Return to payment"' in overlay
    assert "!preSubmission && !succeeded && !failed" in overlay
    assert "execution-status" in gateway_controller
    assert "providerSubmitted: row.attempt_status !== null && row.attempt_status !== 'CREATED'" in gateway_repository


def test_r2_api_login_public_boundary_is_exact() -> None:
    middleware = read("core/middleware/auth_middleware.py")
    startup = read("startup.py")

    assert 'method == "POST" and path == "/api/auth/login"' in middleware
    assert 'path.startswith("/api/auth/")' not in middleware
    assert '"/api/auth/login"' in startup
    assert 'methods=["POST"]' in startup
    assert '"/api/auth/refresh"' not in startup
    assert '"/api/auth/me"' not in startup


def test_r2_checkout_proposal_is_not_payment_records_execution_truth() -> None:
    controller = read("core/api/payments/payments_controller.py")

    projection = controller.split("def _canonical_xafpay_attempts", 1)[1].split(
        "def _payment_record_summary", 1
    )[0]
    assert "if not provider_submitted:" in projection
    assert "continue" in projection
    assert '"status": status_value,' in projection
    assert '"has_xafpay_attempt": provider_submitted' in controller
    assert '"has_checkout_proposal": not provider_submitted' in controller
    assert 'channel="pos"' in controller


def test_r2_payment_summary_method_uses_confirmed_settlement_legs_only() -> None:
    controller = read("core/api/payments/payments_controller.py")
    summary = controller.split("def _payment_record_summary", 1)[1].split(
        "def _extract_customer_name", 1
    )[0]

    assert 'AS confirmed_settlements' in controller
    assert '"confirmed_settlements": int(row["confirmed_settlements"] or 0)' in controller
    assert 'successful_canonical = [' in summary
    assert 'attempt["status"] == "COMPLETED"' in summary
    assert 'int(attempt.get("confirmed_settlements") or 0) > 0' in summary
    assert 'bool(local_methods and successful_canonical)' in summary
    assert 'latest = successful_canonical[-1]' in summary


def test_r2_frontend_auth_refresh_is_single_flight_and_bootstrap_gated() -> None:
    overlay = read("scripts/prepare_xv15_frontend_runtime.py")

    assert "let refreshPromise: Promise<string> | null = null" in overlay
    assert "if (!refreshPromise)" in overlay
    assert "refreshPromise = performRefreshAccessToken().finally" in overlay
    assert "waitForAuthBootstrap" in overlay
    assert "await waitForAuthBootstrap()" in overlay
    assert "currentToken !== token" in overlay
    assert 'path === "/auth/login" || path === "/auth/refresh"' in overlay
    assert "handleTerminalAuthFailure" in overlay
    assert "if (terminalAuthFailureHandled) return" in overlay
