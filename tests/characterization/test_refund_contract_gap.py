from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


REFUND_AMOUNT = Decimal("750.00")


def test_legacy_api_has_no_refund_workflow(app):
    paths = app.openapi()["paths"]

    refund_paths = [path for path in paths if "refund" in path.lower()]
    void_paths = [path for path in paths if "void" in path.lower()]

    assert refund_paths == []
    assert void_paths == []

    # Legacy order cancellation exists, but it is not a refund substitute.
    assert "/kernel/orders/{order_id}/cancel" in paths


def test_dormant_refund_event_reuses_one_cash_out_row_last_write_wins(app):
    from core.domain.accounting.emitter import FinancialEventEmitter
    from database import SessionLocal

    refund_id = int(uuid4().int % 2_000_000_000) + 1

    db = SessionLocal()

    try:
        first_event = FinancialEventEmitter.refund_paid(
            db,
            tenant_id=2,
            branch_id=1,
            refund_id=refund_id,
            amount=REFUND_AMOUNT,
            currency="XAF",
            channel="orange",
            meta={
                "source": "track_b_characterization",
                "reason": "refund contract gap test",
            },
        )
        db.commit()

        assert first_event is not None

        replayed_event = FinancialEventEmitter.refund_paid(
            db,
            tenant_id=2,
            branch_id=1,
            refund_id=refund_id,
            amount=REFUND_AMOUNT,
            currency="XAF",
            channel="orange",
            meta={
                "source": "track_b_characterization_replay",
                "reason": "must not create a duplicate event",
            },
        )
        db.commit()

        assert replayed_event is not None

        events = (
            db.execute(
                text(
                    """
                    SELECT event_type, amount, currency, channel,
                           direction, reference_type, reference_id,
                           idempotency_key, meta
                    FROM treasury_logs
                    WHERE idempotency_key = :idempotency_key
                    ORDER BY id
                    """
                ),
                {"idempotency_key": f"refund:{refund_id}"},
            )
            .mappings()
            .all()
        )
    finally:
        db.close()

    assert len(events) == 1

    event = events[0]
    assert event["event_type"] == "REFUND_PAID"
    assert Decimal(str(event["amount"])) == REFUND_AMOUNT
    assert event["currency"] == "XAF"
    assert event["channel"] == "orange"
    assert event["direction"] == "debit"
    assert event["reference_type"] == "refund"
    assert event["reference_id"] == refund_id
    assert event["idempotency_key"] == f"refund:{refund_id}"
    assert event["meta"]["source_channel"] == "orange"
    assert event["meta"]["target_channel"] == "customer"
    assert event["meta"]["movement_direction"] == "refund_paid"
    # Legacy deduplication preserves one row, but replay metadata overwrites
    # the original payload instead of remaining immutable.
    assert event["meta"]["source"] == "track_b_characterization_replay"
    assert event["meta"]["reason"] == "must not create a duplicate event"
