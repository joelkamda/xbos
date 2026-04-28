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
from sqlalchemy.dialects.postgresql import JSON

import enum

from database import Base


# =====================================================
# Enums
# =====================================================

class SaleStatus(str, enum.Enum):
    pending_payment = "pending_payment"
    paid = "paid"
    cancelled = "cancelled"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    xafpay = "xafpay"


# =====================================================
# Sale (header)
# =====================================================

class Sale(Base):
    __tablename__ = "sales"

    # -------------------------
    # Identity
    # -------------------------

    id = Column(Integer, primary_key=True)

    receipt_no = Column(
        String(32),
        nullable=False,
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

    # 🔥 CRITICAL FIX (DB ALREADY HAS THIS)
    order_id = Column(
        Integer,
        nullable=True,
        unique=True,
        index=True,
        comment="Link back to originating order",
    )

    # -------------------------
    # Financial breakdown
    # -------------------------

    discount_total = Column(Numeric(12, 2), nullable=False, default=0)
    complimentary_total = Column(Numeric(12, 2), nullable=False, default=0)
    tendered_total = Column(Numeric(12, 2), nullable=False, default=0)
    change_amount = Column(Numeric(12, 2), nullable=False, default=0)
    unpaid_amount = Column(Numeric(12, 2), nullable=False, default=0)

    payment_summary = Column(
        JSON,
        nullable=True,
        comment="Breakdown of payment methods (UI/analytics only)",
    )

    # -------------------------
    # Commercial state
    # -------------------------

    status = Column(
        String(32),
        nullable=False,
        index=True,
    )

    payment_method = Column(
        String(32),
        nullable=False,
    )

    # -------------------------
    # Money (truth)
    # -------------------------

    subtotal = Column(Numeric(12, 2), nullable=False)
    total = Column(Numeric(12, 2), nullable=False)

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

        # Receipt uniqueness
        Index(
            "ux_sales_receipt_no",
            "tenant_id",
            "branch_id",
            "receipt_no",
            unique=True,
        ),

        # Query optimization
        Index(
            "ix_sales_tenant_branch_created",
            "tenant_id",
            "branch_id",
            "created_at",
        ),

        # 🔥 Financial integrity
        CheckConstraint("subtotal >= 0", name="ck_sales_subtotal_non_negative"),
        CheckConstraint("total >= 0", name="ck_sales_total_non_negative"),
        CheckConstraint("discount_total >= 0", name="ck_sales_discount_non_negative"),
        CheckConstraint("complimentary_total >= 0", name="ck_sales_complimentary_non_negative"),
        CheckConstraint("tendered_total >= 0", name="ck_sales_tendered_non_negative"),
        CheckConstraint("change_amount >= 0", name="ck_sales_change_non_negative"),
        CheckConstraint("unpaid_amount >= 0", name="ck_sales_unpaid_non_negative"),
    )

    def __repr__(self) -> str:
        return (
            f"<Sale id={self.id} "
            f"receipt_no={self.receipt_no} "
            f"order_id={self.order_id} "
            f"status={self.status} "
            f"total={self.total}>"
        )


# =====================================================
# SaleItem (line items)
# =====================================================

class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True)

    sale_id = Column(
        Integer,
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    atomic_unit_id = Column(
        Integer,
        ForeignKey("atomic_units.id"),
        nullable=False,
        index=True,
    )

    name_snapshot = Column(String, nullable=False)

    unit_price = Column(Numeric(12, 2), nullable=False)

    quantity = Column(Integer, nullable=False)

    line_total = Column(Numeric(12, 2), nullable=False)

    sale = relationship(
        "Sale",
        back_populates="items",
    )

    __table_args__ = (
        Index("ix_sale_items_sale", "sale_id"),
        CheckConstraint("quantity > 0", name="ck_sale_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_sale_item_price_non_negative"),
        CheckConstraint("line_total >= 0", name="ck_sale_item_total_non_negative"),
    )

    def __repr__(self) -> str:
        return (
            f"<SaleItem id={self.id} "
            f"name='{self.name_snapshot}' "
            f"{self.quantity} × {self.unit_price}>"
        )