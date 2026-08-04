from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


WINDOW_START = datetime(2000, 1, 1, 8, tzinfo=timezone.utc)
WINDOW_END = datetime(2000, 1, 2, 8, tzinfo=timezone.utc)
EVENT_TIME = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
EVENT_SOURCE = "track_b_reconciliation_mapping"
RECONCILIATION_PATH = "/kernel/accounting/reconciliation"


def _amount(value):
    return Decimal(str(value))


def _emit_mapping_events(wnd_test_identity):
    from core.domain.accounting.emitter import FinancialEventEmitter
    from database import SessionLocal

    run_id = uuid4().hex
    tenant_id = wnd_test_identity["tenant_id"]
    branch_id = wnd_test_identity["branch_id"]
    db = SessionLocal()

    events = [
        {
            "event_type": "SALE_REVENUE_GROSS",
            "amount": 10000,
            "direction": "credit",
            "channel": None,
            "meta": {},
        },
        {
            "event_type": "PAYMENT_RECEIVED",
            "amount": 3000,
            "direction": "credit",
            "channel": "cash",
            "meta": {},
        },
        {
            "event_type": "PAYMENT_RECEIVED",
            "amount": 2000,
            "direction": "credit",
            "channel": "mtn",
            "meta": {},
        },
        {
            "event_type": "DEBT_CREATED",
            "amount": 1500,
            "direction": "debit",
            "channel": "ar",
            "meta": {},
        },
        {
            "event_type": "DEBT_REPAYMENT",
            "amount": 500,
            "direction": "credit",
            "channel": "orange",
            "meta": {
                "source_channel": "ar",
                "target_channel": "orange",
            },
        },
        {
            "event_type": "DISCOUNT_APPLIED",
            "amount": 1000,
            "direction": "debit",
            "channel": None,
            "meta": {
                "display_label": "B1 Promotional Discount",
            },
        },
        {
            "event_type": "COMPLIMENTARY_APPLIED",
            "amount": 500,
            "direction": "debit",
            "channel": None,
            "meta": {
                "display_label": "B1 Complimentary",
            },
        },
        {
            "event_type": "EXPENSE_POSTED",
            "amount": 700,
            "direction": "debit",
            "channel": "cash",
            "meta": {},
        },
        {
            "event_type": "REFUND_PAID",
            "amount": 300,
            "direction": "debit",
            "channel": "cash",
            "meta": {},
        },
        {
            "event_type": "CASH_MOVE",
            "amount": 1000,
            "direction": "credit",
            "channel": "bank",
            "meta": {
                "source_channel": "cash",
                "target_channel": "bank",
            },
        },
        {
            "event_type": "OTHER_INCOME",
            "amount": 200,
            "direction": "credit",
            "channel": "bank",
            "meta": {
                "category_name": "B1 Other Income",
            },
        },
        {
            "event_type": "SERVICE_REVENUE",
            "amount": 100,
            "direction": "credit",
            "channel": "mtn",
            "meta": {
                "category_name": "B1 Service Revenue",
            },
        },
        {
            "event_type": "STORE_CREDIT_CREATED",
            "amount": 400,
            "direction": "credit",
            "channel": "ap",
            "meta": {},
        },
        {
            "event_type": "TIP_REVENUE",
            "amount": 200,
            "direction": "credit",
            "channel": "cash",
            "meta": {},
        },
    ]

    try:
        db.execute(
            text(
                """
                DELETE FROM treasury_logs
                WHERE tenant_id = :tenant_id
                  AND branch_id = :branch_id
                  AND occurred_at >= :window_start
                  AND occurred_at < :window_end
                  AND meta ->> 'source' = :event_source
                """
            ),
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "window_start": WINDOW_START,
                "window_end": WINDOW_END,
                "event_source": EVENT_SOURCE,
            },
        )

        for index, event in enumerate(events, start=1):
            FinancialEventEmitter.emit(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                idempotency_key=f"b1-recon-map:{run_id}:{index}",
                direction=event["direction"],
                event_type=event["event_type"],
                amount=event["amount"],
                currency="XAF",
                channel=event["channel"],
                reference_type="track_b_characterization",
                reference_id=index,
                occurred_at=EVENT_TIME,
                meta={
                    **event["meta"],
                    "source": EVENT_SOURCE,
                    "run_id": run_id,
                },
            )

        db.commit()
    finally:
        db.close()


def test_treasury_events_map_to_reconciliation_rows_and_commercial_summary(
    client,
    auth_headers,
    wnd_test_identity,
):
    _emit_mapping_events(wnd_test_identity)

    response = client.get(
        RECONCILIATION_PATH,
        headers=auth_headers,
        params={
            "start": WINDOW_START.isoformat(),
            "end": WINDOW_END.isoformat(),
            "shift": "full24",
            "limit": 500,
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()
    rows = {row["channel"]: row for row in body["rows"]}

    cash = rows["cash"]
    assert _amount(cash["income"]) == Decimal("3000")
    assert _amount(cash["expense"]) == Decimal("1000")
    assert _amount(cash["cashIn"]) == Decimal("0")
    assert _amount(cash["cashOut"]) == Decimal("1000")
    assert _amount(cash["expected"]) == _amount(cash["opening"]) + Decimal("1000")

    mtn = rows["mtn"]
    assert _amount(mtn["income"]) == Decimal("2100")
    assert _amount(mtn["expense"]) == Decimal("0")
    assert _amount(mtn["cashIn"]) == Decimal("0")
    assert _amount(mtn["cashOut"]) == Decimal("0")

    orange = rows["orange"]
    assert _amount(orange["income"]) == Decimal("0")
    assert _amount(orange["cashIn"]) == Decimal("500")
    assert _amount(orange["cashOut"]) == Decimal("0")

    bank = rows["bank"]
    assert _amount(bank["income"]) == Decimal("200")
    assert _amount(bank["cashIn"]) == Decimal("1000")
    assert _amount(bank["cashOut"]) == Decimal("0")

    ar = rows["ar"]
    assert _amount(ar["income"]) == Decimal("1500")
    assert _amount(ar["cashIn"]) == Decimal("0")
    assert _amount(ar["cashOut"]) == Decimal("500")

    ap = rows["ap"]
    assert _amount(ap["income"]) == Decimal("400")
    assert _amount(ap["cashIn"]) == Decimal("0")
    assert _amount(ap["cashOut"]) == Decimal("0")

    summary = body["commercial_summary"]

    assert _amount(summary["gross_sales"]) == Decimal("10000")
    assert _amount(summary["collections"]) == Decimal("5000")
    assert _amount(summary["applied_to_sales"]) == Decimal("4400")
    assert _amount(summary["discounts"]) == Decimal("1000")
    assert _amount(summary["complimentary"]) == Decimal("500")
    assert _amount(summary["allowances"]) == Decimal("1500")
    assert _amount(summary["ar_created"]) == Decimal("1500")
    assert _amount(summary["ar_repaid"]) == Decimal("500")
    assert _amount(summary["ar_net"]) == Decimal("1000")
    assert _amount(summary["ap_created"]) == Decimal("400")
    assert _amount(summary["tips"]) == Decimal("200")
    assert _amount(summary["refunds"]) == Decimal("300")
    assert _amount(summary["real_expenses"]) == Decimal("700")
    assert _amount(summary["manual_income"]) == Decimal("300")
    assert _amount(summary["service_income"]) == Decimal("100")
    assert _amount(summary["other_income"]) == Decimal("200")
    assert _amount(summary["settled_value"]) == Decimal("7100")
    assert _amount(summary["unallocated"]) == Decimal("2900")

    assert summary["discount_by_type"] == {
        "B1 Promotional Discount": 1000.0,
    }
    assert summary["complimentary_by_type"] == {
        "B1 Complimentary": 500.0,
    }
    assert summary["manual_income_by_category"] == {
        "B1 Other Income": 200.0,
        "B1 Service Revenue": 100.0,
    }
