from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from database import Base


# =====================================================
# ENUMS (stored as STRING values)
# =====================================================

class PaymentIntentStatus(str, enum.Enum):
    created = "created"
    pending = "pending"
    partially_paid = "partially_paid"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


class PaymentAttemptStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    xafpay = "xafpay"
    mtn = "mtn"
    orange = "orange"
    split = "split"  # UI-level grouping


class PaymentProvider(str, enum.Enum):
    direct = "direct"        # cashier-confirmed finality
    xafpay = "xafpay"        # gateway
    wallet = "wallet"
    card = "card"
    bank = "bank"


class SettlementMode(str, enum.Enum):
    instant = "instant"              # cash, direct momo
    async_gateway = "async_gateway"  # xafpay, card, bank


class PayableType(str, enum.Enum):
    sale = "sale"
    debt = "debt"
    invoice = "invoice"
    other = "other"


# =====================================================
# PAYMENT INTENT
# =====================================================

class PaymentIntent(Base):
    """
    Represents a payable obligation.

    KEY RULES:
    - Inventory is deducted ONLY when intent becomes fully PAID.
    - Sale is marked PAID ONLY when intent becomes fully PAID.
    - Supports split payments natively.
    """

    __tablename__ = "payment_intents"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    branch_id = Column(
        Integer,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    payable_type = Column(
        String(32),
        nullable=False,
        index=True,
        comment="PayableType enum value",
    )

    payable_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="ID in payable table (e.g. sales.id)",
    )

    currency = Column(
        String(8),
        nullable=False,
        default="XAF",
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False,
    )

    status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="PaymentIntentStatus enum value",
    )

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    channel = Column(
        String(16),
        nullable=False,
        default="pos",
        comment="pos|api|invoice",
    )

    # Aggregates (authoritative recomputed values)
    total_paid = Column(
        Numeric(12, 2),
        nullable=False,
        server_default="0",
    )

    balance_due = Column(
        Numeric(12, 2),
        nullable=False,
        server_default="0",
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    attempts = relationship(
        "PaymentAttempt",
        back_populates="intent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_pi_tenant_branch_created", "tenant_id", "branch_id", "created_at"),
        Index("ix_pi_payable_lookup", "payable_type", "payable_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentIntent id={self.id} "
            f"status={self.status} "
            f"amount={self.amount}>"
        )


# =====================================================
# PAYMENT ATTEMPT
# =====================================================

class PaymentAttempt(Base):
    """
    Represents a single settlement attempt.

    RULES:
    - Terminal once PAID/FAILED/CANCELLED
    - Webhook-safe via callback_reference uniqueness
    - Client-safe via client_reference uniqueness
    """

    __tablename__ = "payment_attempts"

    id = Column(Integer, primary_key=True)

    payment_intent_id = Column(
        Integer,
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional convenience link when payable is sale
    sale_id = Column(
        Integer,
        ForeignKey("sales.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    method = Column(
        String(32),
        nullable=False,
        index=True,
        comment="PaymentMethod enum value",
    )

    provider = Column(
        String(32),
        nullable=True,
        index=True,
        comment="PaymentProvider enum value",
    )

    settlement_mode = Column(
        String(32),
        nullable=False,
        index=True,
        comment="SettlementMode enum value",
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False,
    )

    status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="PaymentAttemptStatus enum value",
    )

    # Idempotency
    client_reference = Column(
        String(64),
        nullable=False,
        comment="Client idempotency key (POS/API)",
    )

    callback_reference = Column(
        String(128),
        nullable=True,
        comment="Provider webhook idempotency key",
    )

    # External references
    gateway_reference = Column(
        String(128),
        nullable=True,
        index=True,
    )

    provider_reference = Column(
        String(128),
        nullable=True,
        index=True,
    )

    cashier_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    provider_meta = Column(
        JSON,
        nullable=True,
    )

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
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_pa_intent_status", "payment_intent_id", "status"),
        UniqueConstraint("client_reference", name="ux_pa_client_reference"),
        UniqueConstraint("callback_reference", name="ux_pa_callback_reference"),
        CheckConstraint("amount > 0", name="ck_pa_amount_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentAttempt id={self.id} "
            f"status={self.status} "
            f"amount={self.amount}>"
        )