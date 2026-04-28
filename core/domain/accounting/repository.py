from typing import Optional, Dict, Any, List
from datetime import datetime, date, time, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from core.domain.accounting.models import TreasuryLog


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
            occurred_at=occurred_at or datetime.utcnow(),
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

        q = db.query(TreasuryLog).filter(
            TreasuryLog.tenant_id == tenant_id,
            TreasuryLog.branch_id == branch_id,
        )

        if start:
            q = q.filter(TreasuryLog.occurred_at >= start)

        if end:
            q = q.filter(TreasuryLog.occurred_at < end)

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

        rows = (
            TreasuryRepository._base_query(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                start=start,
                end=end,
            )
            .order_by(desc(TreasuryLog.occurred_at), desc(TreasuryLog.id))
            .offset(offset)
            .limit(limit)
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

        rows = (
            TreasuryRepository._base_query(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                start=start,
                end=end,
            )
            .filter(TreasuryLog.event_type.in_(event_types))
            .order_by(desc(TreasuryLog.occurred_at), desc(TreasuryLog.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return rows


    @staticmethod
    def get_sale_logs(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
    ) -> List[TreasuryLog]:

        rows = (
            db.query(TreasuryLog)
            .filter(
                TreasuryLog.tenant_id == tenant_id,
                TreasuryLog.branch_id == branch_id,
                TreasuryLog.reference_type == "sale",
                TreasuryLog.reference_id == sale_id,
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

                "DISCOUNT_APPLIED": "Discount Applied",
                "COMPLIMENTARY_APPLIED": "Complimentary Item",
                "REFUND_PAID": "Refund Paid",

                "PAYMENT_RECEIVED": "Customer Payment",
                "DEBT_CREATED": "Customer Debt",
                "DEBT_REPAYMENT": "Debt Repayment",
                "STORE_CREDIT_CREATED": "Store Credit Issued",
            }

            timestamp = l.occurred_at or l.created_at

            rows.append(
                {
                    "id": l.id,
                    "time": timestamp.strftime("%I:%M %p"),
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