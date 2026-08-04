from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


ATOMIC_UNIT_ID = 19
GROSS_TOTAL = Decimal("3500.00")
DISCOUNT_TOTAL = Decimal("500.00")
DISCOUNT_NET_TOTAL = Decimal("3000.00")
COMPLIMENTARY_TOTAL = GROSS_TOTAL


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

    order = response.json()
    assert Decimal(str(order["total"])) == GROSS_TOTAL
    assert order["status"] == "pending_payment"
    return order


def _settle_adjusted_order(
    client,
    auth_headers,
    *,
    order_id,
    net_total,
    discount_total=Decimal("0"),
    discount_reason=None,
    complimentary_total=Decimal("0"),
    complimentary_reason=None,
    complimentary_items=None,
):
    response = client.post(
        "/kernel/payments/pos/settle",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "client_reference": f"b1-adjustment-{uuid4().hex}",
            "lines": [
                {
                    "method": "cash",
                    "amount": float(net_total),
                    "meta": {
                        "source": "track_b_characterization",
                    },
                }
            ],
            "tendered_total": float(net_total),
            "change_amount": 0,
            "change_given_now": 0,
            "tip_amount": 0,
            "unpaid_amount": 0,
            "receipt_meta": {
                "description": "Track B sale adjustment characterization",
                "gross_total": float(GROSS_TOTAL),
                "discount_total": float(discount_total),
                "discount_reason": discount_reason,
                "complimentary_total": float(complimentary_total),
                "complimentary_reason": complimentary_reason,
                "complimentary_items": complimentary_items or [],
                "customer": {
                    "name": "Track B Adjustment Customer",
                },
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
                    SELECT status, subtotal, total, discount_total,
                           discount_reason, complimentary_total,
                           tendered_total, unpaid_amount, order_id
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
                    SELECT status, amount, total_paid, balance_due, meta
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

        sale_events = (
            db.execute(
                text(
                    """
                    SELECT event_type, amount, channel, direction,
                           reference_type, reference_id, meta
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

        payment_events = []
        attempt_ids = [attempt["id"] for attempt in attempts]

        if attempt_ids:
            payment_events = (
                db.execute(
                    text(
                        """
                        SELECT event_type, amount, channel, direction,
                               reference_type, reference_id
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

        return {
            "order": order_row,
            "sale": sale_row,
            "intent": intent_row,
            "attempts": attempts,
            "sale_events": sale_events,
            "payment_events": payment_events,
            "ar_count": ar_count,
        }
    finally:
        db.close()


def test_discount_reduces_net_payable_and_emits_non_cash_adjustment(
    client,
    auth_headers,
):
    order = _create_order(client, auth_headers)
    settlement = _settle_adjusted_order(
        client,
        auth_headers,
        order_id=order["id"],
        net_total=DISCOUNT_NET_TOTAL,
        discount_total=DISCOUNT_TOTAL,
        discount_reason="staff_discount",
    )

    assert Decimal(str(settlement["total_paid"])) == DISCOUNT_NET_TOTAL
    assert Decimal(str(settlement["balance_due"])) == Decimal("0")
    assert settlement["ar_id"] is None

    state = _load_state(
        order_id=order["id"],
        sale_id=settlement["sale_id"],
        intent_id=settlement["intent_id"],
    )

    assert state["order"]["status"] == "paid"
    assert Decimal(str(state["order"]["total"])) == GROSS_TOTAL
    assert state["sale"]["status"] == "paid"
    assert Decimal(str(state["sale"]["total"])) == GROSS_TOTAL
    assert state["sale"]["order_id"] == order["id"]

    assert state["intent"]["status"] == "succeeded"
    assert Decimal(str(state["intent"]["amount"])) == DISCOUNT_NET_TOTAL
    assert Decimal(str(state["intent"]["total_paid"])) == DISCOUNT_NET_TOTAL
    assert Decimal(str(state["intent"]["balance_due"])) == Decimal("0")
    assert Decimal(str(state["intent"]["meta"]["gross_total"])) == GROSS_TOTAL
    assert Decimal(
        str(state["intent"]["meta"]["discount_total"])
    ) == DISCOUNT_TOTAL
    assert state["intent"]["meta"]["discount_reason"] == "staff_discount"
    assert Decimal(
        str(state["intent"]["meta"]["complimentary_total"])
    ) == Decimal("0")

    assert len(state["attempts"]) == 1
    assert state["attempts"][0]["method"] == "cash"
    assert state["attempts"][0]["status"] == "succeeded"
    assert Decimal(str(state["attempts"][0]["amount"])) == DISCOUNT_NET_TOTAL
    assert state["ar_count"] == 0

    assert [event["event_type"] for event in state["sale_events"]] == [
        "SALE_REVENUE_GROSS",
        "DISCOUNT_APPLIED",
    ]
    assert Decimal(str(state["sale_events"][0]["amount"])) == GROSS_TOTAL
    assert Decimal(
        str(state["sale_events"][1]["amount"])
    ) == DISCOUNT_TOTAL
    assert state["sale_events"][1]["direction"] == "debit"
    assert state["sale_events"][1]["meta"]["allowance_type"] == "discount"
    assert (
        state["sale_events"][1]["meta"]["discount_reason"]
        == "staff_discount"
    )

    assert [event["event_type"] for event in state["payment_events"]] == [
        "PAYMENT_RECEIVED"
    ]
    assert state["payment_events"][0]["channel"] == "cash"
    assert Decimal(
        str(state["payment_events"][0]["amount"])
    ) == DISCOUNT_NET_TOTAL

    receipt_response = client.get(
        f"/kernel/payments/receipts/{settlement['sale_id']}",
        headers=auth_headers,
    )
    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()
    assert receipt["status"] == "succeeded"
    assert Decimal(str(receipt["gross_total"])) == GROSS_TOTAL
    assert Decimal(str(receipt["discount_total"])) == DISCOUNT_TOTAL
    assert Decimal(str(receipt["complimentary_total"])) == Decimal("0")
    assert Decimal(str(receipt["total"])) == DISCOUNT_NET_TOTAL
    assert Decimal(str(receipt["total_paid"])) == DISCOUNT_NET_TOTAL
    assert Decimal(str(receipt["balance_due"])) == Decimal("0")
    assert len(receipt["payments"]) == 1
    assert receipt["payments"][0]["method"] == "cash"


def test_fully_complimentary_sale_has_zero_collection_and_non_cash_event(
    client,
    auth_headers,
):
    order = _create_order(client, auth_headers)
    settlement = _settle_adjusted_order(
        client,
        auth_headers,
        order_id=order["id"],
        net_total=Decimal("0"),
        complimentary_total=COMPLIMENTARY_TOTAL,
        complimentary_reason="management_complimentary",
        complimentary_items=[
            {
                "atomic_unit_id": ATOMIC_UNIT_ID,
                "amount": float(COMPLIMENTARY_TOTAL),
            }
        ],
    )

    assert Decimal(str(settlement["total_paid"])) == Decimal("0")
    assert Decimal(str(settlement["balance_due"])) == Decimal("0")
    assert settlement["ar_id"] is None

    state = _load_state(
        order_id=order["id"],
        sale_id=settlement["sale_id"],
        intent_id=settlement["intent_id"],
    )

    assert state["order"]["status"] == "paid"
    assert Decimal(str(state["order"]["total"])) == GROSS_TOTAL
    assert state["sale"]["status"] == "paid"
    assert Decimal(str(state["sale"]["total"])) == GROSS_TOTAL

    assert state["intent"]["status"] == "succeeded"
    assert Decimal(str(state["intent"]["amount"])) == Decimal("0")
    assert Decimal(str(state["intent"]["total_paid"])) == Decimal("0")
    assert Decimal(str(state["intent"]["balance_due"])) == Decimal("0")
    assert Decimal(str(state["intent"]["meta"]["gross_total"])) == GROSS_TOTAL
    assert Decimal(
        str(state["intent"]["meta"]["complimentary_total"])
    ) == COMPLIMENTARY_TOTAL
    assert (
        state["intent"]["meta"]["complimentary_reason"]
        == "management_complimentary"
    )

    assert state["attempts"] == []
    assert state["payment_events"] == []
    assert state["ar_count"] == 0

    assert [event["event_type"] for event in state["sale_events"]] == [
        "SALE_REVENUE_GROSS",
        "COMPLIMENTARY_APPLIED",
    ]
    assert Decimal(str(state["sale_events"][0]["amount"])) == GROSS_TOTAL
    assert Decimal(
        str(state["sale_events"][1]["amount"])
    ) == COMPLIMENTARY_TOTAL
    assert state["sale_events"][1]["direction"] == "debit"
    assert (
        state["sale_events"][1]["meta"]["allowance_type"]
        == "complimentary"
    )
    assert (
        state["sale_events"][1]["meta"]["complimentary_reason"]
        == "management_complimentary"
    )

    receipt_response = client.get(
        f"/kernel/payments/receipts/{settlement['sale_id']}",
        headers=auth_headers,
    )
    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()
    assert receipt["status"] == "succeeded"
    assert Decimal(str(receipt["gross_total"])) == GROSS_TOTAL
    assert Decimal(str(receipt["discount_total"])) == Decimal("0")
    assert Decimal(
        str(receipt["complimentary_total"])
    ) == COMPLIMENTARY_TOTAL
    assert Decimal(str(receipt["total"])) == Decimal("0")
    assert Decimal(str(receipt["total_paid"])) == Decimal("0")
    assert Decimal(str(receipt["balance_due"])) == Decimal("0")
    assert receipt["payments"] == []
