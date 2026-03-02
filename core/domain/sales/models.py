from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    ForeignKey,
    DateTime,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from database import Base


# =====================================================
# Enums (application-level, stored as STRING values)
# =====================================================

class SaleStatus(str, enum.Enum):
    pending_payment = "pending_payment"   # bill issued
    paid = "paid"                         # receipt issued
    cancelled = "cancelled"               # terminal


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    xafpay = "xafpay"


# =====================================================
# Sale (header)
# =====================================================

class Sale(Base):
    """
    Represents a finalized commercial intent.

    INVARIANTS (LOCKED):
    - Created once
    - Receipt number immutable
    - Items immutable
    - Status transitions driven ONLY by Payments
    - Commercial truth limited to subtotal / total
    """

    __tablename__ = "sales"

    # -------------------------
    # Identity
    # -------------------------

    id = Column(Integer, primary_key=True)

    receipt_no = Column(
        String(32),
        nullable=False,
        comment="Human-readable receipt / bill number",
    )

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

    cashier_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    discount_total = Column(Numeric(12,2), nullable=False, default=0)
    complimentary_total = Column(Numeric(12,2), nullable=False, default=0)
    tendered_total = Column(Numeric(12,2), nullable=False, default=0)
    change_amount = Column(Numeric(12,2), nullable=False, default=0)
    unpaid_amount = Column(Numeric(12,2), nullable=False, default=0)

    # -------------------------
    # Commercial state
    # -------------------------

    status = Column(
        String(32),
        nullable=False,
        index=True,
        comment="SaleStatus enum value",
    )

    payment_method = Column(
        String(32),
        nullable=False,
        comment="Initial payment method intent (PaymentMethod enum value)",
    )

    # -------------------------
    # Money (commercial truth)
    # -------------------------

    subtotal = Column(
        Numeric(12, 2),
        nullable=False,
    )

    total = Column(
        Numeric(12, 2),
        nullable=False,
    )

    # -------------------------
    # Timestamps
    # -------------------------

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    paid_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # -------------------------
    # Relationships
    # -------------------------

    items = relationship(
        "SaleItem",
        back_populates="sale",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    payments = relationship(
        "Payment",
        back_populates="sale",
        lazy="selectin",
    )

    # -------------------------
    # Constraints & indexes
    # -------------------------

    __table_args__ = (
        # Receipt uniqueness per tenant + branch
        Index(
            "ux_sales_receipt_no",
            "tenant_id",
            "branch_id",
            "receipt_no",
            unique=True,
        ),
        # Operational query index
        Index(
            "ix_sales_tenant_branch_created",
            "tenant_id",
            "branch_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} "
            f"receipt_no={self.receipt_no} "
            f"status={self.status} "
            f"total={self.total}>"
        )


# =====================================================
# SaleItem (line items)
# =====================================================

class SaleItem(Base):
    """
    Immutable snapshot of a billable unit at time of sale.

    GUARANTEES:
    - Name never changes
    - Unit price never changes
    - quantity × unit_price = line_total
    """

    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True)

    sale_id = Column(
        Integer,
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    billable_unit_id = Column(
        Integer,
        ForeignKey("billable_units.id"),
        nullable=False,
        index=True,
    )

    name_snapshot = Column(
        String,
        nullable=False,
    )

    unit_price = Column(
        Numeric(12, 2),
        nullable=False,
    )

    quantity = Column(
        Integer,
        nullable=False,
    )

    line_total = Column(
        Numeric(12, 2),
        nullable=False,
    )

    sale = relationship(
        "Sale",
        back_populates="items",
    )

    __table_args__ = (
        Index("ix_sale_items_sale", "sale_id"),
        CheckConstraint(
            "quantity > 0",
            name="ck_sale_item_quantity_positive",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SaleItem id={self.id} "
            f"name='{self.name_snapshot}' "
            f"{self.quantity} × {self.unit_price}>"
        )
