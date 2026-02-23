from sqlalchemy import (
    Column,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    Integer,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from database import Base


# -------------------------
# Enums (application-level)
# -------------------------

class PaymentMethod(str, enum.Enum):
    cash = "cash"
    xafpay = "xafpay"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


class PaymentProvider(str, enum.Enum):
    wallet = "wallet"
    mtn = "mtn"
    orange = "orange"
    card = "card"
    bank = "bank"


# -------------------------
# Payment
# -------------------------

class Payment(Base):
    """
    Represents a settlement attempt for a Sale.

    Principles:
    - Payments are authoritative for money movement
    - Sale becomes PAID only when Payment is PAID
    - Inventory is reduced only after payment success
    - Provider is metadata, not logic
    """

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)

    sale_id = Column(
        Integer,
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    method = Column(
        String,
        nullable=False,
        index=True,
    )

    provider = Column(
        String,
        nullable=True,
        index=True,
    )

    amount = Column(
        Numeric(12, 2),
        nullable=False,
    )

    status = Column(
        String,
        nullable=False,
        index=True,
    )

    # External gateway reference
    reference = Column(
        String,
        nullable=True,
        index=True,
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

    # -------------------------
    # Relationships
    # -------------------------

    sale = relationship(
        "Sale",
        back_populates="payments",
    )

    # -------------------------
    # Indexes
    # -------------------------

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
