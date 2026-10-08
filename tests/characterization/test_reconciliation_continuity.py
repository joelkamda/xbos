from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text


pytestmark = [
    pytest.mark.characterization,
    pytest.mark.integration,
]


RECONCILIATION_PATH = "/kernel/accounting/reconciliation"
RECONCILIATION_CLOSE_PATH = f"{RECONCILIATION_PATH}/close"
FUTURE_TEST_FLOOR = datetime(2099, 1, 1, tzinfo=timezone.utc)


WINDOW_1 = (
    "2099-01-01T08:00:00+00:00",
    "2099-01-02T08:00:00+00:00",
)
WINDOW_2 = (
    "2099-01-02T08:00:00+00:00",
    "2099-01-03T08:00:00+00:00",
)
WINDOW_3 = (
    "2099-01-03T08:00:00+00:00",
    "2099-01-04T08:00:00+00:00",
)


def _clear_future_reconciliation(wnd_test_identity):
    from database import SessionLocal

    db = SessionLocal()

    try:
        db.execute(
            text(
                """
                DELETE FROM recon_sheets
                WHERE tenant_id = :tenant_id
                  AND branch_id = :branch_id
                  AND window_start >= :future_test_floor
                """
            ),
            {
                "tenant_id": wnd_test_identity["tenant_id"],
                "branch_id": wnd_test_identity["branch_id"],
                "future_test_floor": FUTURE_TEST_FLOOR,
            },
        )
        db.commit()
    finally:
        db.close()


def _reconciliation_row(*, opening, actual, note):
    return {
        "channel": "cash",
        "opening": float(opening),
        "income": 0,
        "expense": 0,
        "cashIn": 0,
        "cashOut": 0,
        "expected": float(opening),
        "actual": float(actual),
        "variance": float(Decimal(str(actual)) - Decimal(str(opening))),
        "note": note,
    }


def _close_window(
    client,
    auth_headers,
    *,
    shift,
    window,
    opening,
    actual,
    note,
):
    response = client.post(
        RECONCILIATION_CLOSE_PATH,
        headers=auth_headers,
        json={
            "start": window[0],
            "end": window[1],
            "shift": shift,
            "rows": [
                _reconciliation_row(
                    opening=opening,
                    actual=actual,
                    note=note,
                )
            ],
        },
    )

    assert response.status_code == 200, response.text
    return response.json()


def _get_cash_row(client, auth_headers, *, shift, window):
    response = client.get(
        RECONCILIATION_PATH,
        headers=auth_headers,
        params={
            "start": window[0],
            "end": window[1],
            "shift": shift,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    cash_row = next(row for row in body["rows"] if row["channel"] == "cash")

    return body, cash_row


def test_same_window_close_is_upserted_and_adjacent_window_carries_latest_actual(
    client,
    auth_headers,
    wnd_test_identity,
):
    from database import SessionLocal

    _clear_future_reconciliation(wnd_test_identity)
    shift = f"b1-adj-{uuid4().hex[:8]}"

    first = _close_window(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_1,
        opening=0,
        actual=125,
        note="Initial close",
    )

    assert first["status"] == "closed"
    assert Decimal(str(first["rows"][0]["actual"])) == Decimal("125")

    replay = _close_window(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_1,
        opening=0,
        actual=130,
        note="Corrected same-window close",
    )

    assert Decimal(str(replay["rows"][0]["actual"])) == Decimal("130")

    db = SessionLocal()

    try:
        saved = (
            db.execute(
                text(
                    """
                    SELECT COUNT(*) AS row_count,
                           MAX(actual_closing_amount) AS actual_closing_amount
                    FROM recon_sheets
                    WHERE tenant_id = :tenant_id
                      AND branch_id = :branch_id
                      AND shift = :shift
                      AND window_start = :window_start
                      AND window_end = :window_end
                      AND channel = 'cash'
                    """
                ),
                {
                    "tenant_id": wnd_test_identity["tenant_id"],
                    "branch_id": wnd_test_identity["branch_id"],
                    "shift": shift,
                    "window_start": WINDOW_1[0],
                    "window_end": WINDOW_1[1],
                },
            )
            .mappings()
            .one()
        )
    finally:
        db.close()

    assert saved["row_count"] == 1
    assert Decimal(str(saved["actual_closing_amount"])) == Decimal("130")

    next_window, cash_row = _get_cash_row(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_2,
    )

    assert next_window["status"] == "draft"
    assert Decimal(str(cash_row["opening"])) == Decimal("130")
    assert Decimal(str(cash_row["expected"])) == Decimal("130")
    assert Decimal(str(cash_row["actual"])) == Decimal("0")
    assert Decimal(str(cash_row["variance"])) == Decimal("-130")


def test_non_adjacent_window_does_not_inherit_stale_prior_close(
    client,
    auth_headers,
    wnd_test_identity,
):
    _clear_future_reconciliation(wnd_test_identity)
    shift = f"b1-gap-{uuid4().hex[:8]}"

    _close_window(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_1,
        opening=0,
        actual=200,
        note="Closed before intentional gap",
    )

    skipped_window_view, cash_row = _get_cash_row(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_3,
    )

    assert skipped_window_view["status"] == "draft"
    assert Decimal(str(cash_row["opening"])) == Decimal("0")

def test_previous_closing_is_isolated_across_shift_names(
    client,
    auth_headers,
    wnd_test_identity,
):
    _clear_future_reconciliation(wnd_test_identity)
    first_shift = f"b1-src-{uuid4().hex[:8]}"
    unrelated_shift = f"b1-other-{uuid4().hex[:8]}"

    _close_window(
        client,
        auth_headers,
        shift=first_shift,
        window=WINDOW_1,
        opening=0,
        actual=400,
        note="Source shift close",
    )

    next_window, cash_row = _get_cash_row(
        client,
        auth_headers,
        shift=unrelated_shift,
        window=WINDOW_2,
    )

    assert next_window["status"] == "draft"
    assert Decimal(str(cash_row["opening"])) == Decimal("0")

def test_correcting_prior_close_cascades_projection_without_erasing_later_actual(
    client,
    auth_headers,
    wnd_test_identity,
):
    from database import SessionLocal

    _clear_future_reconciliation(wnd_test_identity)
    shift = f"b1-cascade-{uuid4().hex[:8]}"

    _close_window(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_1,
        opening=0,
        actual=100,
        note="Original first close",
    )

    _close_window(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_2,
        opening=100,
        actual=150,
        note="Persisted second close",
    )

    _close_window(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_1,
        opening=0,
        actual=250,
        note="Corrected first close",
    )

    second_window, cash_row = _get_cash_row(
        client,
        auth_headers,
        shift=shift,
        window=WINDOW_2,
    )

    assert second_window["status"] == "closed"
    assert Decimal(str(cash_row["opening"])) == Decimal("250")
    assert Decimal(str(cash_row["expected"])) == Decimal("250")
    assert Decimal(str(cash_row["actual"])) == Decimal("150")
    assert Decimal(str(cash_row["variance"])) == Decimal("-100")

    db = SessionLocal()
    try:
        persisted = (
            db.execute(
                text(
                    """
                    SELECT opening_amount, actual_closing_amount
                    FROM recon_sheets
                    WHERE tenant_id = :tenant_id
                      AND branch_id = :branch_id
                      AND shift = :shift
                      AND window_start = :window_start
                      AND window_end = :window_end
                      AND channel = 'cash'
                    """
                ),
                {
                    "tenant_id": wnd_test_identity["tenant_id"],
                    "branch_id": wnd_test_identity["branch_id"],
                    "shift": shift,
                    "window_start": WINDOW_2[0],
                    "window_end": WINDOW_2[1],
                },
            )
            .mappings()
            .one()
        )
    finally:
        db.close()

    assert Decimal(str(persisted["opening_amount"])) == Decimal("100")
    assert Decimal(str(persisted["actual_closing_amount"])) == Decimal("150")
