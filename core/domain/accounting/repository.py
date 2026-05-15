from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import select, desc, or_

from core.domain.accounting.models import TreasuryLog, ReconSheet


# =========================================================
# HELPERS
# =========================================================

def _utc_now() -> datetime:
    """
    Canonical repository timestamp.

    The emitter now sends UTC-aware occurred_at values, but this repository
    still keeps a safe fallback for older/direct calls.
    """

    return datetime.now(timezone.utc)


def _normalize_dt(value: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize datetimes before DB writes/queries.

    - Aware datetime: convert to UTC.
    - Naive datetime: treat as UTC wall-clock to avoid server-local ambiguity.
      Router-level accounting windows already convert Africa/Douala → UTC.
    """

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _d(value: Any) -> Decimal:
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None

    normalized = _normalize_dt(value)
    return normalized.isoformat() if normalized else None


# =========================================================
# REPOSITORY
# =========================================================

class TreasuryRepository:

    # =========================================================
    # IDP LOOKUP (LEDGER SAFETY)
    # =========================================================

    @staticmethod
    def get_by_idempotency(
        db: Session,
        *,
        tenant_id: int,
        idempotency_key: str,
    ) -> Optional[TreasuryLog]:

        stmt = (
            select(TreasuryLog)
            .where(TreasuryLog.tenant_id == tenant_id)
            .where(TreasuryLog.idempotency_key == idempotency_key)
        )

        return db.execute(stmt).scalar_one_or_none()

    # =========================================================
    # LEDGER WRITE (EMITTER ONLY)
    # =========================================================

    @staticmethod
    def record(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        direction: str,
        event_type: str,
        amount,
        currency: str = "XAF",
        channel: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        taxonomy_node_id: Optional[int] = None,
        idempotency_key: str = "",
        occurred_at: Optional[datetime] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> TreasuryLog:

        normalized_occurred_at = _normalize_dt(occurred_at) or _utc_now()

        log = TreasuryLog(
            tenant_id=tenant_id,
            branch_id=branch_id,
            direction=direction,
            event_type=event_type,
            amount=amount,
            currency=currency,
            channel=channel,
            reference_type=reference_type,
            reference_id=reference_id,
            taxonomy_node_id=taxonomy_node_id,
            idempotency_key=idempotency_key,
            occurred_at=normalized_occurred_at,
            meta=meta or {},
        )

        db.add(log)

        return log

    # =========================================================
    # INTERNAL BASE QUERY
    # =========================================================

    @staticmethod
    def _base_query(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ):

        start_dt = _normalize_dt(start)
        end_dt = _normalize_dt(end)

        q = db.query(TreasuryLog).filter(
            TreasuryLog.tenant_id == tenant_id,
            TreasuryLog.branch_id == branch_id,
        )

        if start_dt:
            q = q.filter(TreasuryLog.occurred_at >= start_dt)

        if end_dt:
            q = q.filter(TreasuryLog.occurred_at < end_dt)

        return q

    # =========================================================
    # GENERIC LEDGER QUERIES
    # =========================================================

    @staticmethod
    def list_logs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TreasuryLog]:

        safe_limit = max(1, min(int(limit or 100), 5000))
        safe_offset = max(0, int(offset or 0))

        rows = (
            TreasuryRepository._base_query(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                start=start,
                end=end,
            )
            .order_by(desc(TreasuryLog.occurred_at), desc(TreasuryLog.id))
            .offset(safe_offset)
            .limit(safe_limit)
            .all()
        )

        return rows

    @staticmethod
    def list_by_event_types(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        event_types: List[str],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[TreasuryLog]:

        safe_limit = max(1, min(int(limit or 200), 5000))
        safe_offset = max(0, int(offset or 0))

        rows = (
            TreasuryRepository._base_query(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                start=start,
                end=end,
            )
            .filter(TreasuryLog.event_type.in_(event_types or []))
            .order_by(desc(TreasuryLog.occurred_at), desc(TreasuryLog.id))
            .offset(safe_offset)
            .limit(safe_limit)
            .all()
        )

        return rows

    # =========================================================
    # RECONCILIATION PERSISTENCE
    # =========================================================

    @staticmethod
    def get_previous_closed_reconciliation_by_channel(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        before: Optional[datetime],
    ) -> Dict[str, float]:
        """
        Return the latest actual closing amount per channel before a window.

        Carry-forward rule:
            previous actual_closing_amount => next opening_amount

        Includes both closed and approved statuses so future approval workflow
        does not break opening balance carry-forward.
        """

        before_dt = _normalize_dt(before)

        if not before_dt:
            return {}

        rows = (
            db.query(ReconSheet)
            .filter(
                ReconSheet.tenant_id == tenant_id,
                ReconSheet.branch_id == branch_id,
                ReconSheet.window_end <= before_dt,
                ReconSheet.status.in_(["closed", "approved"]),
            )
            .order_by(
                ReconSheet.channel.asc(),
                ReconSheet.window_end.desc(),
                ReconSheet.id.desc(),
            )
            .all()
        )

        result: Dict[str, float] = {}

        for row in rows:
            channel = str(row.channel or "").strip().lower()

            if not channel:
                continue

            if channel not in result:
                result[channel] = _f(row.actual_closing_amount)

        return result

    @staticmethod
    def get_existing_reconciliation_window(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        shift: str,
        window_start: Optional[datetime],
        window_end: Optional[datetime],
    ) -> Dict[str, ReconSheet]:
        """
        Return persisted reconciliation rows for one exact window.

        Keyed by channel:
            cash, mtn, orange, xafpay, bank, ar, ap
        """

        start_dt = _normalize_dt(window_start)
        end_dt = _normalize_dt(window_end)

        if not start_dt or not end_dt:
            return {}

        rows = (
            db.query(ReconSheet)
            .filter(
                ReconSheet.tenant_id == tenant_id,
                ReconSheet.branch_id == branch_id,
                ReconSheet.shift == shift,
                ReconSheet.window_start == start_dt,
                ReconSheet.window_end == end_dt,
            )
            .order_by(ReconSheet.channel.asc())
            .all()
        )

        return {
            str(row.channel or "").strip().lower(): row
            for row in rows
            if row.channel
        }

    @staticmethod
    def upsert_reconciliation_rows(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        shift: str,
        window_start: datetime,
        window_end: datetime,
        rows: List[Dict[str, Any]],
        closed_by_user_id: Optional[int] = None,
        status: str = "closed",
    ) -> List[ReconSheet]:
        """
        Create or update reconciliation rows.

        The database has a unique index on:
            tenant_id, branch_id, shift, window_start, window_end, channel

        This method honors that uniqueness without requiring raw SQL upsert.
        The caller is responsible for db.commit().
        """

        saved: List[ReconSheet] = []

        start_dt = _normalize_dt(window_start)
        end_dt = _normalize_dt(window_end)

        if not start_dt or not end_dt:
            return saved

        safe_status = str(status or "closed").strip().lower()
        if safe_status not in {"draft", "closed", "approved", "reopened"}:
            safe_status = "closed"

        existing_map = TreasuryRepository.get_existing_reconciliation_window(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            shift=shift,
            window_start=start_dt,
            window_end=end_dt,
        )

        now = _utc_now()

        for incoming in rows:
            channel = str(incoming.get("channel") or "").strip().lower()

            if not channel:
                continue

            opening = _d(incoming.get("opening"))
            income = _d(incoming.get("income"))
            expense = _d(incoming.get("expense"))
            cash_in = _d(incoming.get("cashIn"))
            cash_out = _d(incoming.get("cashOut"))

            expected = opening + income - expense + cash_in - cash_out
            actual = _d(incoming.get("actual", expected))
            variance = actual - expected

            note = incoming.get("note") or ""

            meta = incoming.get("meta") or {}
            if not isinstance(meta, dict):
                meta = {}

            # Make the persisted window auditable.
            meta = {
                **meta,
                "window_start_utc": _iso(start_dt),
                "window_end_utc": _iso(end_dt),
            }

            row = existing_map.get(channel)

            if row:
                row.opening_amount = opening
                row.income_amount = income
                row.expense_amount = expense
                row.cash_in_amount = cash_in
                row.cash_out_amount = cash_out
                row.expected_closing_amount = expected
                row.actual_closing_amount = actual
                row.variance_amount = variance
                row.note = note
                row.status = safe_status
                row.closed_by_user_id = closed_by_user_id
                row.closed_at = now
                row.updated_at = now
                row.meta = meta or row.meta
            else:
                row = ReconSheet(
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    shift=shift,
                    window_start=start_dt,
                    window_end=end_dt,
                    channel=channel,
                    opening_amount=opening,
                    income_amount=income,
                    expense_amount=expense,
                    cash_in_amount=cash_in,
                    cash_out_amount=cash_out,
                    expected_closing_amount=expected,
                    actual_closing_amount=actual,
                    variance_amount=variance,
                    note=note,
                    status=safe_status,
                    closed_by_user_id=closed_by_user_id,
                    closed_at=now,
                    meta=meta,
                )

                db.add(row)

            saved.append(row)

        db.flush()

        return saved

    @staticmethod
    def serialize_reconciliation_sheet(row: ReconSheet) -> Dict[str, Any]:
        """
        Convert a persisted ReconSheet row into the frontend ReconRow shape.
        """

        return {
            "channel": row.channel,
            "opening": _f(row.opening_amount),
            "income": _f(row.income_amount),
            "expense": _f(row.expense_amount),
            "cashIn": _f(row.cash_in_amount),
            "cashOut": _f(row.cash_out_amount),
            "expected": _f(row.expected_closing_amount),
            "actual": _f(row.actual_closing_amount),
            "variance": _f(row.variance_amount),
            "note": row.note or "",
            "status": row.status or "closed",
        }

    # =========================================================
    # DOCUMENT-SPECIFIC LEDGER QUERIES
    # =========================================================

    @staticmethod
    def get_sale_logs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
    ) -> List[TreasuryLog]:
        """
        Return the complete accounting event family for a sale.

        Important:
        Some sale events are direct sale references:
            reference_type = "sale"
            reference_id = sale_id

        But payment collection events usually reference payment attempts:
            reference_type = "payment_attempt"
            reference_id = attempt_id

        Those payment rows still carry the sale identity inside JSON meta:
            meta.sale_id = sale_id

        The Income screen settlement panel needs both families so it can show:
            Gross Revenue
            Collection
            Discount / Comp
            A/R
            A/P
            Tips
            Unallocated
        """

        sale_id_str = str(sale_id)

        rows = (
            db.query(TreasuryLog)
            .filter(
                TreasuryLog.tenant_id == tenant_id,
                TreasuryLog.branch_id == branch_id,
            )
            .filter(
                or_(
                    # Direct sale ledger rows:
                    # SALE_REVENUE_GROSS, DISCOUNT_APPLIED,
                    # COMPLIMENTARY_APPLIED, DEBT_CREATED, etc.
                    (
                        (TreasuryLog.reference_type == "sale")
                        & (TreasuryLog.reference_id == sale_id)
                    ),

                    # Payment attempt / intent rows that carry sale_id in JSON meta.
                    # PostgreSQL JSONB path via SQLAlchemy index operator.
                    TreasuryLog.meta.op("->>")("sale_id") == sale_id_str,
                )
            )
            .order_by(desc(TreasuryLog.occurred_at), desc(TreasuryLog.id))
            .all()
        )

        return rows

    @staticmethod
    def get_attempt_logs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        attempt_id: int,
    ) -> List[TreasuryLog]:

        rows = (
            db.query(TreasuryLog)
            .filter(
                TreasuryLog.tenant_id == tenant_id,
                TreasuryLog.branch_id == branch_id,
                TreasuryLog.reference_type == "payment_attempt",
                TreasuryLog.reference_id == attempt_id,
            )
            .order_by(desc(TreasuryLog.occurred_at), desc(TreasuryLog.id))
            .all()
        )

        return rows

    # =========================================================
    # UI VIEW → DAILY ACCOUNTING SCREEN
    # =========================================================

    @staticmethod
    def daily_rows(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        limit: int = 200,
    ) -> List[Dict]:

        logs = TreasuryRepository.list_logs(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            limit=limit,
        )

        rows: List[Dict] = []

        for l in logs:

            # ----------------------------
            # Map event → UI row type
            # ----------------------------

            type_map = {
                "SALE_REVENUE_GROSS": "income",
                "TIP_REVENUE": "income",
                "SERVICE_REVENUE": "income",
                "OTHER_INCOME": "income",

                "DISCOUNT_APPLIED": "expense",
                "COMPLIMENTARY_APPLIED": "expense",
                "EXPENSE_POSTED": "expense",
                "COGS_RECOGNIZED": "expense",
                "REFUND_PAID": "expense",

                "PAYMENT_RECEIVED": "movement",
                "CASH_MOVE": "movement",
                "DEBT_CREATED": "movement",
                "DEBT_REPAYMENT": "movement",
                "STORE_CREDIT_CREATED": "movement",
            }

            entry_map = {
                "SALE_REVENUE_GROSS": "Sales Revenue · Restaurant",
                "TIP_REVENUE": "Other Income · Tips / Service",
                "SERVICE_REVENUE": "Service Revenue",
                "OTHER_INCOME": "Other Income",

                "DISCOUNT_APPLIED": "Discount Applied",
                "COMPLIMENTARY_APPLIED": "Complimentary Item",
                "EXPENSE_POSTED": "Expense",
                "COGS_RECOGNIZED": "COGS Recognized",
                "REFUND_PAID": "Refund Paid",

                "PAYMENT_RECEIVED": "Customer Payment",
                "CASH_MOVE": "Cash Movement",
                "DEBT_CREATED": "Customer Debt",
                "DEBT_REPAYMENT": "Debt Repayment",
                "STORE_CREDIT_CREATED": "Store Credit Issued",
            }

            timestamp = l.occurred_at or l.created_at
            normalized_timestamp = _normalize_dt(timestamp)

            rows.append(
                {
                    "id": l.id,
                    "time": normalized_timestamp.strftime("%I:%M %p")
                    if normalized_timestamp
                    else "",
                    "occurred_at": _iso(l.occurred_at),
                    "created_at": _iso(l.created_at),
                    "date": _iso(normalized_timestamp),
                    "type": type_map.get(l.event_type, "movement"),
                    "entry": entry_map.get(l.event_type, l.event_type),
                    "channel": l.channel,
                    "amount": float(l.amount),
                    "reference_type": l.reference_type,
                    "reference_id": l.reference_id,
                    "details": l.meta or {},
                    "event_type": l.event_type,
                    "direction": l.direction,
                    "currency": l.currency,
                }
            )

        return rows

    # =========================================================
    # SUMMARY (TOP CARDS IN UI)
    # =========================================================

    @staticmethod
    def daily_summary(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
    ) -> Dict:

        rows = TreasuryRepository.daily_rows(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

        income = 0.0
        expense = 0.0

        for r in rows:

            if r["type"] == "income":
                income += r["amount"]

            elif r["type"] == "expense":
                expense += abs(r["amount"])

        return {
            "income": income,
            "expense": expense,
            "net": income - expense,
            "rows": len(rows),
        }