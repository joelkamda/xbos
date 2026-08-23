from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session


BUSINESS_TIMEZONE_NAME = "Africa/Douala"
BUSINESS_TZ = ZoneInfo(BUSINESS_TIMEZONE_NAME)


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _f(value: Any) -> float:
    return float(_d(value))


def _iso(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _month_bounds(yyyymm: str) -> tuple[datetime, datetime]:
    raw = str(yyyymm or "").strip()
    try:
        year_s, month_s = raw.split("-", 1)
        year = int(year_s)
        month = int(month_s)
    except Exception as exc:
        raise ValueError("month must be YYYY-MM") from exc

    if month < 1 or month > 12:
        raise ValueError("month must be YYYY-MM")

    start_local = datetime(year, month, 1, tzinfo=BUSINESS_TZ)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=BUSINESS_TZ)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=BUSINESS_TZ)

    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


class OperationalReportsService:
    """
    Track A read-only operational reporting facade.

    Financial/event authorities remain in their canonical domain tables:
    - Payments lifecycle: payment_intents + payment_attempts.
    - Posted money effects: treasury_logs.
    - Reconciliation history: recon_sheets.
    - Debt/A/R: accounts_receivable + accounts_receivable_repayments.

    This service never creates, closes, settles, allocates, or rewrites them.
    """

    @staticmethod
    def payment_report(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        month: str,
    ) -> Dict[str, Any]:
        start, end = _month_bounds(month)
        scope = {
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "start": start,
            "end": end,
        }

        status_rows = db.execute(
            text(
                """
                SELECT
                  status,
                  COUNT(*) AS row_count,
                  COALESCE(SUM(amount),0) AS amount,
                  COALESCE(SUM(total_paid),0) AS total_paid,
                  COALESCE(SUM(balance_due),0) AS balance_due
                FROM payment_intents
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                  AND created_at >= :start
                  AND created_at < :end
                GROUP BY status
                ORDER BY status
                """
            ),
            scope,
        ).mappings().all()

        channel_rows = db.execute(
            text(
                """
                SELECT
                  COALESCE(channel,'unknown') AS channel,
                  COUNT(*) AS row_count,
                  COALESCE(SUM(total_paid),0) AS total_paid,
                  COALESCE(SUM(balance_due),0) AS balance_due
                FROM payment_intents
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                  AND created_at >= :start
                  AND created_at < :end
                GROUP BY 1
                ORDER BY total_paid DESC, channel
                """
            ),
            scope,
        ).mappings().all()

        attempt_rows = db.execute(
            text(
                """
                SELECT
                  COALESCE(a.provider,'manual') AS provider,
                  COALESCE(a.method,'unknown') AS method,
                  COALESCE(a.status,'unknown') AS status,
                  COUNT(*) AS row_count,
                  COALESCE(SUM(a.amount),0) AS amount
                FROM payment_attempts a
                JOIN payment_intents i ON i.id = a.payment_intent_id
                WHERE i.tenant_id=:tenant_id
                  AND i.branch_id=:branch_id
                  AND a.created_at >= :start
                  AND a.created_at < :end
                GROUP BY 1,2,3
                ORDER BY row_count DESC, provider, method, status
                """
            ),
            scope,
        ).mappings().all()

        unresolved_rows = db.execute(
            text(
                """
                SELECT
                  id, payable_type, payable_id, currency, amount, status,
                  channel, total_paid, balance_due, created_at, updated_at
                FROM payment_intents
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                  AND created_at >= :start
                  AND created_at < :end
                  AND status IN ('pending','processing','failed','cancelled')
                ORDER BY created_at DESC, id DESC
                LIMIT 100
                """
            ),
            scope,
        ).mappings().all()

        effect_rows = db.execute(
            text(
                """
                SELECT
                  event_type,
                  COALESCE(channel,'unknown') AS channel,
                  COUNT(*) AS row_count,
                  COALESCE(SUM(amount),0) AS amount
                FROM treasury_logs
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                  AND occurred_at >= :start
                  AND occurred_at < :end
                  AND event_type IN (
                    'PAYMENT_RECEIVED',
                    'DEBT_REPAYMENT',
                    'OTHER_INCOME',
                    'SERVICE_REVENUE',
                    'EXPENSE_POSTED',
                    'REFUND_PAID',
                    'CASH_MOVE'
                  )
                GROUP BY event_type, COALESCE(channel,'unknown')
                ORDER BY event_type, amount DESC
                """
            ),
            scope,
        ).mappings().all()

        status_summary: Dict[str, Dict[str, float | int]] = {}
        total_intents = 0
        succeeded_intents = 0
        attention_intents = 0
        succeeded_paid = Decimal("0")
        unresolved_balance = Decimal("0")

        for row in status_rows:
            status = str(row["status"] or "unknown").lower()
            count = int(row["row_count"])
            paid = _d(row["total_paid"])
            balance = _d(row["balance_due"])
            total_intents += count

            if status == "succeeded":
                succeeded_intents += count
                succeeded_paid += paid
            if status in {"pending", "processing", "failed", "cancelled"}:
                attention_intents += count
                unresolved_balance += balance

            status_summary[status] = {
                "count": count,
                "amount": _f(row["amount"]),
                "total_paid": _f(paid),
                "balance_due": _f(balance),
            }

        posted_received = Decimal("0")
        posted_paid_out = Decimal("0")
        transferred = Decimal("0")
        posted_effects: List[Dict[str, Any]] = []

        inbound_types = {
            "PAYMENT_RECEIVED",
            "DEBT_REPAYMENT",
            "OTHER_INCOME",
            "SERVICE_REVENUE",
        }
        outbound_types = {"EXPENSE_POSTED", "REFUND_PAID"}

        for row in effect_rows:
            event_type = str(row["event_type"])
            amount = _d(row["amount"])
            if event_type in inbound_types:
                posted_received += amount
            elif event_type in outbound_types:
                posted_paid_out += amount
            elif event_type == "CASH_MOVE":
                transferred += amount

            posted_effects.append(
                {
                    "event_type": event_type,
                    "channel": row["channel"],
                    "count": int(row["row_count"]),
                    "amount": _f(amount),
                }
            )

        return {
            "month": month,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "business_timezone": BUSINESS_TIMEZONE_NAME,
            },
            "summary": {
                "intents": total_intents,
                "succeeded_intents": succeeded_intents,
                "attention_intents": attention_intents,
                "succeeded_paid": _f(succeeded_paid),
                "unresolved_balance": _f(unresolved_balance),
                "posted_received": _f(posted_received),
                "posted_paid_out": _f(posted_paid_out),
                "transferred": _f(transferred),
            },
            "status_summary": status_summary,
            "channels": [
                {
                    "channel": row["channel"],
                    "count": int(row["row_count"]),
                    "total_paid": _f(row["total_paid"]),
                    "balance_due": _f(row["balance_due"]),
                }
                for row in channel_rows
            ],
            "attempts": [
                {
                    "provider": row["provider"],
                    "method": row["method"],
                    "status": row["status"],
                    "count": int(row["row_count"]),
                    "amount": _f(row["amount"]),
                }
                for row in attempt_rows
            ],
            "unresolved": [
                {
                    "id": int(row["id"]),
                    "payable_type": row["payable_type"],
                    "payable_id": row["payable_id"],
                    "currency": row["currency"],
                    "amount": _f(row["amount"]),
                    "status": row["status"],
                    "channel": row["channel"],
                    "total_paid": _f(row["total_paid"]),
                    "balance_due": _f(row["balance_due"]),
                    "created_at": _iso(row["created_at"]),
                    "updated_at": _iso(row["updated_at"]),
                }
                for row in unresolved_rows
            ],
            "posted_effects": posted_effects,
            "rules": {
                "intent_status_is_operational_not_income": True,
                "posted_money_effects_source": "treasury_logs",
                "payment_received_is_money_movement_not_revenue": True,
                "cash_move_pl_effect": 0,
            },
        }

    @staticmethod
    def reconciliation_report(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        month: str,
    ) -> Dict[str, Any]:
        start, end = _month_bounds(month)
        rows = db.execute(
            text(
                """
                SELECT
                  id, shift, window_start, window_end, channel,
                  opening_amount, income_amount, expense_amount,
                  cash_in_amount, cash_out_amount,
                  expected_closing_amount, actual_closing_amount,
                  variance_amount, note, status,
                  closed_at, approved_at, created_at, updated_at
                FROM recon_sheets
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                  AND window_start >= :start
                  AND window_start < :end
                ORDER BY window_start DESC, shift, channel
                """
            ),
            {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "start": start,
                "end": end,
            },
        ).mappings().all()

        grouped: Dict[tuple[Any, Any, str], List[Any]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    row["window_start"],
                    row["window_end"],
                    str(row["shift"] or "full24"),
                )
            ].append(row)

        status_rank = {
            "approved": 4,
            "closed": 3,
            "reopened": 2,
            "draft": 1,
        }

        windows = []
        status_counts: Dict[str, int] = defaultdict(int)
        variance_windows = 0
        total_abs_variance = Decimal("0")

        for (window_start, window_end, shift), channel_rows in sorted(
            grouped.items(),
            key=lambda item: item[0][0],
            reverse=True,
        ):
            statuses = [
                str(row["status"] or "draft").lower()
                for row in channel_rows
            ]
            status = max(
                statuses,
                key=lambda value: status_rank.get(value, 0),
                default="draft",
            )
            status_counts[status] += 1

            abs_variance = sum(
                (abs(_d(row["variance_amount"])) for row in channel_rows),
                Decimal("0"),
            )
            if abs_variance != 0:
                variance_windows += 1
            total_abs_variance += abs_variance

            start_local = window_start.astimezone(BUSINESS_TZ)
            closed_candidates = [
                row["approved_at"] or row["closed_at"]
                for row in channel_rows
                if row["approved_at"] or row["closed_at"]
            ]

            windows.append(
                {
                    "business_date": start_local.date().isoformat(),
                    "shift": shift,
                    "status": status,
                    "window_start": _iso(window_start),
                    "window_end": _iso(window_end),
                    "closed_at": _iso(max(closed_candidates)) if closed_candidates else None,
                    "channel_count": len(channel_rows),
                    "absolute_variance": _f(abs_variance),
                    "variance_channels": sum(
                        1
                        for row in channel_rows
                        if _d(row["variance_amount"]) != 0
                    ),
                    "channels": [
                        {
                            "channel": row["channel"],
                            "opening": _f(row["opening_amount"]),
                            "income": _f(row["income_amount"]),
                            "expense": _f(row["expense_amount"]),
                            "cash_in": _f(row["cash_in_amount"]),
                            "cash_out": _f(row["cash_out_amount"]),
                            "expected": _f(row["expected_closing_amount"]),
                            "actual": _f(row["actual_closing_amount"]),
                            "variance": _f(row["variance_amount"]),
                            "note": row["note"] or "",
                            "status": row["status"],
                        }
                        for row in sorted(
                            channel_rows,
                            key=lambda item: str(item["channel"] or ""),
                        )
                    ],
                }
            )

        return {
            "month": month,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "business_timezone": BUSINESS_TIMEZONE_NAME,
            },
            "summary": {
                "windows": len(windows),
                "closed": status_counts.get("closed", 0),
                "approved": status_counts.get("approved", 0),
                "draft": status_counts.get("draft", 0),
                "reopened": status_counts.get("reopened", 0),
                "variance_windows": variance_windows,
                "absolute_variance": _f(total_abs_variance),
                "channel_rows": len(rows),
            },
            "windows": windows,
            "rules": {
                "source_of_truth": "recon_sheets",
                "read_only": True,
                "does_not_close_or_recompute_windows": True,
                "variance_is_persisted_variance": True,
            },
        }

    @staticmethod
    def debt_report(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
    ) -> Dict[str, Any]:
        ar_rows = db.execute(
            text(
                """
                SELECT
                  id, order_id, sale_id, payment_intent_id,
                  customer_name, customer_phone, note,
                  original_amount, paid_amount, balance_due, status,
                  created_at, updated_at, settled_at
                FROM accounts_receivable
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                ORDER BY balance_due DESC, created_at ASC, id ASC
                """
            ),
            {"tenant_id": tenant_id, "branch_id": branch_id},
        ).mappings().all()

        repayment_rows = db.execute(
            text(
                """
                SELECT
                  id, ar_id, amount, payment_method,
                  reference, note, created_at
                FROM accounts_receivable_repayments
                WHERE tenant_id=:tenant_id
                  AND branch_id=:branch_id
                ORDER BY created_at DESC, id DESC
                """
            ),
            {"tenant_id": tenant_id, "branch_id": branch_id},
        ).mappings().all()

        repayments_by_ar: Dict[int, List[Any]] = defaultdict(list)
        for row in repayment_rows:
            repayments_by_ar[int(row["ar_id"])].append(row)

        now_local = datetime.now(timezone.utc).astimezone(BUSINESS_TZ)

        aging_defs = [
            ("0-30", 0, 30),
            ("31-60", 31, 60),
            ("61-90", 61, 90),
            ("91+", 91, None),
        ]
        aging = {
            key: {"count": 0, "amount": Decimal("0")}
            for key, _, _ in aging_defs
        }

        status_counts: Dict[str, int] = defaultdict(int)
        original_total = Decimal("0")
        paid_total = Decimal("0")
        outstanding_total = Decimal("0")
        items = []
        customer_rollup: Dict[tuple[str, str], Dict[str, Any]] = {}

        for row in ar_rows:
            ar_id = int(row["id"])
            status = str(row["status"] or "open").lower()
            status_counts[status] += 1

            original = _d(row["original_amount"])
            paid = _d(row["paid_amount"])
            balance = _d(row["balance_due"])
            original_total += original
            paid_total += paid
            outstanding_total += balance

            created_at = row["created_at"]
            created_local = created_at.astimezone(BUSINESS_TZ)
            age_days = max((now_local.date() - created_local.date()).days, 0)

            if balance > 0:
                for key, low, high in aging_defs:
                    if age_days >= low and (high is None or age_days <= high):
                        aging[key]["count"] += 1
                        aging[key]["amount"] += balance
                        break

            repayments = repayments_by_ar.get(ar_id, [])
            last_repayment = repayments[0] if repayments else None

            customer_name = str(row["customer_name"] or "Unspecified customer")
            customer_phone = str(row["customer_phone"] or "")
            customer_key = (customer_name, customer_phone)
            customer = customer_rollup.setdefault(
                customer_key,
                {
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "accounts": 0,
                    "outstanding": Decimal("0"),
                    "original": Decimal("0"),
                    "paid": Decimal("0"),
                },
            )
            customer["accounts"] += 1
            customer["outstanding"] += balance
            customer["original"] += original
            customer["paid"] += paid

            items.append(
                {
                    "id": ar_id,
                    "order_id": row["order_id"],
                    "sale_id": row["sale_id"],
                    "payment_intent_id": row["payment_intent_id"],
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "note": row["note"] or "",
                    "original_amount": _f(original),
                    "paid_amount": _f(paid),
                    "balance_due": _f(balance),
                    "status": status,
                    "created_at": _iso(created_at),
                    "updated_at": _iso(row["updated_at"]),
                    "settled_at": _iso(row["settled_at"]),
                    "age_days": age_days,
                    "repayment_count": len(repayments),
                    "last_repayment_at": _iso(last_repayment["created_at"]) if last_repayment else None,
                    "last_repayment_amount": _f(last_repayment["amount"]) if last_repayment else 0.0,
                }
            )

        repayment_total = sum(
            (_d(row["amount"]) for row in repayment_rows),
            Decimal("0"),
        )

        customer_summary = sorted(
            (
                {
                    **value,
                    "outstanding": _f(value["outstanding"]),
                    "original": _f(value["original"]),
                    "paid": _f(value["paid"]),
                }
                for value in customer_rollup.values()
            ),
            key=lambda row: row["outstanding"],
            reverse=True,
        )

        return {
            "as_of": now_local.isoformat(),
            "business_timezone": BUSINESS_TIMEZONE_NAME,
            "summary": {
                "accounts": len(ar_rows),
                "open": status_counts.get("open", 0),
                "partial": status_counts.get("partial", 0),
                "settled": status_counts.get("settled", 0),
                "original_amount": _f(original_total),
                "paid_amount": _f(paid_total),
                "outstanding": _f(outstanding_total),
                "repayment_count": len(repayment_rows),
                "repayment_total": _f(repayment_total),
            },
            "aging": [
                {
                    "bucket": key,
                    "count": value["count"],
                    "amount": _f(value["amount"]),
                }
                for key, value in aging.items()
            ],
            "accounts": items,
            "customers": customer_summary[:50],
            "recent_repayments": [
                {
                    "id": int(row["id"]),
                    "ar_id": int(row["ar_id"]),
                    "amount": _f(row["amount"]),
                    "payment_method": row["payment_method"],
                    "reference": row["reference"] or "",
                    "note": row["note"] or "",
                    "created_at": _iso(row["created_at"]),
                }
                for row in repayment_rows[:100]
            ],
            "rules": {
                "source_of_truth": "accounts_receivable",
                "outstanding_is_persisted_balance_due": True,
                "aging_basis": "accounts_receivable.created_at",
                "treasury_event_subtraction_used": False,
            },
        }
