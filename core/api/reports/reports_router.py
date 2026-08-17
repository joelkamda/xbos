# core/api/reports/reports_router.py

from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from core.domain.reports.reports_service import ReportsService
from core.rbac.utils.permission_decorator import require_permissions


router = APIRouter(tags=["Reports"])


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _ctx(request: Request):
    """
    Extract authenticated tenant / branch context.

    Current middleware stores context at:
      request.state.user = {
        "user_id": ...,
        "tenant_id": ...,
        "branch_id": ...,
        "role": ...
      }
    """

    ctx = getattr(request.state, "user", None)

    if not ctx or not isinstance(ctx, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication context",
        )

    if not ctx.get("tenant_id") or not ctx.get("branch_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing tenant or branch context",
        )

    return ctx


def _safe_year(year: int) -> int:
    try:
        y = int(year)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid year",
        )

    if y < 2000 or y > 2100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Year must be between 2000 and 2100",
        )

    return y


def _safe_month_key(yyyymm: str) -> str:
    """
    Validate YYYY-MM before passing to service.
    """

    raw = str(yyyymm or "").strip()

    if len(raw) != 7 or raw[4] != "-":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid month format. Expected YYYY-MM.",
        )

    try:
        year = int(raw[:4])
        month = int(raw[5:7])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid month format. Expected YYYY-MM.",
        )

    if year < 2000 or year > 2100 or month < 1 or month > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid month range.",
        )

    return raw


# ============================================================
# MONTHLY SUMMARY
# ============================================================

@router.get("/monthly-summary/{year}")
@require_permissions("report.view", "report.financial", "report.finance.view", "report.financial.overview")
def monthly_summary(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return a 12-month summary for the Reports → Monthly table.

    Shape:
    {
      "year": 2026,
      "rows": [
        {
          "key": "2026-01",
          "income": 0,
          "expense": 0,
          "net": 0,
          "totals": {...}
        }
      ],
      "totals": {
        "income": 0,
        "expense": 0,
        "net": 0
      }
    }
    """

    ctx = _ctx(request)
    safe_year = _safe_year(year)

    try:
        return ReportsService.monthly_summary(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            year=safe_year,
        )

    except Exception as e:
        print("❌ REPORT monthly_summary failed:", str(e))

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate monthly summary",
        )


# ============================================================
# MONTHLY STATEMENT
# ============================================================

@router.get("/monthly-statement/{yyyymm}")
@require_permissions("report.view", "report.financial", "report.finance.view", "report.financial.overview")
def monthly_statement(
    yyyymm: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return the A–F monthly financial statement.

    Rules:
    A. Sales Revenue
       Source of truth = SALE_REVENUE_GROSS treasury logs.
       Detail grouping = sale_items + COMMERCE taxonomy.

    B. Other Income
       Source = OTHER_INCOME + SERVICE_REVENUE treasury logs.

    C. COGS
       Source of truth = explicit treasury/accounting COGS classification.
       - kitchen/manual COGS from treasury COGS classifications,
       - bar/drinks COGS from sold quantity × seeded atomic unit cost.

    D. Gross Profit
       A + B - C

    E. Operating Expenses
       EXPENSE_POSTED excluding COGS classification.

    F. Net Profit

    Shape:
    {
      "month": "2026-05",
      "start": "...",
      "end": "...",
      "totals": {
        "sales": 0,
        "otherIncome": 0,
        "cogs": 0,
        "gross": 0,
        "opex": 0,
        "net": 0
      },
      "sections": {
        "sales": [...],
        "otherIncome": [...],
        "cogs": [...],
        "opex": [...]
      },
      "warnings": [...]
    }
    """

    ctx = _ctx(request)
    safe_month = _safe_month_key(yyyymm)

    try:
        return ReportsService.monthly_statement(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            yyyymm=safe_month,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except Exception as e:
        print("❌ REPORT monthly_statement failed:", str(e))

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate monthly statement",
        )


# ============================================================
# STATEMENT DRILLDOWN PLACEHOLDER
# ============================================================

@router.get("/statement-drilldown/{yyyymm}/{section_key}")
@require_permissions("report.financial", "report.financial.audit")
def statement_drilldown(
    yyyymm: str,
    section_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Placeholder for deeper row-click drilldown.

    Later:
    - sales / Bar / Beer → product mix, tickets, quantity, unit prices
    - otherIncome → manual income rows
    - cogs → COGS source rows and missing-cost diagnostics
    - opex → expense rows, receipt refs, vendors

    For now, this validates routing and returns a stable shape.
    """

    ctx = _ctx(request)
    safe_month = _safe_month_key(yyyymm)

    allowed_sections = {
        "sales",
        "otherIncome",
        "cogs",
        "grossProfit",
        "opex",
        "netProfit",
    }

    if section_key not in allowed_sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid statement section",
        )

    return {
        "month": safe_month,
        "section_key": section_key,
        "tenant_id": ctx["tenant_id"],
        "branch_id": ctx["branch_id"],
        "rows": [],
        "summary": {
            "count": 0,
            "amount": 0,
        },
        "message": "Drilldown will be implemented after the monthly statement is live.",
    }