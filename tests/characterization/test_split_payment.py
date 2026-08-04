from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


ATOMIC_UNIT_ID = 19
EXPECTED_ITEM_NAME = "Shisha"
EXPECTED_TOTAL = Decimal("3500.00")
CASH_AMOUNT = Decimal("1000.00")
MTN_AMOUNT = Decimal("2500.00")


def test_cash_and_mtn_split_payment_settles_sale_and_receipt(
    client,
    auth_headers,
    wnd_test_identity,
):
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

    order_response = client.post(
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

    assert order_response.status_code == 200, order_response.text

    order = order_response.json()
    order_id = order["id"]

    assert Decimal(str(order["total"])) == EXPECTED_TOTAL
    assert order["status"] == "pending_payment"

    settlement_response = client.post(
        "/kernel/payments/pos/settle",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "client_reference": f"b1-split-cash-mtn-{uuid4().hex}",
            "lines": [
                {
                    "method": "cash",
                    "amount": float(CASH_AMOUNT),
                    "meta": {
                        "source": "track_b_characterization",
                    },
                },
                {
                    "method": "mtn",
                    "amount": float(MTN_AMOUNT),
                    "meta": {
                        "source": "track_b_characterization",
                    },
                },
            ],
            "tendered_total": float(EXPECTED_TOTAL),
            "change_amount": 0,
            "change_given_now": 0,
            "tip_amount": 0,
            "unpaid_amount": 0,
            "receipt_meta": {
                "description": "Track B cash and MTN split payment",
                "customer": {
                    "name": "Track B Split Customer",
                },
            },
        },
    )

    assert settlement_response.status_code == 200, settlement_response.text

    settlement = settlement_response.json()
    sale_id = settlement["sale_id"]
    intent_id = settlement["intent_id"]

    assert Decimal(str(settlement["total_paid"])) == EXPECTED_TOTAL
    assert Decimal(str(settlement["balance_due"])) == Decimal("0")
    assert settlement["ar_id"] is None

    receipt_response = client.get(
        f"/kernel/payments/receipts/{sale_id}",
        headers=auth_headers,
    )

    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()

    assert receipt["status"] == "succeeded"
    assert Decimal(str(receipt["gross_total"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["total"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["tendered_total"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["total_paid"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["balance_due"])) == Decimal("0")
    assert Decimal(str(receipt["unpaid_amount"])) == Decimal("0")
    assert receipt["order_id"] == order_id
    assert receipt["order_created_by_user_id"] == wnd_test_identity["user_id"]

    assert len(receipt["items"]) == 1
    assert receipt["items"][0]["name"] == EXPECTED_ITEM_NAME
    assert Decimal(str(receipt["items"][0]["line_total"])) == EXPECTED_TOTAL

    assert [payment["method"] for payment in receipt["payments"]] == [
        "cash",
        "mtn",
    ]
    assert [payment["status"] for payment in receipt["payments"]] == [
        "succeeded",
        "succeeded",
    ]
    assert [
        Decimal(str(payment["amount"])) for payment in receipt["payments"]
    ] == [CASH_AMOUNT, MTN_AMOUNT]

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

        ar_count = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM accounts_receivable
                WHERE order_id = :order_id
                """
            ),
            {"order_id": order_id},
        ).scalar_one()

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

        attempt_ids = [attempt["id"] for attempt in attempts]
        payment_events = (
            db.execute(
                text(
                    """
                    SELECT event_type, amount, channel,
                           direction, reference_type
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
    finally:
        db.close()

    assert order_row["status"] == "paid"
    assert Decimal(str(order_row["total"])) == EXPECTED_TOTAL

    assert sale_row["status"] == "paid"
    assert Decimal(str(sale_row["total"])) == EXPECTED_TOTAL
    assert sale_row["order_id"] == order_id

    assert intent_row["status"] == "succeeded"
    assert Decimal(str(intent_row["amount"])) == EXPECTED_TOTAL
    assert Decimal(str(intent_row["total_paid"])) == EXPECTED_TOTAL
    assert Decimal(str(intent_row["balance_due"])) == Decimal("0")

    assert [attempt["method"] for attempt in attempts] == ["cash", "mtn"]
    assert [attempt["status"] for attempt in attempts] == [
        "succeeded",
        "succeeded",
    ]
    assert [Decimal(str(attempt["amount"])) for attempt in attempts] == [
        CASH_AMOUNT,
        MTN_AMOUNT,
    ]
    assert ar_count == 0

    assert [event["event_type"] for event in sale_events] == [
        "SALE_REVENUE_GROSS"
    ]
    assert Decimal(str(sale_events[0]["amount"])) == EXPECTED_TOTAL
    assert sale_events[0]["direction"] == "credit"
    assert sale_events[0]["reference_type"] == "sale"

    assert [event["event_type"] for event in payment_events] == [
        "PAYMENT_RECEIVED",
        "PAYMENT_RECEIVED",
    ]
    assert [event["channel"] for event in payment_events] == ["cash", "mtn"]
    assert [Decimal(str(event["amount"])) for event in payment_events] == [
        CASH_AMOUNT,
        MTN_AMOUNT,
    ]
    assert [event["direction"] for event in payment_events] == [
        "credit",
        "credit",
    ]
    assert all(
        event["reference_type"] == "payment_attempt"
        for event in payment_events
    )
