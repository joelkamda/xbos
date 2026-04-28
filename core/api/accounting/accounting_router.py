from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database import get_db
from core.domain.accounting.repository import TreasuryRepository

router = APIRouter(tags=["Accounting"])


# ============================================================
# INTERNAL UTIL
# ============================================================

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _serialize_log(log):
    """
    Prevents returning raw SQLAlchemy objects.
    """
    timestamp = log.occurred_at or log.created_at

    return {
        "id": log.id,
        "time": timestamp.strftime("%I:%M %p"),
        "event_type": log.event_type,
        "direction": log.direction,
        "amount": float(log.amount),
        "currency": log.currency,
        "channel": log.channel,
        "reference_type": log.reference_type,
        "reference_id": log.reference_id,
        "details": log.meta or {},
    }


# ============================================================
# TREASURY LEDGER FEED
# ============================================================

@router.get("/treasury")
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

    items = [_serialize_log(l) for l in logs]

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
        "events": [_serialize_log(l) for l in logs],
    }


# ============================================================
# PAYMENT ATTEMPT DETAILS
# ============================================================

@router.get("/attempt/{attempt_id}")
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
        "events": [_serialize_log(l) for l in logs],
    }


# ============================================================
# DAILY ACCOUNTING VIEW (USED BY ACCOUNTING UI)
# ============================================================

@router.get("/daily")
def accounting_daily(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    start: Optional[str] = None,
    end: Optional[str] = None,
):

    ctx = request.state.user

    rows = TreasuryRepository.daily_rows(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
        limit=limit,
    )

    income = 0.0
    expense = 0.0

    for r in rows:

        if r["type"] == "income":
            income += r["amount"]

        elif r["type"] == "expense":
            expense += abs(r["amount"])

    net = income - expense

    return {
        "summary": {
            "income": income,
            "expense": expense,
            "net": net,
            "rows": len(rows),
        },
        "rows": rows,
    }


# ============================================================
# DAILY FINANCIAL SUMMARY (QUICK DASHBOARD CARD)
# ============================================================

@router.get("/summary")
def financial_summary(
    request: Request,
    db: Session = Depends(get_db),
):

    ctx = request.state.user

    summary = TreasuryRepository.daily_summary(
        db,
        tenant_id=ctx["tenant_id"],
        branch_id=ctx["branch_id"],
    )

    return summary

@router.get("/reconciliation")
async def get_reconciliation(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Returns reconciliation rows for all channels.
    """

    # temporary mock until service implemented

    return [
        {
            "channel": "cash",
            "opening": 112000,
            "income": 182000,
            "expense": 195303,
            "cashIn": 35000,
            "cashOut": 13000,
            "expected": 120697,
            "actual": 101000,
            "variance": -19697,
            "note": "",
        },
        {
            "channel": "mtn",
            "opening": 1337700,
            "income": 69000,
            "expense": 0,
            "cashIn": 0,
            "cashOut": 0,
            "expected": 1406700,
            "actual": 1405700,
            "variance": -1000,
            "note": "",
        },
        {
            "channel": "orange",
            "opening": 38100,
            "income": 70000,
            "expense": 0,
            "cashIn": 0,
            "cashOut": 35000,
            "expected": 73100,
            "actual": 75580,
            "variance": 2480,
            "note": "",
        },
        {
            "channel": "bank",
            "opening": 370000,
            "income": 0,
            "expense": 0,
            "cashIn": 0,
            "cashOut": 0,
            "expected": 370000,
            "actual": 370000,
            "variance": 0,
            "note": "",
        },
        {
            "channel": "ar",
            "opening": 67500,
            "income": 3500,
            "expense": 0,
            "cashIn": 0,
            "cashOut": 0,
            "expected": 71000,
            "actual": 71000,
            "variance": 0,
            "note": "",
        },
        {
            "channel": "ap",
            "opening": 0,
            "income": 0,
            "expense": 0,
            "cashIn": 0,
            "cashOut": 0,
            "expected": 0,
            "actual": 0,
            "variance": 0,
            "note": "",
        },
    ]