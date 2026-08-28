from fastapi import APIRouter, Request, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import get_db
from core.domain.accounting.repository import TreasuryRepository
from core.domain.accounting.models import TreasuryLog
from core.domain.accounting.accounting_controller import AccountingController
from core.domain.accounting.accounts_receivable.service import (
    AccountsReceivableService,
)
from core.domain.accounting.accounts_receivable.repository import (
    AccountsReceivableRepository,
)
from core.rbac.utils.permission_decorator import require_permissions

router = APIRouter(tags=["Accounting"])


# ============================================================
# TIME CONSTANTS
# ============================================================

BUSINESS_TIMEZONE_NAME = "Africa/Douala"
BUSINESS_TZ = ZoneInfo(BUSINESS_TIMEZONE_NAME)
UTC_TZ = timezone.utc


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
    event_date: Optional[str] = None
    business_date: Optional[str] = None

    client_reference: str


class UpdateManualIncomePayload(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    channel: Optional[str] = None

    category_taxonomy_id: Optional[int] = None
    subcategory_taxonomy_id: Optional[int] = None

    item_mode: Optional[str] = None
    atomic_unit_id: Optional[int] = None
    item_name: Optional[str] = None

    source_name: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None
    occurred_at: Optional[str] = None
    event_date: Optional[str] = None
    business_date: Optional[str] = None

    client_reference: Optional[str] = None


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
    event_date: Optional[str] = None
    business_date: Optional[str] = None

    client_reference: str


class UpdateExpensePayload(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    channel: Optional[str] = None

    category_taxonomy_id: Optional[int] = None
    subcategory_taxonomy_id: Optional[int] = None

    item_mode: Optional[str] = None
    atomic_unit_id: Optional[int] = None
    item_name: Optional[str] = None

    vendor: Optional[str] = None
    receipt_ref: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None
    occurred_at: Optional[str] = None
    event_date: Optional[str] = None
    business_date: Optional[str] = None

    client_reference: Optional[str] = None


class CashMovementPayload(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "XAF"

    source_channel: str
    target_channel: str

    reason: Optional[str] = None
    reference: Optional[str] = None
    occurred_at: Optional[str] = None
    event_date: Optional[str] = None
    business_date: Optional[str] = None

    client_reference: str


class UpdateCashMovementPayload(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None

    source_channel: Optional[str] = None
    target_channel: Optional[str] = None

    reason: Optional[str] = None
    reference: Optional[str] = None
    occurred_at: Optional[str] = None
    event_date: Optional[str] = None
    business_date: Optional[str] = None

    client_reference: Optional[str] = None


class ReconCloseRowPayload(BaseModel):
    channel: str

    opening: float = 0
    income: float = 0
    expense: float = 0
    cashIn: float = 0
    cashOut: float = 0

    expected: float = 0
    actual: float = 0
    variance: float = 0

    note: Optional[str] = None


class ReconClosePayload(BaseModel):
    start: str
    end: str
    shift: str = "full24"
    rows: List[ReconCloseRowPayload]


class AccountsReceivableRepayPayload(BaseModel):
    amount: float = Field(..., gt=0)
    payment_method: str = "cash"
    reference: Optional[str] = None
    note: Optional[str] = None
    client_reference: Optional[str] = None


# ============================================================
# INTERNAL TIME UTILITIES
# ============================================================

def _utc_now() -> datetime:
    return datetime.now(UTC_TZ)


def _now_iso() -> str:
    return _utc_now().isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """
    Parse accounting datetime safely.

    XBOS accounting rule:
    - Business timezone is Africa/Douala / GMT+1.
    - Frontend should send explicit +01:00 strings.
    - If a legacy/frontend caller sends a naive datetime, treat it as
      Africa/Douala wall-clock time, then normalize to UTC for DB filtering.
    """

    if not value:
        return None

    safe_value = str(value).strip()

    if not safe_value:
        return None

    if safe_value.endswith("Z"):
        safe_value = safe_value.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(safe_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid datetime value: {value}",
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BUSINESS_TZ)

    return parsed.astimezone(UTC_TZ)


def _display_dt(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC_TZ)

    return value.astimezone(BUSINESS_TZ)


def _payload_occurred_at(payload: Dict[str, Any]) -> Optional[datetime]:
    occurred = payload.get("occurred_at") or payload.get("event_date")
    if occurred:
        return _parse_dt(str(occurred))

    business_date = payload.get("business_date")
    if business_date:
        return _parse_dt(f"{str(business_date).strip()}T12:00:00+01:00")

    return None


def _normalize_payload_dates(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(payload or {})
    occurred = _payload_occurred_at(clean)

    if occurred:
        clean["occurred_at"] = occurred.isoformat()

    return clean


# ============================================================
# INTERNAL GENERAL UTILITIES
# ============================================================

def _safe_settlement_channel(value: Optional[str]) -> str:
    ch = str(value or "").strip().lower()

    if ch not in {"cash", "mtn", "orange", "xafpay", "bank"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid settlement channel",
        )

    return ch


def _get_owned_treasury_log(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    event_id: int,
    allowed_event_types: set[str],
) -> TreasuryLog:
    log = (
        db.query(TreasuryLog)
        .filter(
            TreasuryLog.id == event_id,
            TreasuryLog.tenant_id == tenant_id,
            TreasuryLog.branch_id == branch_id,
        )
        .first()
    )

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Accounting event not found",
        )

    if str(log.event_type or "") not in allowed_event_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This accounting event type cannot be edited from this screen",
        )

    return log


def _changed_payload(payload: BaseModel) -> Dict[str, Any]:
    return payload.model_dump(exclude_unset=True)


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _time_str(value: Optional[datetime]) -> str:
    if not value:
        return ""

    display_value = _display_dt(value)
    return display_value.strftime("%I:%M %p") if display_value else ""


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC_TZ)

    return value.astimezone(UTC_TZ).isoformat()


def _iso_business(value: Optional[datetime]) -> Optional[str]:
    display_value = _display_dt(value)
    return display_value.isoformat() if display_value else None


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
        "occurred_at": _iso_utc(log.occurred_at),
        "created_at": _iso_utc(log.created_at),
        "date": _iso_utc(timestamp),
        "occurred_at_business": _iso_business(log.occurred_at),
        "created_at_business": _iso_business(log.created_at),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
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


def _confirmed_xafpay_settlement_rows(
    db: Session, *, tenant_id: int, branch_id: int,
    start: Optional[datetime] = None, end: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Project canonical confirmed settlements without rewriting Finance history."""
    rows = db.execute(text("""
        SELECT s.id,s.public_id,s.gross_amount,s.currency_code,s.occurred_at,
               s.payment_method_code,s.payment_rail_code,a.orchestrator_code,
               a.external_attempt_reference,a.metadata
          FROM payment_settlements s
          JOIN canonical_payment_attempts a
            ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
         WHERE s.tenant_id=:tenant_id AND s.organization_unit_id=:branch_id
           AND a.orchestrator_code='xafpay'
           AND s.settlement_state IN ('confirmed','partially_reversed')
           AND (:start_at IS NULL OR s.occurred_at >= :start_at)
           AND (:end_at IS NULL OR s.occurred_at < :end_at)
         ORDER BY s.occurred_at DESC,s.id DESC
    """), {"tenant_id": tenant_id, "branch_id": branch_id,
             "start_at": start, "end_at": end}).mappings().all()
    return [dict(row) for row in rows]


def _serialize_xafpay_settlement(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(row.get("metadata") or {})
    sale_id = metadata.get("sale_id")
    occurred_at = row.get("occurred_at")
    metadata.update({"settlement_public_id": str(row.get("public_id")),
                     "payment_method": row.get("payment_method_code"),
                     "payment_rail": row.get("payment_rail_code"),
                     "orchestrator": row.get("orchestrator_code"),
                     "canonical_settlement": True})
    return {
        "id": f"xafpay-settlement:{row.get('public_id')}",
        "time": _time_str(occurred_at), "occurred_at": _iso_utc(occurred_at),
        "created_at": _iso_utc(occurred_at), "date": _iso_utc(occurred_at),
        "occurred_at_business": _iso_business(occurred_at),
        "created_at_business": _iso_business(occurred_at),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "type": _event_row_type("PAYMENT_RECEIVED"),
        "entry": "XafPay Payment", "event_type": "PAYMENT_RECEIVED",
        "direction": "credit", "amount": _f(row.get("gross_amount")),
        "currency": row.get("currency_code") or "XAF", "channel": "xafpay",
        "reference_type": "sale" if sale_id else "payment_settlement",
        "reference_id": sale_id, "taxonomy_node_id": None, "details": metadata,
    }


def _serialize_repayment(repayment) -> Dict[str, Any]:
    return {
        "id": repayment.id,
        "tenant_id": repayment.tenant_id,
        "branch_id": repayment.branch_id,
        "ar_id": repayment.ar_id,
        "amount": _f(repayment.amount),
        "payment_method": repayment.payment_method,
        "reference": repayment.reference,
        "note": repayment.note,
        "created_by_user_id": repayment.created_by_user_id,
        "created_at": _iso_utc(repayment.created_at),
        "created_at_business": _iso_business(repayment.created_at),
    }


def _serialize_ar_with_repayments(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    ar,
) -> Dict[str, Any]:
    repayments = AccountsReceivableRepository.list_repayments(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
        ar_id=ar.id,
    )

    return {
        **AccountsReceivableService.serialize(ar),
        "repayments": [_serialize_repayment(r) for r in repayments],
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


def _build_reconciliation_rows(logs) -> List[Dict[str, Any]]:
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
            source = meta.get("source_channel") or meta.get("from") or meta.get("source")
            target = meta.get("target_channel") or meta.get("to") or meta.get("target") or channel

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

    for channel in channels:
        ordered_rows.append(_recompute_recon_row(rows[channel]))

    for channel, row in rows.items():
        if channel in channels:
            continue
        ordered_rows.append(_recompute_recon_row(row))

    return ordered_rows


def _load_previous_closing_map(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    before: Optional[datetime],
) -> Dict[str, float]:
    """
    Returns the latest closed/approved actual closing balance per channel before
    the selected reconciliation window.

    Carry-forward rule:
    previous actual close => next opening.
    """

    if not before:
        return {}

    result = db.execute(
        text(
            """
            SELECT DISTINCT ON (channel)
                channel,
                actual_closing_amount
            FROM recon_sheets
            WHERE tenant_id = :tenant_id
              AND branch_id = :branch_id
              AND status IN ('closed', 'approved')
              AND window_end <= :before
            ORDER BY channel, window_end DESC, id DESC
            """
        ),
        {
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "before": before,
        },
    ).mappings().all()

    return {
        str(row["channel"]).strip().lower(): _f(row["actual_closing_amount"])
        for row in result
    }


def _load_existing_recon_map(
    db: Session,
    *,
    tenant_id: int,
    branch_id: int,
    shift: str,
    start: Optional[datetime],
    end: Optional[datetime],
) -> Dict[str, Dict[str, Any]]:
    """
    Returns persisted reconciliation rows for the selected window,
    including draft, reopened, closed, and approved rows.
    """

    if not start or not end:
        return {}

    result = db.execute(
        text(
            """
            SELECT *
            FROM recon_sheets
            WHERE tenant_id = :tenant_id
              AND branch_id = :branch_id
              AND shift = :shift
              AND window_start = :window_start
              AND window_end = :window_end
            """
        ),
        {
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "shift": shift,
            "window_start": start,
            "window_end": end,
        },
    ).mappings().all()

    return {
        str(row["channel"]).strip().lower(): dict(row)
        for row in result
    }


def _resolve_reconciliation_window_status(
    existing_recon: Dict[str, Dict[str, Any]],
) -> str:
    """
    Resolves the top-level reconciliation window status from persisted rows.

    Important:
    - Existing rows do NOT automatically mean closed.
    - Save Draft persists rows with status=draft.
    - Close Recon persists rows with status=closed.
    """

    statuses = {
        str(row.get("status") or "").strip().lower()
        for row in existing_recon.values()
        if row
    }

    if "approved" in statuses:
        return "approved"

    if "closed" in statuses:
        return "closed"

    if "reopened" in statuses:
        return "reopened"

    if "draft" in statuses:
        return "draft"

    return "draft"


def _apply_reconciliation_persistence(
    rows: List[Dict[str, Any]],
    *,
    previous_closing: Dict[str, float],
    existing_recon: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Applies persisted reconciliation behavior to computed treasury rows.

    - New/draft window: opening comes from previous actual close.
    - Persisted window: opening/actual/note/status come from recon_sheets.
    """

    next_rows: List[Dict[str, Any]] = []

    for row in rows:
        channel = str(row.get("channel") or "").strip().lower()
        persisted = existing_recon.get(channel)

        if persisted:
            row["opening"] = _f(persisted.get("opening_amount"))
            row["actual"] = _f(persisted.get("actual_closing_amount"))
            row["note"] = persisted.get("note") or ""
            row["status"] = persisted.get("status") or "draft"
        else:
            row["opening"] = _f(previous_closing.get(channel, 0))
            row["actual"] = row.get("expected", 0)
            row["note"] = row.get("note") or ""
            row["status"] = "draft"

        row = _recompute_recon_row(row)

        if persisted:
            row["actual"] = _f(persisted.get("actual_closing_amount"))
            row["variance"] = row["actual"] - row["expected"]

        next_rows.append(row)

    return next_rows


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
            label = meta.get("category_name") or meta.get("subcategory_name") or "Other Income"
            manual_income_by_category[label] = manual_income_by_category.get(label, 0.0) + amount
            continue

        if event_type == "SERVICE_REVENUE":
            manual_income += amount
            service_income += amount
            label = meta.get("category_name") or meta.get("subcategory_name") or "Service Revenue"
            manual_income_by_category[label] = manual_income_by_category.get(label, 0.0) + amount
            continue

        if event_type == "DISCOUNT_APPLIED":
            discounts += amount
            label = meta.get("display_label") or meta.get("discount_reason") or meta.get("discount_type") or "Discount"
            discount_by_type[label] = discount_by_type.get(label, 0.0) + amount
            continue

        if event_type == "COMPLIMENTARY_APPLIED":
            complimentary += amount
            label = meta.get("display_label") or meta.get("complimentary_reason") or "Complimentary"
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

    settled_value = applied_to_sales + allowances + ar_created - refunds
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
# ACCOUNTS / A-R ENDPOINTS
# ============================================================

@router.get("/accounts/ar")
@require_permissions("accounting.view")
def list_accounts_receivable(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
):
    ctx = request.state.user

    rows = AccountsReceivableService.list_open(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        limit=limit,
        offset=offset,
    )

    items = [
        _serialize_ar_with_repayments(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            ar=row,
        )
        for row in rows
    ]

    summary = {
        "open_count": len([r for r in items if r.get("status") == "open"]),
        "partial_count": len([r for r in items if r.get("status") == "partial"]),
        "total_original": sum(_f(r.get("original_amount")) for r in items),
        "total_paid": sum(_f(r.get("paid_amount")) for r in items),
        "total_balance_due": sum(_f(r.get("balance_due")) for r in items),
    }

    return {
        "limit": limit,
        "offset": offset,
        "count": len(items),
        "summary": summary,
        "items": items,
    }


@router.get("/accounts/ar/{ar_id}")
@require_permissions("accounting.view")
def get_accounts_receivable(
    ar_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user

    ar = AccountsReceivableRepository.get_by_id(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        ar_id=ar_id,
    )

    if not ar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="A/R account not found",
        )

    return _serialize_ar_with_repayments(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        ar=ar,
    )


@router.post("/accounts/ar/{ar_id}/repay")
@require_permissions("accounting.post", "payments.receive")
def repay_accounts_receivable(
    ar_id: int,
    payload: AccountsReceivableRepayPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user
    user_id = ctx.get("id") or ctx.get("user_id")

    try:
        ar = AccountsReceivableService.record_repayment(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            ar_id=ar_id,
            amount=payload.amount,
            payment_method=payload.payment_method,
            reference=payload.reference,
            note=payload.note,
            client_reference=payload.client_reference,
            created_by_user_id=user_id,
        )

        db.commit()
        db.refresh(ar)

        return {
            "ok": True,
            "account": _serialize_ar_with_repayments(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                ar=ar,
            ),
        }

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record A/R repayment: {exc}",
        )


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
        payload=_normalize_payload_dates(payload.model_dump()),
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
        payload=_normalize_payload_dates(payload.model_dump()),
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
        payload=_normalize_payload_dates(payload.model_dump()),
    )


# ============================================================
# ACCOUNTING MODAL UPDATE ENDPOINTS
# ============================================================

@router.patch("/income/manual/{event_id}")
@require_permissions("accounting.edit")
def update_manual_income(
    event_id: int,
    payload: UpdateManualIncomePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user
    user_id = ctx.get("id") or ctx.get("user_id")

    patch = _changed_payload(payload)

    log = _get_owned_treasury_log(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        event_id=event_id,
        allowed_event_types={"OTHER_INCOME", "SERVICE_REVENUE"},
    )

    meta = dict(log.meta or {})

    if "amount" in patch:
        log.amount = patch["amount"]

    if "currency" in patch and patch.get("currency"):
        log.currency = str(patch["currency"]).upper()

    if "channel" in patch and patch.get("channel"):
        log.channel = _safe_settlement_channel(patch.get("channel"))

    occurred_at = _payload_occurred_at(patch)
    if occurred_at:
        log.occurred_at = occurred_at
        meta["business_date"] = patch.get("business_date")
        meta["business_timezone"] = BUSINESS_TIMEZONE_NAME

    needs_taxonomy = (
        "category_taxonomy_id" in patch
        or "subcategory_taxonomy_id" in patch
        or "atomic_unit_id" in patch
        or "item_name" in patch
        or "item_mode" in patch
    )

    if needs_taxonomy:
        category_id = int(
            patch.get("category_taxonomy_id")
            or meta.get("category_taxonomy_id")
            or 0
        )
        subcategory_id = int(
            patch.get("subcategory_taxonomy_id")
            or meta.get("subcategory_taxonomy_id")
            or 0
        )

        path = AccountingController._validate_finance_path(
            db,
            tenant_id=ctx["tenant_id"],
            domain_name="Revenue",
            category_taxonomy_id=category_id,
            subcategory_taxonomy_id=subcategory_id,
        )

        atomic_unit = AccountingController._validate_atomic_unit(
            db,
            tenant_id=ctx["tenant_id"],
            atomic_unit_id=patch.get("atomic_unit_id"),
        )

        item_name = (
            atomic_unit.name
            if atomic_unit
            else str(patch.get("item_name") or meta.get("item_name") or "").strip()
        )

        if not item_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specific item is required",
            )

        category = path["category"]
        subcategory = path["subcategory"]

        log.event_type = (
            "SERVICE_REVENUE"
            if category.name == "Service Revenue"
            else "OTHER_INCOME"
        )
        log.taxonomy_node_id = subcategory.id

        meta.update(
            {
                "domain_taxonomy_id": path["domain"].id,
                "domain_name": path["domain"].name,
                "category_taxonomy_id": category.id,
                "category_name": category.name,
                "subcategory_taxonomy_id": subcategory.id,
                "subcategory_name": subcategory.name,
                "item_mode": patch.get("item_mode") or meta.get("item_mode") or "free_text",
                "atomic_unit_id": atomic_unit.id if atomic_unit else patch.get("atomic_unit_id") or meta.get("atomic_unit_id"),
                "item_name": item_name,
            }
        )

    for key in ["source_name", "reference", "note", "client_reference"]:
        if key in patch:
            meta[key] = patch.get(key)

    meta["edited_by_user_id"] = user_id
    meta["edited_at"] = _now_iso()
    log.meta = meta

    try:
        db.commit()
        db.refresh(log)
        return {"ok": True, "event": _serialize_log(log)}
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update income event: {exc}",
        )


@router.patch("/expenses/{event_id}")
@require_permissions("accounting.edit")
def update_expense(
    event_id: int,
    payload: UpdateExpensePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user
    user_id = ctx.get("id") or ctx.get("user_id")

    patch = _changed_payload(payload)

    log = _get_owned_treasury_log(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        event_id=event_id,
        allowed_event_types={"EXPENSE_POSTED"},
    )

    meta = dict(log.meta or {})

    if "amount" in patch:
        log.amount = patch["amount"]

    if "currency" in patch and patch.get("currency"):
        log.currency = str(patch["currency"]).upper()

    if "channel" in patch and patch.get("channel"):
        log.channel = _safe_settlement_channel(patch.get("channel"))

    occurred_at = _payload_occurred_at(patch)
    if occurred_at:
        log.occurred_at = occurred_at
        meta["business_date"] = patch.get("business_date")
        meta["business_timezone"] = BUSINESS_TIMEZONE_NAME

    needs_taxonomy = (
        "category_taxonomy_id" in patch
        or "subcategory_taxonomy_id" in patch
        or "atomic_unit_id" in patch
        or "item_name" in patch
        or "item_mode" in patch
    )

    if needs_taxonomy:
        category_id = int(
            patch.get("category_taxonomy_id")
            or meta.get("category_taxonomy_id")
            or 0
        )
        subcategory_id = int(
            patch.get("subcategory_taxonomy_id")
            or meta.get("subcategory_taxonomy_id")
            or 0
        )

        path = AccountingController._validate_finance_path(
            db,
            tenant_id=ctx["tenant_id"],
            domain_name="Expenses",
            category_taxonomy_id=category_id,
            subcategory_taxonomy_id=subcategory_id,
        )

        atomic_unit = AccountingController._validate_atomic_unit(
            db,
            tenant_id=ctx["tenant_id"],
            atomic_unit_id=patch.get("atomic_unit_id"),
        )

        item_name = (
            atomic_unit.name
            if atomic_unit
            else str(patch.get("item_name") or meta.get("item_name") or "").strip()
        )

        if not item_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specific item is required",
            )

        category = path["category"]
        subcategory = path["subcategory"]

        log.taxonomy_node_id = subcategory.id

        meta.update(
            {
                "domain_taxonomy_id": path["domain"].id,
                "domain_name": path["domain"].name,
                "category_taxonomy_id": category.id,
                "category_name": category.name,
                "subcategory_taxonomy_id": subcategory.id,
                "subcategory_name": subcategory.name,
                "item_mode": patch.get("item_mode") or meta.get("item_mode") or "free_text",
                "atomic_unit_id": atomic_unit.id if atomic_unit else patch.get("atomic_unit_id") or meta.get("atomic_unit_id"),
                "item_name": item_name,
            }
        )

    for key in [
        "vendor",
        "receipt_ref",
        "reference",
        "note",
        "client_reference",
    ]:
        if key in patch:
            meta[key] = patch.get(key)

    meta["edited_by_user_id"] = user_id
    meta["edited_at"] = _now_iso()
    log.meta = meta

    try:
        db.commit()
        db.refresh(log)
        return {"ok": True, "event": _serialize_log(log)}
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update expense event: {exc}",
        )


@router.patch("/cash-movements/{event_id}")
@require_permissions("accounting.edit")
def update_cash_movement(
    event_id: int,
    payload: UpdateCashMovementPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    ctx = request.state.user
    user_id = ctx.get("id") or ctx.get("user_id")

    patch = _changed_payload(payload)

    log = _get_owned_treasury_log(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        event_id=event_id,
        allowed_event_types={"CASH_MOVE"},
    )

    meta = dict(log.meta or {})

    if "amount" in patch:
        log.amount = patch["amount"]

    if "currency" in patch and patch.get("currency"):
        log.currency = str(patch["currency"]).upper()

    source_channel = patch.get("source_channel") or meta.get("source_channel")
    target_channel = patch.get("target_channel") or meta.get("target_channel")

    if "source_channel" in patch:
        source_channel = _safe_settlement_channel(patch.get("source_channel"))
        meta["source_channel"] = source_channel
        meta["from"] = source_channel

    if "target_channel" in patch:
        target_channel = _safe_settlement_channel(patch.get("target_channel"))
        meta["target_channel"] = target_channel
        meta["to"] = target_channel
        log.channel = target_channel

    if source_channel and target_channel and source_channel == target_channel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_channel and target_channel must be different",
        )

    occurred_at = _payload_occurred_at(patch)
    if occurred_at:
        log.occurred_at = occurred_at
        meta["business_date"] = patch.get("business_date")
        meta["business_timezone"] = BUSINESS_TIMEZONE_NAME

    for key in ["reason", "reference", "client_reference"]:
        if key in patch:
            meta[key] = patch.get(key)

    meta["edited_by_user_id"] = user_id
    meta["edited_at"] = _now_iso()
    log.meta = meta

    try:
        db.commit()
        db.refresh(log)
        return {"ok": True, "event": _serialize_log(log)}
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update cash movement: {exc}",
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
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)

    logs = TreasuryRepository.list_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )

    items = [_serialize_log(log) for log in logs]

    return {
        "limit": limit,
        "offset": offset,
        "count": len(items),
        "items": items,
        "window_start": _iso_utc(start_dt),
        "window_end": _iso_utc(end_dt),
        "window_start_business": _iso_business(start_dt),
        "window_end_business": _iso_business(end_dt),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
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
    limit: int = 1000,
    offset: int = 0,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    ctx = request.state.user
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)

    logs = TreasuryRepository.list_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )

    rows = [_serialize_log(log) for log in logs]
    rows.extend(_serialize_xafpay_settlement(row) for row in
                _confirmed_xafpay_settlement_rows(
                    db, tenant_id=ctx["tenant_id"], branch_id=ctx["branch_id"],
                    start=start_dt, end=end_dt))
    collection_controls = db.execute(text("""
        SELECT a.public_id,a.attempt_state,a.attempted_amount,a.payment_rail_code,
               a.occurred_at,(a.metadata->>'sale_id')::int sale_id,
               pi.amount commercial_total,pi.total_paid confirmed_total,
               pi.balance_due outstanding,
               coalesce((SELECT sum(ar.balance_due) FROM accounts_receivable ar
                          WHERE ar.tenant_id=a.tenant_id
                            AND ar.sale_id=(a.metadata->>'sale_id')::int
                            AND ar.status IN ('open','partial')),0) approved_ar
          FROM canonical_payment_attempts a
          JOIN payment_intents pi ON pi.tenant_id=a.tenant_id
           AND pi.payable_type='sale' AND pi.payable_id=(a.metadata->>'sale_id')::int
         WHERE a.tenant_id=:tenant AND a.organization_unit_id=:branch
           AND a.orchestrator_code='xafpay'
           AND a.attempt_state IN ('pending','processing','unknown','failed','cancelled','expired')
           AND (:start IS NULL OR a.occurred_at>=:start)
           AND (:end IS NULL OR a.occurred_at<:end)
         ORDER BY a.occurred_at,a.id
    """), {"tenant": ctx["tenant_id"], "branch": ctx["branch_id"],
             "start": start_dt, "end": end_dt}).mappings().all()
    rows.extend({
        "id": -index,
        "type": "movement",
        "entry": f"XafPay {str(row['attempt_state']).upper()} collection control",
        "event_type": "XAFPAY_COLLECTION_CONTROL",
        "channel": "xafpay",
        "amount": _f(row["outstanding"]),
        "currency": "XAF",
        "occurred_at": _iso_utc(row["occurred_at"]),
        "occurred_at_business": _iso_business(row["occurred_at"]),
        "reference_type": "sale",
        "reference_id": row["sale_id"],
        "details": {
            "financial_effect": "NONE",
            "attempt_state": str(row["attempt_state"]).upper(),
            "attempted_amount": _f(row["attempted_amount"]),
            "outstanding": _f(row["outstanding"]),
            "approved_ar": _f(row["approved_ar"]),
            "collectible_now": max(0, _f(row["outstanding"]) - _f(row["approved_ar"])),
        },
    } for index, row in enumerate(collection_controls, start=1))

    income = sum(
        abs(_f(row.get("amount")))
        for row in rows
        if row.get("type") == "income"
    )

    expense = sum(
        abs(_f(row.get("amount")))
        for row in rows
        if row.get("type") == "expense"
    )

    return {
        "summary": {
            "income": income,
            "expense": expense,
            "net": income - expense,
            "rows": len(rows),
            "events": len(rows),
        },
        "rows": rows,
        "collection_controls": [{
            "attempt_id": str(row["public_id"]), "sale_id": row["sale_id"],
            "orchestrator": "xafpay", "rail": row["payment_rail_code"],
            "attempt_state": str(row["attempt_state"]).upper(),
            "attempted_amount": _f(row["attempted_amount"]),
            "commercial_total": _f(row["commercial_total"]),
            "confirmed_total": _f(row["confirmed_total"]),
            "outstanding": _f(row["outstanding"]),
            "approved_ar": _f(row["approved_ar"]),
            "collectible_now": max(0, _f(row["outstanding"]) - _f(row["approved_ar"])),
            "financial_effect": "NONE",
        } for row in collection_controls],
        "window_start": _iso_utc(start_dt),
        "window_end": _iso_utc(end_dt),
        "window_start_business": _iso_business(start_dt),
        "window_end_business": _iso_business(end_dt),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "limit": limit,
        "offset": offset,
    }


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
    daily = accounting_daily(
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
    shift: str = "full24",
):
    """
    Returns channel reconciliation plus commercial settlement summary.

    Persistence behavior:
    - New/draft window:
        opening = previous closed actual close per channel.
    - Persisted draft window:
        opening, actual, note, status come from recon_sheets,
        but top-level status remains draft.
    - Closed/approved window:
        opening, actual, note, status come from recon_sheets,
        and top-level status becomes closed/approved.
    """

    ctx = request.state.user
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)

    logs = TreasuryRepository.list_logs(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )

    rows = _build_reconciliation_rows(logs)
    confirmed_xafpay = _confirmed_xafpay_settlement_rows(
        db, tenant_id=ctx["tenant_id"], branch_id=ctx["branch_id"],
        start=start_dt, end=end_dt)
    xafpay_amount = sum(_f(row.get("gross_amount")) for row in confirmed_xafpay)
    for row in rows:
        if row.get("channel") == "xafpay":
            row["income"] = _f(row.get("income")) + xafpay_amount
            row.update(_recompute_recon_row(row))
            row["payment_method"] = "mobile_money"
            row["rails"] = sorted({str(item.get("payment_rail_code") or "").lower()
                                  for item in confirmed_xafpay if item.get("payment_rail_code")})
            row["orchestrator"] = "xafpay"
            row["confirmed_settlement_count"] = len(confirmed_xafpay)
            row["confirmed_settlements"] = [
                {"settlement_id": str(item.get("public_id")),
                 "sale_id": (item.get("metadata") or {}).get("sale_id"),
                 "amount": _f(item.get("gross_amount")),
                 "currency": item.get("currency_code") or "XAF",
                 "rail": str(item.get("payment_rail_code") or "").lower() or None}
                for item in confirmed_xafpay
            ]
            break
    commercial_summary = _build_commercial_summary(logs)

    previous_closing = _load_previous_closing_map(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        before=start_dt,
    )

    existing_recon = _load_existing_recon_map(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        shift=shift,
        start=start_dt,
        end=end_dt,
    )

    rows = _apply_reconciliation_persistence(
        rows,
        previous_closing=previous_closing,
        existing_recon=existing_recon,
    )

    window_status = _resolve_reconciliation_window_status(existing_recon)

    open_controls = db.execute(text("""
        SELECT a.public_id,a.attempt_state,a.attempted_amount,a.payment_rail_code,
               (a.metadata->>'sale_id')::int sale_id,pi.amount commercial_total,
               pi.total_paid confirmed_total,pi.balance_due outstanding,
               coalesce((SELECT sum(ar.balance_due) FROM accounts_receivable ar
                          WHERE ar.tenant_id=a.tenant_id
                            AND ar.sale_id=(a.metadata->>'sale_id')::int
                            AND ar.status IN ('open','partial')),0) approved_ar
          FROM canonical_payment_attempts a
          JOIN payment_intents pi ON pi.tenant_id=a.tenant_id
           AND pi.payable_type='sale' AND pi.payable_id=(a.metadata->>'sale_id')::int
         WHERE a.tenant_id=:tenant AND a.organization_unit_id=:branch
           AND a.orchestrator_code='xafpay'
           AND a.attempt_state IN ('pending','processing','unknown','failed','cancelled','expired')
           AND (:start IS NULL OR a.occurred_at>=:start)
           AND (:end IS NULL OR a.occurred_at<:end)
         ORDER BY a.occurred_at,a.id
    """), {"tenant": ctx["tenant_id"], "branch": ctx["branch_id"],
             "start": start_dt, "end": end_dt}).mappings().all()
    for recon_row in rows:
        if recon_row.get("channel") == "xafpay":
            recon_row.setdefault("meta", {})["open_balance_controls"] = [{
                "sale_id": row["sale_id"],
                "attempt_state": str(row["attempt_state"]).upper(),
                "attempted_amount": _f(row["attempted_amount"]),
                "outstanding": _f(row["outstanding"]),
                "approved_ar": _f(row["approved_ar"]),
                "collectible_now": max(0, _f(row["outstanding"]) - _f(row["approved_ar"])),
                "confirmed_money": 0,
            } for row in open_controls]
            break

    return {
        "rows": rows,
        "commercial_summary": commercial_summary,
        "open_balance_controls": [{
            "attempt_id": str(row["public_id"]), "sale_id": row["sale_id"],
            "orchestrator": "xafpay", "rail": row["payment_rail_code"],
            "attempt_state": str(row["attempt_state"]).upper(),
            "attempted_amount": _f(row["attempted_amount"]),
            "commercial_total": _f(row["commercial_total"]),
            "confirmed_total": _f(row["confirmed_total"]),
            "outstanding": _f(row["outstanding"]),
            "approved_ar": _f(row["approved_ar"]),
            "collectible_now": max(0, _f(row["outstanding"]) - _f(row["approved_ar"])),
            "confirmed_money": 0,
        } for row in open_controls],
        "status": window_status,
        "shift": shift,
        "window_start": _iso_utc(start_dt),
        "window_end": _iso_utc(end_dt),
        "window_start_business": _iso_business(start_dt),
        "window_end_business": _iso_business(end_dt),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "limit": limit,
        "offset": offset,
    }


@router.post("/reconciliation/save-draft")
@require_permissions("accounting.reconcile")
def save_reconciliation_draft(
    payload: ReconClosePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Persists a draft reconciliation window.

    This saves actual counted values and notes without closing the accounting cycle.
    """

    return AccountingController.save_reconciliation_draft(
        request=request,
        db=db,
        payload=payload.model_dump(),
    )


@router.post("/reconciliation/close")
@require_permissions("accounting.reconcile")
def close_reconciliation(
    payload: ReconClosePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Persists a closed reconciliation window.

    Rule:
    - actual_closing_amount becomes the opening amount for the next cycle.
    - Existing same-window/channel rows are updated, not duplicated.
    """

    ctx = request.state.user
    start_dt = _parse_dt(payload.start)
    end_dt = _parse_dt(payload.end)

    if not start_dt or not end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start and end are required",
        )

    if end_dt <= start_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end must be after start",
        )

    user_id = ctx.get("id") or ctx.get("user_id")
    saved_rows: List[Dict[str, Any]] = []

    try:
        for incoming in payload.rows:
            row = incoming.model_dump()
            channel = str(row.get("channel") or "").strip().lower()

            if not channel:
                continue

            clean = _recompute_recon_row(row)
            clean["channel"] = channel
            clean["note"] = clean.get("note") or ""
            clean["status"] = "closed"

            db.execute(
                text(
                    """
                    INSERT INTO recon_sheets (
                        tenant_id,
                        branch_id,
                        shift,
                        window_start,
                        window_end,
                        channel,
                        opening_amount,
                        income_amount,
                        expense_amount,
                        cash_in_amount,
                        cash_out_amount,
                        expected_closing_amount,
                        actual_closing_amount,
                        variance_amount,
                        note,
                        status,
                        closed_by_user_id,
                        closed_at,
                        updated_at
                    )
                    VALUES (
                        :tenant_id,
                        :branch_id,
                        :shift,
                        :window_start,
                        :window_end,
                        :channel,
                        :opening_amount,
                        :income_amount,
                        :expense_amount,
                        :cash_in_amount,
                        :cash_out_amount,
                        :expected_closing_amount,
                        :actual_closing_amount,
                        :variance_amount,
                        :note,
                        'closed',
                        :closed_by_user_id,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (
                        tenant_id,
                        branch_id,
                        shift,
                        window_start,
                        window_end,
                        channel
                    )
                    DO UPDATE SET
                        opening_amount = EXCLUDED.opening_amount,
                        income_amount = EXCLUDED.income_amount,
                        expense_amount = EXCLUDED.expense_amount,
                        cash_in_amount = EXCLUDED.cash_in_amount,
                        cash_out_amount = EXCLUDED.cash_out_amount,
                        expected_closing_amount = EXCLUDED.expected_closing_amount,
                        actual_closing_amount = EXCLUDED.actual_closing_amount,
                        variance_amount = EXCLUDED.variance_amount,
                        note = EXCLUDED.note,
                        status = 'closed',
                        closed_by_user_id = EXCLUDED.closed_by_user_id,
                        closed_at = NOW(),
                        updated_at = NOW()
                    """
                ),
                {
                    "tenant_id": ctx["tenant_id"],
                    "branch_id": ctx["branch_id"],
                    "shift": payload.shift,
                    "window_start": start_dt,
                    "window_end": end_dt,
                    "channel": channel,
                    "opening_amount": clean["opening"],
                    "income_amount": clean["income"],
                    "expense_amount": clean["expense"],
                    "cash_in_amount": clean["cashIn"],
                    "cash_out_amount": clean["cashOut"],
                    "expected_closing_amount": clean["expected"],
                    "actual_closing_amount": clean["actual"],
                    "variance_amount": clean["variance"],
                    "note": clean["note"],
                    "closed_by_user_id": user_id,
                },
            )

            saved_rows.append(clean)

        db.commit()

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to close reconciliation: {exc}",
        )

    return {
        "ok": True,
        "status": "closed",
        "shift": payload.shift,
        "window_start": _iso_utc(start_dt),
        "window_end": _iso_utc(end_dt),
        "window_start_business": _iso_business(start_dt),
        "window_end_business": _iso_business(end_dt),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "rows": saved_rows,
    }
