from sqlalchemy.orm import Session
from sqlalchemy import desc

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
    def list_open(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        limit: int = 200,
        offset: int = 0,
    ):
        return (
            db.query(AccountsReceivable)
            .filter(
                AccountsReceivable.tenant_id == tenant_id,
                AccountsReceivable.branch_id == branch_id,
                AccountsReceivable.status.in_(["open", "partial"]),
            )
            .order_by(
                desc(AccountsReceivable.created_at),
                desc(AccountsReceivable.id),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )

    @staticmethod
    def create(db: Session, ar: AccountsReceivable):
        db.add(ar)

    @staticmethod
    def create_repayment(db: Session, repayment: AccountsReceivableRepayment):
        db.add(repayment)

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