from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)

    # Original staff/waiter/cashier who created the order.
    # This is the commission-safe author field.
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    status = Column(String(50), default="pending_payment")

    subtotal = Column(Numeric(12, 2), default=0)
    total = Column(Numeric(12, 2), default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)

    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"))

    atomic_unit_id = Column(Integer, nullable=False)
    name_snapshot = Column(String, nullable=False)

    unit_price = Column(Numeric(12, 2))
    quantity = Column(Integer)
    line_total = Column(Numeric(12, 2))

    fulfillment_status = Column(String(50), default="waiting")
    fulfilled_at = Column(DateTime, nullable=True)
    fulfilled_by_user_id = Column(Integer, nullable=True)

    order = relationship("Order", back_populates="items")

    modifiers = relationship(
        "OrderItemModifier",
        back_populates="order_item",
        cascade="all, delete-orphan",
    )


class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"

    id = Column(Integer, primary_key=True)

    order_item_id = Column(
        Integer,
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    modifier_type = Column(String(50), nullable=False, default="side")
    name_snapshot = Column(String, nullable=False)

    price_delta = Column(Numeric(12, 2), default=0)
    quantity = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.utcnow)

    order_item = relationship(
        "OrderItem",
        back_populates="modifiers",
    )