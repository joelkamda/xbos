from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List
from datetime import datetime

from database import get_db
from core.domain.accounting.repository import TreasuryRepository
from core.domain.accounting.accounting_controller import AccountingController
from core.rbac.utils.permission_decorator import require_permissions

router = APIRouter(tags=["Accounting"])


# ============================================================
# PAYLOAD MODELS
# ============================================================

class ManualIncomePayload(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "XAF"
    channel: str

    category_taxonomy_id: int
    subcategory_taxonomy_id: int

    item_mode: str = Field(default="free_text")
    atomic_unit_id: Optional[int] = None
    item_name: Optional[str] = None

    source_name: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None
    occurred_at: Optional[str] = None

    client_reference: str


class ExpensePayload(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "XAF"
    channel: str

    category_taxonomy_id: int
    subcategory_taxonomy_id: int

    item_mode: str = Field(default="free_text")
    atomic_unit_id: Optional[int] = None
    item_name: Optional[str] = None

    vendor: Optional[str] = None
    receipt_ref: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None
    occurred_at: Optional[str] = None

    client_reference: str


class CashMovementPayload(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "XAF"

    source_channel: str
    target_channel: str

    reason: Optional[str] = None
    reference: Optional[str] = None
    occurred_at: Optional[str] = None

    client_reference: str


# ============================================================
# INTERNAL UTIL
# ============================================================

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _time_str(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.strftime("%I:%M %p")


def _event_row_type(event_type: str) -> str:
    if event_type in {
        "SALE_REVENUE_GROSS",
        "TIP_REVENUE",
        "SERVICE_REVENUE",
        "OTHER_INCOME",
    }:
        return "income"

    if event_type in {
        "DISCOUNT_APPLIED",
        "COMPLIMENTARY_APPLIED",
        "EXPENSE_POSTED",
        "COGS_RECOGNIZED",
        "REFUND_PAID",
    }:
        return "expense"

    return "movement"


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
        label = meta.get("display_label") or meta.get("discount_reason") or "Discount"
        return f"Discount · {label}"

    if event_type == "COMPLIMENTARY_APPLIED":
        label = meta.get("display_label") or meta.get("complimentary_reason") or "Complimentary"
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

    if event_type == "CHANGE_RETURNED":
        return "Change Returned"

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


def _serialize_log(log) -> Dict[str, Any]:
    timestamp = log.occurred_at or log.created_at

    return {
        "id": log.id,
        "time": _time_str(timestamp),
        "type": _event_row_type(log.event_type),
        "entry": _entry_label(log),
        "event_type": log.event_type,
        "direction": log.direction,
        "amount": _f(log.amount),
        "currency": log.currency,
        "channel": log.channel,
        "reference_type": log.reference_type,
        "reference_id": log.reference_id,
        "taxonomy_node_id": log.taxonomy_node_id,
        "details": log.meta or {},
    }


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
    }


def _build_reconciliation_rows(logs) -> List[Dict[str, Any]]:
    """
    Treasury/channel reconciliation.

    IMPORTANT:
    - SALE_REVENUE_GROSS is not a channel event. It recognizes revenue only.
    - PAYMENT_RECEIVED is channel cashflow.
    - Manual income events OTHER_INCOME / SERVICE_REVENUE are both revenue
      recognition and real channel inflows because they are created from the
      manual income modal with a selected settlement channel.
    - TIP_REVENUE is intentionally NOT counted here unless its emission model
      is later confirmed to be separate from PAYMENT_RECEIVED, to avoid
      double-counting tips in channel balances.
    - CASH_MOVE is not income or expense. It uses source/target metadata.
    - CHANGE_RETURNED rows from old tests are ignored.
    """

    channels = ["cash", "mtn", "orange", "xafpay", "bank", "ar", "ap"]
    rows: Dict[str, Dict[str, Any]] = {
        channel: _empty_recon_row(channel) for channel in channels
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
            rows["ar"]["expense"] += amount
            if channel:
                ensure(channel)["income"] += amount
            continue

        if event_type == "STORE_CREDIT_CREATED":
            rows["ap"]["income"] += amount
            continue

    ordered_rows: List[Dict[str, Any]] = []

    for channel in channels:
        row = rows[channel]

        expected = (
            row["opening"]
            + row["income"]
            - row["expense"]
            + row["cashIn"]
            - row["cashOut"]
        )

        row["expected"] = expected
        row["actual"] = expected
        row["variance"] = row["actual"] - row["expected"]

        ordered_rows.append(row)

    for channel, row in rows.items():
        if channel in channels:
            continue

        expected = (
            row["opening"]
            + row["income"]
            - row["expense"]
            + row["cashIn"]
            - row["cashOut"]
        )

        row["expected"] = expected
        row["actual"] = expected
        row["variance"] = row["actual"] - row["expected"]

        ordered_rows.append(row)

    return ordered_rows


def _build_commercial_summary(logs) -> Dict[str, Any]:
    """
    Commercial settlement summary.

    Notes:
    - This summary is sale-settlement oriented and historically compared
      SALE_REVENUE_GROSS against PAYMENT_RECEIVED.
    - Manual income is now included separately as manual_income / service_income
      / other_income, but is NOT folded into gross_sales. This avoids making
      sale settlement math appear cleaner or dirtier because of unrelated
      non-sale income.
    - Old CHANGE_RETURNED rows from testing are ignored.
    """

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
        "manual_income": manual_income,
        "service_income": service_income,
        "other_income": other_income,
        "settled_value": settled_value,
        "unallocated": unallocated,
        "discount_by_type": discount_by_type,
        "complimentary_by_type": complimentary_by_type,
        "manual_income_by_category": manual_income_by_category,
    }


# ============================================================
# ACCOUNTING MODAL TAXONOMY ENDPOINTS
# ============================================================

@router.get("/taxonomy/income")
@require_permissions("accounting.view")
def accounting_income_taxonomy(
    request: Request,
    db: Session = Depends(get_db),
):
    return AccountingController.taxonomy_tree(
        request=request,
        db=db,
        taxonomy_type="FINANCE",
        domain_name="Revenue",
    )


@router.get("/taxonomy/expenses")
@require_permissions("accounting.view")
def accounting_expense_taxonomy(
    request: Request,
    db: Session = Depends(get_db),
):
    return AccountingController.taxonomy_tree(
        request=request,
        db=db,
        taxonomy_type="FINANCE",
        domain_name="Expenses",
    )


@router.get("/items/search")
@require_permissions("accounting.view")
def accounting_item_search(
    request: Request,
    db: Session = Depends(get_db),
    taxonomy_node_id: Optional[int] = None,
    q: str = "",
    limit: int = 25,
):
    return AccountingController.search_items(
        request=request,
        db=db,
        taxonomy_node_id=taxonomy_node_id,
        q=q,
        limit=limit,
    )


# ============================================================
# ACCOUNTING MODAL CREATE ENDPOINTS
# ============================================================

@router.post("/income/manual")
@require_permissions("accounting.post")
def create_manual_income(
    payload: ManualIncomePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    return AccountingController.create_manual_income(
        request=request,
        db=db,
        payload=payload.model_dump(),
    )


@router.post("/expenses")
@require_permissions("accounting.post")
def create_expense(
    payload: ExpensePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    return AccountingController.create_expense(
        request=request,
        db=db,
        payload=payload.model_dump(),
    )


@router.post("/cash-movements")
@require_permissions("accounting.post", "accounting.reconcile")
def create_cash_movement(
    payload: CashMovementPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    return AccountingController.create_cash_movement(
        request=request,
        db=db,
        payload=payload.model_dump(),
    )


# ============================================================
# TREASURY LEDGER FEED
# ============================================================

@router.get("/treasury")
@require_permissions("accounting.view")
def get_treasury_feed(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    ctx = request.state.user

    logs = TreasuryRepository.list_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        start=_parse_dt(start),
        end=_parse_dt(end),
        limit=limit,
        offset=offset,
    )

    items = [_serialize_log(log) for log in logs]

    return {
        "limit": limit,
        "offset": offset,
        "count": len(items),
        "items": items,
    }


# ============================================================
# SALE FINANCIAL DETAILS
# ============================================================

@router.get("/sales/{sale_id}")
@require_permissions("accounting.view", "report.financial", "sale.view")
def get_sale_financials(
    sale_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user

    logs = TreasuryRepository.get_sale_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        sale_id=sale_id,
    )

    return {
        "sale_id": sale_id,
        "events": [_serialize_log(log) for log in logs],
    }


# ============================================================
# PAYMENT ATTEMPT DETAILS
# ============================================================

@router.get("/attempt/{attempt_id}")
@require_permissions("accounting.view", "payments.view")
def get_attempt_financials(
    attempt_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user

    logs = TreasuryRepository.get_attempt_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        attempt_id=attempt_id,
    )

    return {
        "attempt_id": attempt_id,
        "events": [_serialize_log(log) for log in logs],
    }


# ============================================================
# DAILY ACCOUNTING VIEW
# ============================================================

@router.get("/daily")
@require_permissions("accounting.view")
def accounting_daily(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    return AccountingController.daily(
        request=request,
        db=db,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


# ============================================================
# INCOME VIEW
# ============================================================

@router.get("/income")
@require_permissions("accounting.view")
def accounting_income(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    return AccountingController.income(
        request=request,
        db=db,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


# ============================================================
# EXPENSES VIEW
# ============================================================

@router.get("/expenses")
@require_permissions("accounting.view")
def accounting_expenses(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    return AccountingController.expenses(
        request=request,
        db=db,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


# ============================================================
# CASH MOVEMENTS VIEW
# ============================================================

@router.get("/cash-movements")
@require_permissions("accounting.view")
def accounting_cash_movements(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    return AccountingController.cash_moves(
        request=request,
        db=db,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


# ============================================================
# DEBT / A-R VIEW
# ============================================================

@router.get("/debt")
@require_permissions("accounting.view")
def accounting_debt(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    return AccountingController.debt(
        request=request,
        db=db,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )


# ============================================================
# DAILY FINANCIAL SUMMARY
# ============================================================

@router.get("/summary")
@require_permissions("accounting.view")
def financial_summary(
    request: Request,
    db: Session = Depends(get_db),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    daily = AccountingController.daily(
        request=request,
        db=db,
        start=start,
        end=end,
        limit=500,
        offset=0,
    )

    return daily.get("summary", daily)


# ============================================================
# RECONCILIATION
# ============================================================

@router.get("/reconciliation")
@require_permissions("accounting.reconcile")
def get_reconciliation(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 500,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """
    Returns channel reconciliation plus commercial settlement summary.

    Shape:
    {
      "rows": [...],
      "commercial_summary": {...}
    }
    """

    ctx = request.state.user

    logs = TreasuryRepository.list_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        start=_parse_dt(start),
        end=_parse_dt(end),
        limit=limit,
        offset=offset,
    )

    rows = _build_reconciliation_rows(logs)
    commercial_summary = _build_commercial_summary(logs)

    return {
        "rows": rows,
        "commercial_summary": commercial_summary,
    }