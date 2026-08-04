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


def test_full_cash_payment_and_duplicate_settlement_are_idempotent(
    client,
    auth_headers,
    wnd_test_identity,
):
    from database import SessionLocal

    db = SessionLocal()

    try:
        db.execute(
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

    order_body = order_response.json()
    order_id = order_body["id"]

    assert Decimal(str(order_body["total"])) == EXPECTED_TOTAL
    assert order_body["status"] == "pending_payment"

    settlement_reference = f"b1-full-cash-{uuid4().hex}"

    settlement_payload = {
        "order_id": order_id,
        "client_reference": settlement_reference,
        "lines": [
            {
                "method": "cash",
                "amount": float(EXPECTED_TOTAL),
                "meta": {
                    "source": "track_b_characterization",
                },
            }
        ],
        "tendered_total": float(EXPECTED_TOTAL),
        "change_amount": 0,
        "change_given_now": 0,
        "tip_amount": 0,
        "unpaid_amount": 0,
        "receipt_meta": {
            "description": "Track B full cash payment",
            "customer": {
                "name": "Track B Test Customer",
            },
        },
    }

    settlement_response = client.post(
        "/kernel/payments/pos/settle",
        headers=auth_headers,
        json=settlement_payload,
    )

    assert settlement_response.status_code == 200, settlement_response.text

    settlement_body = settlement_response.json()
    sale_id = settlement_body["sale_id"]
    intent_id = settlement_body["intent_id"]

    assert Decimal(str(settlement_body["total_paid"])) == EXPECTED_TOTAL
    assert Decimal(str(settlement_body["balance_due"])) == Decimal("0")
    assert settlement_body["ar_id"] is None

    receipt_response = client.get(
        f"/kernel/payments/receipts/{sale_id}",
        headers=auth_headers,
    )

    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()

    assert Decimal(str(receipt["gross_total"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["total"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["tendered_total"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["total_paid"])) == EXPECTED_TOTAL
    assert Decimal(str(receipt["balance_due"])) == Decimal("0")
    assert Decimal(str(receipt["unpaid_amount"])) == Decimal("0")
    assert receipt["status"] == "succeeded"
    assert receipt["payable_type"] == "sale"
    assert int(receipt["payable_id"]) == sale_id
    assert receipt["order_id"] == order_id
    assert receipt["order_created_by_user_id"] == wnd_test_identity["user_id"]

    assert len(receipt["items"]) == 1
    assert receipt["items"][0]["name"] == EXPECTED_ITEM_NAME
    assert Decimal(str(receipt["items"][0]["line_total"])) == EXPECTED_TOTAL

    assert len(receipt["payments"]) == 1
    assert receipt["payments"][0]["method"] == "cash"
    assert receipt["payments"][0]["status"] == "succeeded"
    assert Decimal(str(receipt["payments"][0]["amount"])) == EXPECTED_TOTAL

    db = SessionLocal()

    try:
        order_row = (
            db.execute(
                text(
                    """
                    SELECT status, total, created_by_user_id
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
                    SELECT status, amount, total_paid, balance_due,
                           payable_type, payable_id
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
                    SELECT method, amount, status
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
    finally:
        db.close()

    assert order_row["status"] == "paid"
    assert Decimal(str(order_row["total"])) == EXPECTED_TOTAL
    assert order_row["created_by_user_id"] == wnd_test_identity["user_id"]

    assert sale_row["status"] == "paid"
    assert Decimal(str(sale_row["total"])) == EXPECTED_TOTAL
    assert sale_row["order_id"] == order_id

    assert intent_row["status"] == "succeeded"
    assert Decimal(str(intent_row["amount"])) == EXPECTED_TOTAL
    assert Decimal(str(intent_row["total_paid"])) == EXPECTED_TOTAL
    assert Decimal(str(intent_row["balance_due"])) == Decimal("0")
    assert intent_row["payable_type"] == "sale"
    assert intent_row["payable_id"] == sale_id

    assert len(attempts) == 1
    assert attempts[0]["method"] == "cash"
    assert attempts[0]["status"] == "succeeded"
    assert Decimal(str(attempts[0]["amount"])) == EXPECTED_TOTAL
    assert ar_count == 0

    replay_response = client.post(
        "/kernel/payments/pos/settle",
        headers=auth_headers,
        json=settlement_payload,
    )

    assert replay_response.status_code == 200, replay_response.text
    assert replay_response.json()["intent_id"] == intent_id
    assert replay_response.json()["sale_id"] == sale_id

    db = SessionLocal()

    try:
        attempt_count_after_replay = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM payment_attempts
                WHERE payment_intent_id = :intent_id
                """
            ),
            {"intent_id": intent_id},
        ).scalar_one()
    finally:
        db.close()

    assert attempt_count_after_replay == 1