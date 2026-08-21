from datetime import datetime, timezone

from sqlalchemy import Column, Integer, BigInteger, String, Numeric, DateTime, ForeignKey

from database import Base


def _utc_now_naive() -> datetime:
    """
    Safe default timestamp for current A/R tables.

    Current A/R model columns are plain DateTime, which usually maps to
    timestamp WITHOUT time zone unless the DB was migrated otherwise.

    So we store UTC wall-clock as naive here for compatibility.

    Long-term preferred migration:
    - Convert accounts_receivable timestamps to timestamptz.
    - Then use timezone-aware datetime.now(timezone.utc) directly.
    """

    return datetime.now(timezone.utc).replace(tzinfo=None)


class AccountsReceivable(Base):
    __tablename__ = "accounts_receivable"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)

    order_id = Column(Integer, nullable=True)
    sale_id = Column(Integer, nullable=True)
    payment_intent_id = Column(String, nullable=True)

    customer_id = Column(BigInteger, nullable=True)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    note = Column(String, nullable=True)

    original_amount = Column(Numeric(12, 2), nullable=False, default=0)
    paid_amount = Column(Numeric(12, 2), nullable=False, default=0)
    balance_due = Column(Numeric(12, 2), nullable=False, default=0)

    status = Column(String(30), nullable=False, default="open")

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=_utc_now_naive)
    updated_at = Column(DateTime, default=_utc_now_naive, onupdate=_utc_now_naive)
    settled_at = Column(DateTime, nullable=True)


class AccountsReceivableRepayment(Base):
    __tablename__ = "accounts_receivable_repayments"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)

    ar_id = Column(Integer, ForeignKey("accounts_receivable.id"), nullable=False)

    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(50), nullable=False, default="cash")
    reference = Column(String, nullable=True)
    note = Column(String, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utc_now_naive)