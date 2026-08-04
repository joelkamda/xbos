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
ORANGE_REPAYMENT = Decimal("1000.00")
BANK_REPAYMENT = Decimal("2500.00")


def _create_fully_unpaid_sale(client, auth_headers):
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
    assert Decimal(str(order["total"])) == ORDER_TOTAL
    assert order["status"] == "pending_payment"

    settlement_response = client.post(
        "/kernel/payments/pos/settle",
        headers=auth_headers,
        json={
            "order_id": order["id"],
            "client_reference": f"b1-ar-source-{uuid4().hex}",
            "lines": [
                {
                    "method": "unpaid",
                    "amount": float(ORDER_TOTAL),
                    "meta": {
                        "note": "A/R repayment characterization source",
                    },
                }
            ],
            "tendered_total": 0,
            "change_amount": 0,
            "change_given_now": 0,
            "tip_amount": 0,
            "unpaid_amount": float(ORDER_TOTAL),
            "receipt_meta": {
                "description": "Track B A/R repayment characterization",
                "customer": {
                    "name": "Track B Repayment Debtor",
                    "phone": "000000000",
                },
                "note": "Test database only",
            },
        },
    )

    assert settlement_response.status_code == 200, settlement_response.text

    settlement = settlement_response.json()
    assert Decimal(str(settlement["total_paid"])) == Decimal("0")
    assert Decimal(str(settlement["balance_due"])) == ORDER_TOTAL
    assert settlement["ar_id"] is not None

    return {
        "order_id": order["id"],
        "sale_id": settlement["sale_id"],
        "intent_id": settlement["intent_id"],
        "ar_id": settlement["ar_id"],
    }


def _repay(
    client,
    auth_headers,
    *,
    ar_id,
    amount,
    payment_method,
    client_reference,
):
    response = client.post(
        f"/kernel/accounting/accounts/ar/{ar_id}/repay",
        headers=auth_headers,
        json={
            "amount": float(amount),
            "payment_method": payment_method,
            "reference": f"track-b-{payment_method}-reference",
            "note": "Track B A/R repayment characterization",
            "client_reference": client_reference,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    return response.json()["account"]


def _load_financial_state(*, order_id, sale_id, intent_id, ar_id):
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
                    SELECT status, total, tendered_total,
                           unpaid_amount, order_id
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
                    SELECT status, amount, total_paid,
                           balance_due, payable_type, payable_id
                    FROM payment_intents
                    WHERE id = :intent_id
                    """
                ),
                {"intent_id": intent_id},
            )
            .mappings()
            .one()
        )

        receivable = (
            db.execute(
                text(
                    """
                    SELECT status, original_amount, paid_amount,
                           balance_due, settled_at
                    FROM accounts_receivable
                    WHERE id = :ar_id
                    """
                ),
                {"ar_id": ar_id},
            )
            .mappings()
            .one()
        )

        repayments = (
            db.execute(
                text(
                    """
                    SELECT id, amount, payment_method, reference,
                           note, created_by_user_id
                    FROM accounts_receivable_repayments
                    WHERE ar_id = :ar_id
                    ORDER BY id
                    """
                ),
                {"ar_id": ar_id},
            )
            .mappings()
            .all()
        )

        attempts = (
            db.execute(
                text(
                    """
                    SELECT id, method, provider, settlement_mode,
                           amount, status, client_reference, cashier_id
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

        repayment_ids = [repayment["id"] for repayment in repayments]
        repayment_events = []

        if repayment_ids:
            repayment_events = (
                db.execute(
                    text(
                        """
                        SELECT event_type, amount, channel, direction,
                               reference_type, reference_id, meta
                        FROM treasury_logs
                        WHERE reference_type = 'debt_repayment'
                          AND reference_id = ANY(:repayment_ids)
                        ORDER BY id
                        """
                    ),
                    {"repayment_ids": repayment_ids},
                )
                .mappings()
                .all()
            )

        attempt_ids = [attempt["id"] for attempt in attempts]
        payment_received_count = 0

        if attempt_ids:
            payment_received_count = db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM treasury_logs
                    WHERE event_type = 'PAYMENT_RECEIVED'
                      AND reference_type = 'payment_attempt'
                      AND reference_id = ANY(:attempt_ids)
                    """
                ),
                {"attempt_ids": attempt_ids},
            ).scalar_one()

        sale_events = (
            db.execute(
                text(
                    """
                    SELECT event_type, amount, channel
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

        return {
            "order": order_row,
            "sale": sale_row,
            "intent": intent_row,
            "receivable": receivable,
            "repayments": repayments,
            "attempts": attempts,
            "repayment_events": repayment_events,
            "payment_received_count": payment_received_count,
            "sale_events": sale_events,
        }
    finally:
        db.close()


def test_ar_repayment_is_idempotent_transfer_and_synchronizes_payment_truth(
    client,
    auth_headers,
    wnd_test_identity,
):
    source = _create_fully_unpaid_sale(client, auth_headers)

    orange_client_reference = f"b1-ar-orange-{uuid4().hex}"
    partial_account = _repay(
        client,
        auth_headers,
        ar_id=source["ar_id"],
        amount=ORANGE_REPAYMENT,
        payment_method="orange",
        client_reference=orange_client_reference,
    )

    assert partial_account["status"] == "partial"
    assert Decimal(str(partial_account["original_amount"])) == ORDER_TOTAL
    assert Decimal(str(partial_account["paid_amount"])) == ORANGE_REPAYMENT
    assert Decimal(str(partial_account["balance_due"])) == BANK_REPAYMENT
    assert len(partial_account["repayments"]) == 1
    assert partial_account["repayments"][0]["payment_method"] == "orange"
    assert Decimal(
        str(partial_account["repayments"][0]["amount"])
    ) == ORANGE_REPAYMENT
    assert (
        partial_account["repayments"][0]["created_by_user_id"]
        == wnd_test_identity["user_id"]
    )

    replayed_account = _repay(
        client,
        auth_headers,
        ar_id=source["ar_id"],
        amount=ORANGE_REPAYMENT,
        payment_method="orange",
        client_reference=orange_client_reference,
    )

    assert replayed_account["status"] == "partial"
    assert Decimal(str(replayed_account["paid_amount"])) == ORANGE_REPAYMENT
    assert Decimal(str(replayed_account["balance_due"])) == BANK_REPAYMENT
    assert len(replayed_account["repayments"]) == 1

    partial_state = _load_financial_state(**source)

    assert partial_state["order"]["status"] == "receivable"
    assert partial_state["sale"]["status"] == "pending_payment"
    assert partial_state["intent"]["status"] == "processing"
    assert Decimal(str(partial_state["intent"]["total_paid"])) == ORANGE_REPAYMENT
    assert Decimal(str(partial_state["intent"]["balance_due"])) == BANK_REPAYMENT
    assert len(partial_state["repayments"]) == 1
    assert len(partial_state["attempts"]) == 1
    assert len(partial_state["repayment_events"]) == 1
    assert partial_state["payment_received_count"] == 0

    bank_client_reference = f"b1-ar-bank-{uuid4().hex}"
    settled_account = _repay(
        client,
        auth_headers,
        ar_id=source["ar_id"],
        amount=BANK_REPAYMENT,
        payment_method="bank",
        client_reference=bank_client_reference,
    )

    assert settled_account["status"] == "settled"
    assert Decimal(str(settled_account["original_amount"])) == ORDER_TOTAL
    assert Decimal(str(settled_account["paid_amount"])) == ORDER_TOTAL
    assert Decimal(str(settled_account["balance_due"])) == Decimal("0")
    assert settled_account["settled_at"] is not None
    assert [
        repayment["payment_method"]
        for repayment in settled_account["repayments"]
    ] == ["bank", "orange"]

    state = _load_financial_state(**source)

    assert state["order"]["status"] == "paid"
    assert Decimal(str(state["order"]["total"])) == ORDER_TOTAL

    assert state["sale"]["status"] == "paid"
    assert Decimal(str(state["sale"]["total"])) == ORDER_TOTAL
    assert Decimal(str(state["sale"]["tendered_total"])) == ORDER_TOTAL
    assert Decimal(str(state["sale"]["unpaid_amount"])) == Decimal("0")
    assert state["sale"]["order_id"] == source["order_id"]

    assert state["intent"]["status"] == "succeeded"
    assert Decimal(str(state["intent"]["amount"])) == ORDER_TOTAL
    assert Decimal(str(state["intent"]["total_paid"])) == ORDER_TOTAL
    assert Decimal(str(state["intent"]["balance_due"])) == Decimal("0")
    assert state["intent"]["payable_type"] == "sale"
    assert state["intent"]["payable_id"] == source["sale_id"]

    assert state["receivable"]["status"] == "settled"
    assert Decimal(str(state["receivable"]["original_amount"])) == ORDER_TOTAL
    assert Decimal(str(state["receivable"]["paid_amount"])) == ORDER_TOTAL
    assert Decimal(str(state["receivable"]["balance_due"])) == Decimal("0")
    assert state["receivable"]["settled_at"] is not None

    assert [repayment["payment_method"] for repayment in state["repayments"]] == [
        "orange",
        "bank",
    ]
    assert [Decimal(str(repayment["amount"])) for repayment in state["repayments"]] == [
        ORANGE_REPAYMENT,
        BANK_REPAYMENT,
    ]

    assert [attempt["method"] for attempt in state["attempts"]] == [
        "orange",
        "bank",
    ]
    assert [attempt["provider"] for attempt in state["attempts"]] == [
        "orange",
        "bank",
    ]
    assert [attempt["settlement_mode"] for attempt in state["attempts"]] == [
        "ar_repayment",
        "ar_repayment",
    ]
    assert [attempt["status"] for attempt in state["attempts"]] == [
        "succeeded",
        "succeeded",
    ]
    assert [Decimal(str(attempt["amount"])) for attempt in state["attempts"]] == [
        ORANGE_REPAYMENT,
        BANK_REPAYMENT,
    ]
    assert all(
        attempt["cashier_id"] == wnd_test_identity["user_id"]
        for attempt in state["attempts"]
    )

    assert state["payment_received_count"] == 0
    assert [event["event_type"] for event in state["repayment_events"]] == [
        "DEBT_REPAYMENT",
        "DEBT_REPAYMENT",
    ]
    assert [event["channel"] for event in state["repayment_events"]] == [
        "orange",
        "bank",
    ]
    assert [event["direction"] for event in state["repayment_events"]] == [
        "credit",
        "credit",
    ]
    assert [
        Decimal(str(event["amount"])) for event in state["repayment_events"]
    ] == [ORANGE_REPAYMENT, BANK_REPAYMENT]
    assert all(
        event["reference_type"] == "debt_repayment"
        for event in state["repayment_events"]
    )
    assert [event["reference_id"] for event in state["repayment_events"]] == [
        repayment["id"] for repayment in state["repayments"]
    ]
    assert all(
        event["meta"]["source_channel"] == "ar"
        for event in state["repayment_events"]
    )
    assert [
        event["meta"]["target_channel"]
        for event in state["repayment_events"]
    ] == ["orange", "bank"]
    assert all(
        event["meta"]["movement_direction"] == "ar_repayment_transfer"
        for event in state["repayment_events"]
    )

    assert [event["event_type"] for event in state["sale_events"]] == [
        "SALE_REVENUE_GROSS",
        "DEBT_CREATED",
    ]
    assert Decimal(str(state["sale_events"][0]["amount"])) == ORDER_TOTAL
    assert Decimal(str(state["sale_events"][1]["amount"])) == ORDER_TOTAL

    receipt_response = client.get(
        f"/kernel/payments/receipts/{source['sale_id']}",
        headers=auth_headers,
    )

    assert receipt_response.status_code == 200, receipt_response.text

    receipt = receipt_response.json()
    assert receipt["status"] == "succeeded"
    assert Decimal(str(receipt["total_paid"])) == ORDER_TOTAL
    assert Decimal(str(receipt["balance_due"])) == Decimal("0")
    assert Decimal(str(receipt["unpaid_amount"])) == Decimal("0")
    assert [payment["method"] for payment in receipt["payments"]] == [
        "orange",
        "bank",
    ]
    assert [Decimal(str(payment["amount"])) for payment in receipt["payments"]] == [
        ORANGE_REPAYMENT,
        BANK_REPAYMENT,
    ]
