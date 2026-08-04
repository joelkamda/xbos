from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


ATOMIC_UNIT_ID = 19
ORDER_TOTAL = Decimal("3500.00")


def _create_order(client, auth_headers):
    from database import SessionLocal

    db = SessionLocal()

    try:
        result = db.execute(
            text(
                """
                UPDATE inventory_items
                SET quantity_on_hand = 100
                WHERE tenant_id = 2
                  AND branch_id = 1
                  AND atomic_unit_id = :atomic_unit_id
                """
            ),
            {"atomic_unit_id": ATOMIC_UNIT_ID},
        )
        assert result.rowcount == 1
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/kernel/orders/",
        headers=auth_headers,
        json={
            "items": [
                {
                    "atomic_unit_id": ATOMIC_UNIT_ID,
                    "quantity": 1,
                }
            ]
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()
    assert Decimal(str(body["total"])) == ORDER_TOTAL
    assert body["status"] == "pending_payment"

    return body


def _settle_order(
    client,
    auth_headers,
    *,
    order_id,
    lines,
    tendered_total,
    unpaid_amount,
):
    response = client.post(
        "/kernel/payments/pos/settle",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "client_reference": f"b1-receivable-{uuid4().hex}",
            "lines": lines,
            "tendered_total": tendered_total,
            "change_amount": 0,
            "change_given_now": 0,
            "tip_amount": 0,
            "unpaid_amount": unpaid_amount,
            "receipt_meta": {
                "description": "Track B receivable characterization",
                "customer": {
                    "name": "Track B Test Debtor",
                    "phone": "000000000",
                },
                "note": "Test database only",
            },
        },
    )

    assert response.status_code == 200, response.text
    return response.json()


def _load_state(*, order_id, sale_id, intent_id):
    from database import SessionLocal

    db = SessionLocal()

    try:
        order_row = (
            db.execute(
                text(
                    """
                    SELECT status, total
                    FROM orders
                    WHERE id = :order_id
                    """
                ),
                {"order_id": order_id},
            )
            .mappings()
            .one()
        )

        sale_row = (
            db.execute(
                text(
                    """
                    SELECT status, total, order_id
                    FROM sales
                    WHERE id = :sale_id
                    """
                ),
                {"sale_id": sale_id},
            )
            .mappings()
            .one()
        )

        intent_row = (
            db.execute(
                text(
                    """
                    SELECT status, amount, total_paid, balance_due
                    FROM payment_intents
                    WHERE id = :intent_id
                    """
                ),
                {"intent_id": intent_id},
            )
            .mappings()
            .one()
        )

        attempts = (
            db.execute(
                text(
                    """
                    SELECT id, method, amount, status
                    FROM payment_attempts
                    WHERE payment_intent_id = :intent_id
                    ORDER BY id
                    """
                ),
                {"intent_id": intent_id},
            )
            .mappings()
            .all()
        )

        receivable = (
            db.execute(
                text(
                    """
                    SELECT id, status, original_amount,
                           paid_amount, balance_due
                    FROM accounts_receivable
                    WHERE order_id = :order_id
                    """
                ),
                {"order_id": order_id},
            )
            .mappings()
            .one()
        )

        sale_events = (
            db.execute(
                text(
                    """
                    SELECT event_type, amount, channel,
                           direction, reference_type
                    FROM treasury_logs
                    WHERE reference_type = 'sale'
                      AND reference_id = :sale_id
                    ORDER BY id
                    """
                ),
                {"sale_id": sale_id},
            )
            .mappings()
            .all()
        )

        attempt_events = []

        if attempts:
            attempt_ids = [attempt["id"] for attempt in attempts]
            attempt_events = (
                db.execute(
                    text(
                        """
                        SELECT event_type, amount, channel
                        FROM treasury_logs
                        WHERE reference_type = 'payment_attempt'
                          AND reference_id = ANY(:attempt_ids)
                        ORDER BY id
                        """
                    ),
                    {"attempt_ids": attempt_ids},
                )
                .mappings()
                .all()
            )

        return {
            "order": order_row,
            "sale": sale_row,
            "intent": intent_row,
            "attempts": attempts,
            "receivable": receivable,
            "sale_events": sale_events,
            "attempt_events": attempt_events,
        }
    finally:
        db.close()


def test_partial_cash_payment_creates_receivable(
    client,
    auth_headers,
):
    order = _create_order(client, auth_headers)

    settlement = _settle_order(
        client,
        auth_headers,
        order_id=order["id"],
        lines=[
            {
                "method": "cash",
                "amount": 1000,
                "meta": {
                    "source": "track_b_characterization",
                },
            },
            {
                "method": "unpaid",
                "amount": 2500,
                "meta": {
                    "note": "Partial payment balance",
                },
            },
        ],
        tendered_total=1000,
        unpaid_amount=2500,
    )

    assert Decimal(str(settlement["total_paid"])) == Decimal("1000")
    assert Decimal(str(settlement["balance_due"])) == Decimal("2500")
    assert settlement["ar_id"] is not None

    state = _load_state(
        order_id=order["id"],
        sale_id=settlement["sale_id"],
        intent_id=settlement["intent_id"],
    )

    assert state["order"]["status"] == "receivable"
    assert state["sale"]["status"] == "pending_payment"
    assert state["intent"]["status"] == "processing"
    assert Decimal(str(state["intent"]["amount"])) == ORDER_TOTAL
    assert Decimal(str(state["intent"]["total_paid"])) == Decimal("1000")
    assert Decimal(str(state["intent"]["balance_due"])) == Decimal("2500")

    assert len(state["attempts"]) == 1
    assert state["attempts"][0]["method"] == "cash"
    assert state["attempts"][0]["status"] == "succeeded"
    assert Decimal(str(state["attempts"][0]["amount"])) == Decimal("1000")

    assert state["receivable"]["status"] == "partial"
    assert Decimal(str(state["receivable"]["original_amount"])) == ORDER_TOTAL
    assert Decimal(str(state["receivable"]["paid_amount"])) == Decimal("1000")
    assert Decimal(str(state["receivable"]["balance_due"])) == Decimal("2500")

    assert [event["event_type"] for event in state["sale_events"]] == [
        "SALE_REVENUE_GROSS",
        "DEBT_CREATED",
    ]
    assert Decimal(str(state["sale_events"][0]["amount"])) == ORDER_TOTAL
    assert Decimal(str(state["sale_events"][1]["amount"])) == Decimal("2500")
    assert state["sale_events"][1]["channel"] == "ar"
    assert state["sale_events"][1]["direction"] == "debit"
    assert state["sale_events"][1]["reference_type"] == "sale"

    assert [event["event_type"] for event in state["attempt_events"]] == [
        "PAYMENT_RECEIVED"
    ]
    assert state["attempt_events"][0]["channel"] == "cash"
    assert Decimal(str(state["attempt_events"][0]["amount"])) == Decimal("1000")

    receipt_response = client.get(
        f"/kernel/payments/receipts/{settlement['sale_id']}",
        headers=auth_headers,
    )

    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()
    assert receipt["status"] == "processing"
    assert Decimal(str(receipt["total_paid"])) == Decimal("1000")
    assert Decimal(str(receipt["balance_due"])) == Decimal("2500")
    assert len(receipt["payments"]) == 1


def test_fully_unpaid_order_creates_full_receivable(
    client,
    auth_headers,
):
    order = _create_order(client, auth_headers)

    settlement = _settle_order(
        client,
        auth_headers,
        order_id=order["id"],
        lines=[
            {
                "method": "unpaid",
                "amount": float(ORDER_TOTAL),
                "meta": {
                    "note": "Fully unpaid characterization",
                },
            }
        ],
        tendered_total=0,
        unpaid_amount=float(ORDER_TOTAL),
    )

    assert Decimal(str(settlement["total_paid"])) == Decimal("0")
    assert Decimal(str(settlement["balance_due"])) == ORDER_TOTAL
    assert settlement["ar_id"] is not None

    state = _load_state(
        order_id=order["id"],
        sale_id=settlement["sale_id"],
        intent_id=settlement["intent_id"],
    )

    assert state["order"]["status"] == "receivable"
    assert state["sale"]["status"] == "pending_payment"
    assert state["intent"]["status"] == "pending"
    assert Decimal(str(state["intent"]["total_paid"])) == Decimal("0")
    assert Decimal(str(state["intent"]["balance_due"])) == ORDER_TOTAL

    assert state["attempts"] == []
    assert state["attempt_events"] == []

    assert state["receivable"]["status"] == "open"
    assert Decimal(str(state["receivable"]["original_amount"])) == ORDER_TOTAL
    assert Decimal(str(state["receivable"]["paid_amount"])) == Decimal("0")
    assert Decimal(str(state["receivable"]["balance_due"])) == ORDER_TOTAL

    assert [event["event_type"] for event in state["sale_events"]] == [
        "SALE_REVENUE_GROSS",
        "DEBT_CREATED",
    ]
    assert Decimal(str(state["sale_events"][0]["amount"])) == ORDER_TOTAL
    assert Decimal(str(state["sale_events"][1]["amount"])) == ORDER_TOTAL
    assert state["sale_events"][1]["channel"] == "ar"
    assert state["sale_events"][1]["direction"] == "debit"
    assert state["sale_events"][1]["reference_type"] == "sale"

    receipt_response = client.get(
        f"/kernel/payments/receipts/{settlement['sale_id']}",
        headers=auth_headers,
    )

    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()
    assert receipt["status"] == "pending"
    assert Decimal(str(receipt["total_paid"])) == Decimal("0")
    assert Decimal(str(receipt["balance_due"])) == ORDER_TOTAL
    assert receipt["payments"] == []