from sqlalchemy import (
    Column,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Index,
    JSON,
    and_,
)
from core.domain.sales.models import Sale
from sqlalchemy.orm import relationship, foreign
from sqlalchemy.sql import func
import enum
from datetime import datetime
from database import Base


# =========================================================
# ENUMS
# =========================================================

class PaymentMethod(str, enum.Enum):
    cash = "cash"
    xafpay = "xafpay"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


# -------- NEW ARCHITECTURE ENUMS --------

class PaymentIntentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class PaymentAttemptStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


# =========================================================
# LEGACY PAYMENT (Keep for compatibility)
# =========================================================

class Payment(Base):
    """
    Legacy direct Payment model.
    Kept for backward compatibility only.
    """

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)

    sale_id = Column(
        Integer,
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    method = Column(String, nullable=False, index=True)

    provider = Column(String, nullable=True, index=True)

    amount = Column(Numeric(12, 2), nullable=False)

    status = Column(String, nullable=False, index=True)

    reference = Column(String, nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    completed_at = Column(DateTime(timezone=True), nullable=True)

    sale = relationship("Sale", back_populates="payments")

    __table_args__ = (
        Index("ix_payment_sale_status", "sale_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} "
            f"method={self.method} "
            f"status={self.status} "
            f"amount={self.amount}>"
        )


# =========================================================
# NEW PAYMENT INTENT (PRIMARY ARCHITECTURE)
# =========================================================

class PaymentIntent(Base):
    """
    Authoritative payment aggregate.

    One Sale → One PaymentIntent
    One PaymentIntent → Many PaymentAttempts
    """

    __tablename__ = "payment_intents"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=False, index=True)

    payable_type = Column(String(32), nullable=False)
    payable_id = Column(Integer, nullable=False, index=True)

    currency = Column(String(8), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)

    status = Column(String(32), nullable=False, index=True)

    channel = Column(String(16), nullable=False)

    gateway_intent_id = Column(String(64), nullable=True, unique=True, index=True)

    total_paid = Column(Numeric(12, 2), nullable=False, default=0)
    balance_due = Column(Numeric(12, 2), nullable=False, default=0)

    created_by_user_id = Column(Integer, nullable=False)

    meta = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    attempts = relationship(
        "PaymentAttempt",
        back_populates="intent",
        cascade="all, delete-orphan",
    )

    sale = relationship(
        "Sale",
        primaryjoin=lambda: and_(
            foreign(PaymentIntent.payable_id) == Sale.id,
            PaymentIntent.payable_type == "sale",
        ),
        viewonly=True,
    )

    __table_args__ = (
        Index("ix_intent_payable", "payable_type", "payable_id"),
        Index("ix_intent_tenant_status", "tenant_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentIntent id={self.id} "
            f"status={self.status} "
            f"amount={self.amount} "
            f"paid={self.total_paid}>"
        )


# =========================================================
# PAYMENT ATTEMPT (Append-only ledger)
# =========================================================

class PaymentAttempt(Base):
    """
    Represents a provider-level attempt.

    Immutable. New attempt = retry.
    """

    __tablename__ = "payment_attempts"

    id = Column(Integer, primary_key=True)

    payment_intent_id = Column(
        Integer,
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional link to sale (denormalized for reporting speed)
    sale_id = Column(
        Integer,
        ForeignKey("sales.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Payment classification
    method = Column(String(32), nullable=False, index=True)            # xafpay, cash, wallet
    provider = Column(String(32), nullable=False, index=True)          # tranzak, mtn, orange
    settlement_mode = Column(String(32), nullable=False, index=True)   # async, instant, manual

    # Monetary
    amount = Column(Numeric(12, 2), nullable=False)

    # Status lifecycle
    status = Column(String(32), nullable=False, index=True)            # pending, succeeded, failed

    # Idempotency / references
    client_reference = Column(String(64), nullable=False, unique=True)
    callback_reference = Column(String(128), nullable=True)
    gateway_reference = Column(String(128), nullable=True)
    provider_reference = Column(String(128), nullable=True, index=True)

    cashier_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    # Structured provider metadata
    meta = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    intent = relationship(
        "PaymentIntent",
        back_populates="attempts",
        foreign_keys=[payment_intent_id],
    )

    sale = relationship(
        "Sale",
        foreign_keys=[sale_id],
    )

    __table_args__ = (
        Index("ix_attempt_intent_status", "payment_intent_id", "status"),
        UniqueConstraint(
            "callback_reference",
            name="ux_attempt_callback_reference",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentAttempt id={self.id} "
            f"payment_intent_id={self.payment_intent_id} "
            f"status={self.status} "
            f"amount={self.amount}>"
        )