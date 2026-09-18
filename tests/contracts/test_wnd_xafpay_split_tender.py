from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_u_pending_xafpay_is_excluded_from_confirmed_local_total():
    controller = read("core/api/payments/payments_controller.py")
    service = read("core/integrations/xafpay_v2/service.py")
    assert "XAFPAY_UNRESOLVED_OBLIGATION" in controller
    assert "attempt_state IN ('pending','processing','requires_action','authorized')" in controller
    pending = service.split(
        'elif event.event_type in {"payment.created", "payment.pending"}:', 1
    )[1].split('elif event.event_type in {"refund.succeeded"', 1)[0]
    assert "NO_SETTLED_EFFECT" in pending


def test_v_success_applies_exact_external_leg_once_to_residual():
    repository = read("core/integrations/xafpay_v2/repository.py")
    service = read("core/integrations/xafpay_v2/service.py")
    assert "total_paid=LEAST(amount,total_paid+:confirmed_amount)" in repository
    assert "balance_due=GREATEST(0,amount-(total_paid+:confirmed_amount))" in repository
    assert '"confirmed_amount": attempt.attempted_amount' in repository
    assert "gross_amount=attempt.attempted_amount" in service
    assert "net_amount=attempt.attempted_amount" in service


def test_gateway_receives_only_the_xafpay_leg_and_no_provider_routing():
    wnd = read("core/integrations/xafpay_v2/wnd_service.py")
    contract = read("core/integrations/xafpay_v2/contract.py")
    assert "amount=attempt.attempted_amount" in wnd
    assert "provider_account_public_id=None" in wnd
    assert "underlying_provider_code=None" in wnd
    body = contract.split("def body(self)", 1)[1].split("@dataclass", 1)[0]
    assert '"permitted_options"' in body
    assert '"provider"' not in body


def test_w_local_manual_tender_pipeline_remains_available():
    service = read("core/domain/payments/service.py")
    guard = service.split("for idx, line in enumerate(lines or []):", 1)[1].split(
        "if amount <= 0:", 1
    )[0]
    assert 'method == "xafpay"' in guard
    assert 'method == "cash"' not in guard
    assert 'method == "mtn"' not in guard
    assert 'method == "orange"' not in guard
    downstream = service.split("if amount <= 0:", 1)[1]
    assert 'settlement_mode="manual"' in downstream
    assert "PaymentAttemptStatus.succeeded" in downstream


def test_split_residual_allocation_cannot_exceed_commercial_balance_due():
    controller = read("core/api/payments/payments_controller.py")
    init = controller.split("async def init_xafpay_payment", 1)[1]
    assert "available_balance" in init
    assert "requested_amount > available_balance" in init
    assert "XafPay allocation must be positive and no greater than balance due" in init


def test_u_external_pending_residual_does_not_create_accounts_receivable(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://r1:r1@127.0.0.1:5432/xbos_r1_offline_placeholder",
    )
    import core.api.payments.payments_controller as controller_module
    from core.api.payments.payments_controller import PaymentsController

    order = SimpleNamespace(status="pending_payment")
    intent = SimpleNamespace(
        balance_due=Decimal("10000"),
        total_paid=Decimal("5000"),
        amount=Decimal("15000"),
        id=77,
    )
    sale = SimpleNamespace(id=202, total=Decimal("15000"))
    added = []
    ar_calls = []

    monkeypatch.setattr(
        controller_module.OrderRepository,
        "get_by_id",
        staticmethod(lambda db, order_id: order),
    )
    monkeypatch.setattr(
        controller_module.AccountsReceivableService,
        "create_or_update_from_settlement",
        staticmethod(lambda *args, **kwargs: ar_calls.append(kwargs)),
    )

    db = SimpleNamespace(add=lambda value: added.append(value))
    result = PaymentsController()._apply_order_settlement_status_and_ar(
        db=db,
        tenant_id=2,
        branch_id=1,
        user_id=9,
        order_id=101,
        sale=sale,
        intent=intent,
        receipt_meta={},
        external_pending_amount=Decimal("10000"),
        accounts_receivable_amount=Decimal("0"),
    )

    assert result is None
    assert ar_calls == []
    assert order.status == "pending_payment"
    assert added == [order]


def test_u_external_pending_and_real_unpaid_keep_only_real_unpaid_as_debt(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://r1:r1@127.0.0.1:5432/xbos_r1_offline_placeholder",
    )
    import core.api.payments.payments_controller as controller_module
    from core.api.payments.payments_controller import PaymentsController

    order = SimpleNamespace(status="pending_payment")
    intent = SimpleNamespace(
        balance_due=Decimal("12000"),
        total_paid=Decimal("3000"),
        amount=Decimal("15000"),
        id=77,
    )
    sale = SimpleNamespace(id=202, total=Decimal("15000"))
    captured = {}

    monkeypatch.setattr(
        controller_module.OrderRepository,
        "get_by_id",
        staticmethod(lambda db, order_id: order),
    )

    def create_ar(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=5, status="open")

    monkeypatch.setattr(
        controller_module.AccountsReceivableService,
        "create_or_update_from_settlement",
        staticmethod(create_ar),
    )
    db = SimpleNamespace(add=lambda value: None)

    PaymentsController()._apply_order_settlement_status_and_ar(
        db=db,
        tenant_id=2,
        branch_id=1,
        user_id=9,
        order_id=101,
        sale=sale,
        intent=intent,
        receipt_meta={},
        external_pending_amount=Decimal("10000"),
        accounts_receivable_amount=Decimal("2000"),
    )

    assert captured["balance_due"] == Decimal("2000")
    assert order.status == "pending_payment"


def test_debt_event_uses_accounts_receivable_amount_not_external_pending(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace
    from datetime import datetime, timezone

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://r1:r1@127.0.0.1:5432/xbos_r1_offline_placeholder",
    )
    import core.domain.payments.service as payment_module
    from core.domain.payments.service import PaymentService

    emitted = []
    monkeypatch.setattr(
        payment_module.FinancialEventEmitter,
        "debt_created",
        staticmethod(lambda *args, **kwargs: emitted.append(kwargs)),
    )
    intent = SimpleNamespace(id=77, payable_id=202)
    common = dict(
        db=object(),
        tenant_id=2,
        branch_id=1,
        intent=intent,
        sale_id=202,
        payable_type="sale",
        currency="XAF",
        gross_total=Decimal("15000"),
        net_total=Decimal("15000"),
        discount_total=Decimal("0"),
        discount_type=None,
        complimentary_total=Decimal("0"),
        complimentary_reason=None,
        complimentary_items=[],
        total_paid=Decimal("5000"),
        balance_due=Decimal("10000"),
        store_credit=Decimal("0"),
        tip_amount=Decimal("0"),
        change_given_now=Decimal("0"),
        current_tendered_total=Decimal("5000"),
        complete_balance=False,
        settle_failed_intent=False,
        occurred_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
        meta={},
    )

    PaymentService._emit_settlement_accounting_events(
        **common,
        accounts_receivable_amount=Decimal("0"),
    )
    assert emitted == []

    PaymentService._emit_settlement_accounting_events(
        **common,
        accounts_receivable_amount=Decimal("2000"),
    )
    assert len(emitted) == 1
    assert emitted[0]["amount"] == Decimal("2000")
