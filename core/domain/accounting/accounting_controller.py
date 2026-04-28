from datetime import datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from core.domain.accounting.reports import AccountingReportsService


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    return datetime.fromisoformat(v)


class AccountingController:

    @staticmethod
    def daily(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = request.state.user
        return AccountingReportsService.daily_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def income(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = request.state.user
        return AccountingReportsService.income_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def expenses(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = request.state.user
        return AccountingReportsService.expenses_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def cash_moves(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = request.state.user
        return AccountingReportsService.cash_moves_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def debt(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ):
        ctx = request.state.user
        return AccountingReportsService.debt_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def reconciliation(
        *,
        request: Request,
        db: Session,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ):
        ctx = request.state.user
        return AccountingReportsService.reconciliation_view(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            start=_parse_dt(start),
            end=_parse_dt(end),
            limit=limit,
            offset=offset,
        )