from typing import Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.domain.accounting.repository import TreasuryRepository


def _f(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


class AccountingReportsService:
    """
    Shapes treasury ledger data into UI-ready report payloads.
    """

    INCOME_EVENTS = {
        "SALE_REVENUE_GROSS",
        "TIP_REVENUE",
        "SERVICE_REVENUE",
        "OTHER_INCOME",
    }

    EXPENSE_EVENTS = {
        "DISCOUNT_APPLIED",
        "COMPLIMENTARY_APPLIED",
        "EXPENSE_POSTED",
        "COGS_RECOGNIZED",
        "REFUND_PAID",
    }

    CASH_MOVE_EVENTS = {
        "PAYMENT_RECEIVED",
        "CASH_MOVE",
        "STORE_CREDIT_CREATED",
    }

    DEBT_EVENTS = {
        "DEBT_CREATED",
        "DEBT_REPAYMENT",
    }

    RECONCILIATION_PAYMENT_EVENTS = {
        "PAYMENT_RECEIVED",
    }

    @staticmethod
    def _time_str(dt: Optional[datetime]) -> str:
        if not dt:
            return ""
        return dt.strftime("%I:%M %p")

    @staticmethod
    def _entry_label(log) -> str:
        event_type = log.event_type

        if event_type == "SALE_REVENUE_GROSS":
            return "Sales Revenue · Restaurant"

        if event_type == "TIP_REVENUE":
            return "Other Income · Tips / Service"

        if event_type == "DISCOUNT_APPLIED":
            return "Discount Applied"

        if event_type == "COMPLIMENTARY_APPLIED":
            return "Complimentary Item"

        if event_type == "EXPENSE_POSTED":
            meta = log.meta or {}
            category = meta.get("category_name")
            item = meta.get("item_name") or meta.get("subcategory_name")
            if category and item:
                return f"{category} · {item}"
            if category:
                return category
            return "Expense"

        if event_type == "PAYMENT_RECEIVED":
            return "Customer Payment"

        if event_type == "CASH_MOVE":
            meta = log.meta or {}
            src = meta.get("source_channel") or "Source"
            dst = meta.get("target_channel") or "Target"
            return f"{src.upper()} → {dst.upper()}"

        if event_type == "DEBT_CREATED":
            return "Customer Debt"

        if event_type == "DEBT_REPAYMENT":
            return "Debt Repayment"

        if event_type == "REFUND_PAID":
            return "Refund Paid"

        return event_type.replace("_", " ").title()

    @staticmethod
    def _row_type(log) -> str:
        if log.event_type in AccountingReportsService.INCOME_EVENTS:
            return "income"
        if log.event_type in AccountingReportsService.EXPENSE_EVENTS:
            return "expense"
        return "movement"

    @staticmethod
    def _serialize_row(log) -> Dict:
        return {
            "id": log.id,
            "time": AccountingReportsService._time_str(log.occurred_at or log.created_at),
            "type": AccountingReportsService._row_type(log),
            "entry": AccountingReportsService._entry_label(log),
            "channel": log.channel,
            "amount": _f(log.amount),
            "reference_type": log.reference_type,
            "reference_id": log.reference_id,
            "details": log.meta or {},
            "event_type": log.event_type,
            "direction": log.direction,
            "currency": log.currency,
        }

    # =========================================================
    # DAILY TAB
    # =========================================================

    @staticmethod
    def daily_view(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:

        logs = TreasuryRepository.list_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        rows = [AccountingReportsService._serialize_row(l) for l in logs]

        income = 0.0
        expense = 0.0

        for r in rows:
            if r["type"] == "income":
                income += r["amount"]
            elif r["type"] == "expense":
                expense += abs(r["amount"])

        return {
            "summary": {
                "income": income,
                "expense": expense,
                "net": income - expense,
                "rows": len(rows),
            },
            "rows": rows,
        }

    # =========================================================
    # INCOME TAB
    # =========================================================

    @staticmethod
    def income_view(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:

        logs = TreasuryRepository.list_by_event_types(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            event_types=list(AccountingReportsService.INCOME_EVENTS),
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        rows = [AccountingReportsService._serialize_row(l) for l in logs]
        total = sum(r["amount"] for r in rows)

        return {
            "summary": {
                "total_income": total,
                "rows": len(rows),
            },
            "rows": rows,
        }

    # =========================================================
    # EXPENSES TAB
    # =========================================================

    @staticmethod
    def expenses_view(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:

        logs = TreasuryRepository.list_by_event_types(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            event_types=list(AccountingReportsService.EXPENSE_EVENTS),
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        rows = [AccountingReportsService._serialize_row(l) for l in logs]
        total = sum(abs(r["amount"]) for r in rows)

        by_event: Dict[str, float] = {}
        for r in rows:
            by_event[r["event_type"]] = by_event.get(r["event_type"], 0.0) + abs(r["amount"])

        return {
            "summary": {
                "total_expense": total,
                "rows": len(rows),
                "by_event_type": by_event,
            },
            "rows": rows,
        }

    # =========================================================
    # CASH MOVES TAB
    # =========================================================

    @staticmethod
    def cash_moves_view(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:

        logs = TreasuryRepository.list_by_event_types(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            event_types=list(AccountingReportsService.CASH_MOVE_EVENTS),
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        rows = [AccountingReportsService._serialize_row(l) for l in logs]

        by_channel: Dict[str, float] = {}
        total = 0.0

        for r in rows:
            amt = r["amount"]
            total += amt
            key = r["channel"] or "unknown"
            by_channel[key] = by_channel.get(key, 0.0) + amt

        return {
            "summary": {
                "total_movement": total,
                "rows": len(rows),
                "by_channel": by_channel,
            },
            "rows": rows,
        }

    # =========================================================
    # DEBT TAB
    # =========================================================

    @staticmethod
    def debt_view(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:

        logs = TreasuryRepository.list_by_event_types(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            event_types=list(AccountingReportsService.DEBT_EVENTS),
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        rows = [AccountingReportsService._serialize_row(l) for l in logs]

        debt_created = 0.0
        debt_repaid = 0.0

        for r in rows:
            if r["event_type"] == "DEBT_CREATED":
                debt_created += r["amount"]
            elif r["event_type"] == "DEBT_REPAYMENT":
                debt_repaid += r["amount"]

        return {
            "summary": {
                "debt_created": debt_created,
                "debt_repaid": debt_repaid,
                "outstanding_estimate": debt_created - debt_repaid,
                "rows": len(rows),
            },
            "rows": rows,
        }

    # =========================================================
    # RECONCILIATION TAB
    # =========================================================

    @staticmethod
    def reconciliation_view(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> Dict:

        all_logs = TreasuryRepository.list_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        revenue = 0.0
        payments = 0.0
        discounts = 0.0
        complimentary = 0.0
        debt_created = 0.0
        debt_repaid = 0.0

        by_channel: Dict[str, float] = {}

        for l in all_logs:
            amount = _f(l.amount)

            if l.event_type == "SALE_REVENUE_GROSS":
                revenue += amount

            elif l.event_type == "PAYMENT_RECEIVED":
                payments += amount
                ch = l.channel or "unknown"
                by_channel[ch] = by_channel.get(ch, 0.0) + amount

            elif l.event_type == "DISCOUNT_APPLIED":
                discounts += amount

            elif l.event_type == "COMPLIMENTARY_APPLIED":
                complimentary += amount

            elif l.event_type == "DEBT_CREATED":
                debt_created += amount

            elif l.event_type == "DEBT_REPAYMENT":
                debt_repaid += amount

        net_sales = revenue - discounts - complimentary
        expected_collection = net_sales
        realized_collection_plus_debt = payments + debt_created
        variance = expected_collection - realized_collection_plus_debt

        return {
            "summary": {
                "gross_revenue": revenue,
                "discounts": discounts,
                "complimentary": complimentary,
                "net_sales": net_sales,
                "payments_collected": payments,
                "debt_created": debt_created,
                "debt_repaid": debt_repaid,
                "expected_collection": expected_collection,
                "collection_plus_debt": realized_collection_plus_debt,
                "variance": variance,
                "by_channel": by_channel,
            },
            "rows": [AccountingReportsService._serialize_row(l) for l in all_logs],
        }