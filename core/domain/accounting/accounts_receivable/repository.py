from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import String, case, cast, desc, func, or_
from sqlalchemy.orm import Session

from core.domain.accounting.accounts_receivable.models import (
    AccountsReceivable,
    AccountsReceivableRepayment,
)


class AccountsReceivableRepository:

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        ar_id: int,
    ):
        return (
            db.query(AccountsReceivable)
            .filter(
                AccountsReceivable.id == ar_id,
                AccountsReceivable.tenant_id == tenant_id,
                AccountsReceivable.branch_id == branch_id,
            )
            .first()
        )

    @staticmethod
    def get_by_id_for_update(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        ar_id: int,
    ):
        """
        Fetch and lock one A/R row for a mutation.

        Repayments use this to serialize financial changes. AUX1 also reuses
        it for identity-only updates so a concurrent repayment cannot make the
        UI return a stale aggregate after the identity save.
        """

        return (
            db.query(AccountsReceivable)
            .filter(
                AccountsReceivable.id == ar_id,
                AccountsReceivable.tenant_id == tenant_id,
                AccountsReceivable.branch_id == branch_id,
            )
            .with_for_update()
            .first()
        )

    @staticmethod
    def get_by_order_id(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        order_id: int,
    ):
        return (
            db.query(AccountsReceivable)
            .filter(
                AccountsReceivable.tenant_id == tenant_id,
                AccountsReceivable.branch_id == branch_id,
                AccountsReceivable.order_id == order_id,
            )
            .first()
        )

    @staticmethod
    def get_by_sale_id(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
    ):
        return (
            db.query(AccountsReceivable)
            .filter(
                AccountsReceivable.tenant_id == tenant_id,
                AccountsReceivable.branch_id == branch_id,
                AccountsReceivable.sale_id == sale_id,
            )
            .first()
        )

    @staticmethod
    def _filtered_accounts_query(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        status_filter: str = "active",
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        search: str | None = None,
    ):
        query = db.query(AccountsReceivable).filter(
            AccountsReceivable.tenant_id == tenant_id,
            AccountsReceivable.branch_id == branch_id,
        )

        safe_status = str(status_filter or "active").strip().lower()
        if safe_status == "active":
            query = query.filter(AccountsReceivable.status.in_(["open", "partial"]))
        elif safe_status in {"open", "partial", "settled", "cancelled"}:
            query = query.filter(AccountsReceivable.status == safe_status)
        elif safe_status != "all":
            # Fail closed to the operational default instead of silently
            # broadening an unknown filter to every historical account.
            query = query.filter(AccountsReceivable.status.in_(["open", "partial"]))

        if start_at is not None:
            query = query.filter(AccountsReceivable.created_at >= start_at)

        if end_at is not None:
            query = query.filter(AccountsReceivable.created_at < end_at)

        q = str(search or "").strip()
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    AccountsReceivable.customer_name.ilike(like),
                    AccountsReceivable.customer_phone.ilike(like),
                    AccountsReceivable.note.ilike(like),
                    cast(AccountsReceivable.id, String).ilike(like),
                    cast(AccountsReceivable.sale_id, String).ilike(like),
                    cast(AccountsReceivable.order_id, String).ilike(like),
                    cast(AccountsReceivable.payment_intent_id, String).ilike(like),
                )
            )

        return query

    @staticmethod
    def list_accounts(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        status_filter: str = "active",
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        search: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[AccountsReceivable], int]:
        query = AccountsReceivableRepository._filtered_accounts_query(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            status_filter=status_filter,
            start_at=start_at,
            end_at=end_at,
            search=search,
        )

        total_count = query.count()
        rows = (
            query.order_by(
                desc(AccountsReceivable.created_at),
                desc(AccountsReceivable.id),
            )
            .offset(max(0, int(offset)))
            .limit(max(1, int(limit)))
            .all()
        )

        return rows, int(total_count)

    @staticmethod
    def summarize_accounts(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        status_filter: str = "active",
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        query = AccountsReceivableRepository._filtered_accounts_query(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            status_filter=status_filter,
            start_at=start_at,
            end_at=end_at,
            search=search,
        )

        row = query.with_entities(
            func.count(AccountsReceivable.id),
            func.coalesce(
                func.sum(case((AccountsReceivable.status == "open", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((AccountsReceivable.status == "partial", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((AccountsReceivable.status == "settled", 1), else_=0)),
                0,
            ),
            func.coalesce(func.sum(AccountsReceivable.original_amount), 0),
            func.coalesce(func.sum(AccountsReceivable.paid_amount), 0),
            func.coalesce(func.sum(AccountsReceivable.balance_due), 0),
        ).one()

        return {
            "account_count": int(row[0] or 0),
            "open_count": int(row[1] or 0),
            "partial_count": int(row[2] or 0),
            "settled_count": int(row[3] or 0),
            "total_original": row[4] or 0,
            "total_paid": row[5] or 0,
            "total_balance_due": row[6] or 0,
        }

    @staticmethod
    def list_open(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        limit: int = 200,
        offset: int = 0,
    ):
        """Compatibility helper retained for existing Payments searches."""
        rows, _ = AccountsReceivableRepository.list_accounts(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            status_filter="active",
            limit=limit,
            offset=offset,
        )
        return rows

    @staticmethod
    def create(db: Session, ar: AccountsReceivable):
        db.add(ar)

    @staticmethod
    def create_repayment(db: Session, repayment: AccountsReceivableRepayment):
        db.add(repayment)

    @staticmethod
    def get_repayment_by_id(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        repayment_id: int,
    ):
        return (
            db.query(AccountsReceivableRepayment)
            .filter(
                AccountsReceivableRepayment.id == repayment_id,
                AccountsReceivableRepayment.tenant_id == tenant_id,
                AccountsReceivableRepayment.branch_id == branch_id,
            )
            .first()
        )

    @staticmethod
    def list_repayments(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        ar_id: int,
    ):
        return (
            db.query(AccountsReceivableRepayment)
            .filter(
                AccountsReceivableRepayment.tenant_id == tenant_id,
                AccountsReceivableRepayment.branch_id == branch_id,
                AccountsReceivableRepayment.ar_id == ar_id,
            )
            .order_by(desc(AccountsReceivableRepayment.created_at))
            .all()
        )
