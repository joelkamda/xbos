from typing import Dict, List, Optional, Any
from datetime import datetime

from sqlalchemy.orm import Session

from core.domain.accounting.repository import TreasuryRepository


def _f(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _empty_recon_row(channel: str) -> Dict[str, Any]:
    return {
        "channel": channel,
        "opening": 0.0,
        "income": 0.0,
        "expense": 0.0,
        "cashIn": 0.0,
        "cashOut": 0.0,
        "expected": 0.0,
        "actual": 0.0,
        "variance": 0.0,
        "note": "",
        "status": "draft",
    }


def _recompute_recon_row(row: Dict[str, Any]) -> Dict[str, Any]:
    opening = _f(row.get("opening"))
    income = _f(row.get("income"))
    expense = _f(row.get("expense"))
    cash_in = _f(row.get("cashIn"))
    cash_out = _f(row.get("cashOut"))

    expected = opening + income - expense + cash_in - cash_out
    actual = _f(row.get("actual", expected))
    variance = actual - expected

    return {
        **row,
        "opening": opening,
        "income": income,
        "expense": expense,
        "cashIn": cash_in,
        "cashOut": cash_out,
        "expected": expected,
        "actual": actual,
        "variance": variance,
    }


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

    RECON_CHANNELS = ["cash", "mtn", "orange", "xafpay", "bank", "ar", "ap"]

    @staticmethod
    def _time_str(dt: Optional[datetime]) -> str:
        if not dt:
            return ""
        return dt.strftime("%I:%M %p")

    @staticmethod
    def _entry_label(log) -> str:
        event_type = log.event_type
        meta = log.meta or {}

        if event_type == "SALE_REVENUE_GROSS":
            return "Sales Revenue · Restaurant"

        if event_type == "TIP_REVENUE":
            return "Other Income · Tips / Service"

        if event_type == "SERVICE_REVENUE":
            category = meta.get("category_name")
            item = meta.get("item_name") or meta.get("subcategory_name")
            if category and item:
                return f"{category} · {item}"
            if category:
                return category
            return "Service Revenue"

        if event_type == "OTHER_INCOME":
            category = meta.get("category_name")
            item = meta.get("item_name") or meta.get("subcategory_name")
            if category and item:
                return f"{category} · {item}"
            if category:
                return category
            return "Other Income"

        if event_type == "DISCOUNT_APPLIED":
            label = (
                meta.get("display_label")
                or meta.get("discount_reason")
                or meta.get("discount_type")
                or "Discount"
            )
            return f"Discount · {label}"

        if event_type == "COMPLIMENTARY_APPLIED":
            label = (
                meta.get("display_label")
                or meta.get("complimentary_reason")
                or "Complimentary"
            )
            return f"Complimentary · {label}"

        if event_type == "EXPENSE_POSTED":
            category = meta.get("category_name")
            item = meta.get("item_name") or meta.get("subcategory_name")
            if category and item:
                return f"{category} · {item}"
            if category:
                return category
            return "Expense"

        if event_type == "COGS_RECOGNIZED":
            return "COGS Recognized"

        if event_type == "PAYMENT_RECEIVED":
            return "Customer Payment"

        if event_type == "CASH_MOVE":
            src = meta.get("source_channel") or meta.get("from") or "Source"
            dst = meta.get("target_channel") or meta.get("to") or "Target"
            return f"{str(src).upper()} → {str(dst).upper()}"

        if event_type == "DEBT_CREATED":
            return "Customer Debt"

        if event_type == "DEBT_REPAYMENT":
            return "Debt Repayment"

        if event_type == "STORE_CREDIT_CREATED":
            return "Store Credit / Change Owed"

        if event_type == "REFUND_PAID":
            return "Refund Paid"

        return str(event_type or "Event").replace("_", " ").title()

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
    # RECONCILIATION HELPERS
    # =========================================================

    @staticmethod
    def _build_reconciliation_rows(logs) -> List[Dict[str, Any]]:
        """
        Channel reconciliation.

        Treasury-log event interpretation:
        - PAYMENT_RECEIVED increases selected settlement channel.
        - OTHER_INCOME / SERVICE_REVENUE increase selected settlement channel.
        - EXPENSE_POSTED / REFUND_PAID decrease selected settlement channel.
        - DISCOUNT_APPLIED / COMPLIMENTARY_APPLIED are non-cash expenses;
          they are reported in commercial_summary and do not reduce a
          settlement channel a second time.
        - CASH_MOVE moves value from source_channel to target_channel.
        - DEBT_CREATED increases A/R.
        - DEBT_REPAYMENT decreases A/R and increases actual payment channel.
        - STORE_CREDIT_CREATED increases A/P.
        - SALE_REVENUE_GROSS is commercial revenue, not channel cashflow.
        """

        rows: Dict[str, Dict[str, Any]] = {
            channel: _empty_recon_row(channel)
            for channel in AccountingReportsService.RECON_CHANNELS
        }

        def ensure(channel: Optional[str]) -> Dict[str, Any]:
            ch = str(channel or "unknown").strip().lower()
            if not ch:
                ch = "unknown"
            if ch not in rows:
                rows[ch] = _empty_recon_row(ch)
            return rows[ch]

        for log in logs:
            event_type = str(log.event_type or "")
            amount = _f(log.amount)
            channel = str(log.channel or "").strip().lower() if log.channel else None
            meta = log.meta or {}

            if event_type == "CHANGE_RETURNED":
                continue

            if event_type in {
                "PAYMENT_RECEIVED",
                "OTHER_INCOME",
                "SERVICE_REVENUE",
            }:
                ensure(channel or "unknown")["income"] += amount
                continue

            if event_type in {"EXPENSE_POSTED", "REFUND_PAID"}:
                ensure(channel or "cash")["expense"] += amount
                continue

            if event_type == "CASH_MOVE":
                source = (
                    meta.get("source_channel")
                    or meta.get("from")
                    or meta.get("source")
                )
                target = (
                    meta.get("target_channel")
                    or meta.get("to")
                    or meta.get("target")
                    or channel
                )

                if source:
                    ensure(source)["cashOut"] += amount

                if target:
                    ensure(target)["cashIn"] += amount

                continue

            if event_type == "DEBT_CREATED":
                rows["ar"]["income"] += amount
                continue

            if event_type == "DEBT_REPAYMENT":
                rows["ar"]["cashOut"] += amount
                if channel:
                    ensure(channel)["cashIn"] += amount
                continue

            if event_type == "STORE_CREDIT_CREATED":
                rows["ap"]["income"] += amount
                continue

        ordered_rows: List[Dict[str, Any]] = []

        for channel in AccountingReportsService.RECON_CHANNELS:
            ordered_rows.append(_recompute_recon_row(rows[channel]))

        for channel, row in rows.items():
            if channel in AccountingReportsService.RECON_CHANNELS:
                continue
            ordered_rows.append(_recompute_recon_row(row))

        return ordered_rows

    @staticmethod
    def _apply_reconciliation_persistence(
        rows: List[Dict[str, Any]],
        *,
        previous_closing: Dict[str, float],
        existing_recon: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Applies persisted reconciliation behavior.

        - Draft window:
            opening = previous closed actual close per channel.
        - Closed/approved window:
            opening, actual, note, status come from recon_sheets.
        """

        next_rows: List[Dict[str, Any]] = []

        for row in rows:
            channel = str(row.get("channel") or "").strip().lower()
            persisted = existing_recon.get(channel)

            if persisted:
                row["opening"] = _f(persisted.opening_amount)
                row["actual"] = _f(persisted.actual_closing_amount)
                row["note"] = persisted.note or ""
                row["status"] = persisted.status or "closed"
            else:
                row["opening"] = _f(previous_closing.get(channel, 0))
                row["actual"] = row.get("expected", 0)
                row["note"] = row.get("note") or ""
                row["status"] = "draft"

            row = _recompute_recon_row(row)

            if persisted:
                row["actual"] = _f(persisted.actual_closing_amount)
                row["variance"] = row["actual"] - row["expected"]

            next_rows.append(row)

        return next_rows

    @staticmethod
    def _build_commercial_summary(logs) -> Dict[str, Any]:
        gross_sales = 0.0
        collections = 0.0
        discounts = 0.0
        complimentary = 0.0
        ar_created = 0.0
        ar_repaid = 0.0
        ap_created = 0.0
        tips = 0.0
        refunds = 0.0
        real_expenses = 0.0
        system_discount_expense = 0.0
        system_complimentary_expense = 0.0

        manual_income = 0.0
        service_income = 0.0
        other_income = 0.0

        discount_by_type: Dict[str, float] = {}
        complimentary_by_type: Dict[str, float] = {}
        manual_income_by_category: Dict[str, float] = {}

        for log in logs:
            event_type = str(log.event_type or "")
            amount = _f(log.amount)
            meta = log.meta or {}

            if event_type == "CHANGE_RETURNED":
                continue

            if event_type == "SALE_REVENUE_GROSS":
                gross_sales += amount
                continue

            if event_type == "PAYMENT_RECEIVED":
                collections += amount
                continue

            if event_type == "OTHER_INCOME":
                manual_income += amount
                other_income += amount
                label = (
                    meta.get("category_name")
                    or meta.get("subcategory_name")
                    or "Other Income"
                )
                manual_income_by_category[label] = (
                    manual_income_by_category.get(label, 0.0) + amount
                )
                continue

            if event_type == "SERVICE_REVENUE":
                manual_income += amount
                service_income += amount
                label = (
                    meta.get("category_name")
                    or meta.get("subcategory_name")
                    or "Service Revenue"
                )
                manual_income_by_category[label] = (
                    manual_income_by_category.get(label, 0.0) + amount
                )
                continue

            if event_type == "DISCOUNT_APPLIED":
                discounts += amount
                system_discount_expense += amount
                label = (
                    meta.get("display_label")
                    or meta.get("discount_reason")
                    or meta.get("discount_type")
                    or "Discount"
                )
                discount_by_type[label] = discount_by_type.get(label, 0.0) + amount
                continue

            if event_type == "COMPLIMENTARY_APPLIED":
                complimentary += amount
                system_complimentary_expense += amount
                label = (
                    meta.get("display_label")
                    or meta.get("complimentary_reason")
                    or "Complimentary"
                )
                complimentary_by_type[label] = complimentary_by_type.get(label, 0.0) + amount
                continue

            if event_type == "DEBT_CREATED":
                ar_created += amount
                continue

            if event_type == "DEBT_REPAYMENT":
                ar_repaid += amount
                continue

            if event_type == "STORE_CREDIT_CREATED":
                ap_created += amount
                continue

            if event_type == "TIP_REVENUE":
                tips += amount
                continue

            if event_type == "REFUND_PAID":
                refunds += amount
                continue

            if event_type == "EXPENSE_POSTED":
                real_expenses += amount
                continue

        allowances = discounts + complimentary
        system_expenses = system_discount_expense + system_complimentary_expense
        total_reportable_expense = real_expenses + system_expenses
        ar_net = ar_created - ar_repaid

        applied_to_sales = collections - tips - ap_created
        if applied_to_sales < 0:
            applied_to_sales = 0.0

        settled_value = (
            applied_to_sales
            + allowances
            + ar_created
            - refunds
        )

        unallocated = gross_sales - settled_value

        return {
            "gross_sales": gross_sales,
            "collections": collections,
            "applied_to_sales": applied_to_sales,
            "discounts": discounts,
            "complimentary": complimentary,
            "allowances": allowances,
            "ar_created": ar_created,
            "ar_repaid": ar_repaid,
            "ar_net": ar_net,
            "ap_created": ap_created,
            "tips": tips,
            "change_returned": 0.0,
            "refunds": refunds,
            "real_expenses": real_expenses,
            "system_discount_expense": system_discount_expense,
            "system_complimentary_expense": system_complimentary_expense,
            "system_expenses": system_expenses,
            "total_reportable_expense": total_reportable_expense,
            "expense_breakdown": {
                "manual_expenses": real_expenses,
                "discounts": system_discount_expense,
                "complimentary": system_complimentary_expense,
                "total": total_reportable_expense,
            },
            "manual_income": manual_income,
            "service_income": service_income,
            "other_income": other_income,
            "settled_value": settled_value,
            "unallocated": unallocated,
            "discount_by_type": discount_by_type,
            "complimentary_by_type": complimentary_by_type,
            "manual_income_by_category": manual_income_by_category,
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
        shift: str = "full24",
        limit: int = 500,
        offset: int = 0,
    ) -> Dict:
        """
        Returns channel reconciliation plus commercial settlement summary.

        Persistence behavior:
        - Draft window:
            opening = previous closed actual close per channel.
        - Closed/approved window:
            opening, actual, note, status come from recon_sheets.
        """

        logs = TreasuryRepository.list_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        rows = AccountingReportsService._build_reconciliation_rows(logs)

        previous_closing = TreasuryRepository.get_previous_closed_reconciliation_by_channel(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            before=start,
        )

        existing_recon = TreasuryRepository.get_existing_reconciliation_window(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            shift=shift,
            window_start=start,
            window_end=end,
        )

        rows = AccountingReportsService._apply_reconciliation_persistence(
            rows,
            previous_closing=previous_closing,
            existing_recon=existing_recon,
        )

        commercial_summary = AccountingReportsService._build_commercial_summary(logs)

        return {
            "rows": rows,
            "commercial_summary": commercial_summary,
            # Explicit alias for reconciliation UIs. These values are accounting
            # expenses, but discounts/comps are non-cash and therefore are not
            # subtracted from settlement-channel expected balances.
            "expense_summary": commercial_summary.get("expense_breakdown", {}),
            "non_cash_expenses": {
                "discounts": commercial_summary.get("system_discount_expense", 0.0),
                "complimentary": commercial_summary.get(
                    "system_complimentary_expense", 0.0
                ),
                "total": commercial_summary.get("system_expenses", 0.0),
            },
            "status": "closed" if existing_recon else "draft",
            "shift": shift,
            "window_start": start.isoformat() if start else None,
            "window_end": end.isoformat() if end else None,
        }