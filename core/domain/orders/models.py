from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=False)

    status = Column(String(50), default="pending_payment")

    subtotal = Column(Numeric(12, 2), default=0)
    total = Column(Numeric(12, 2), default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",   # ✅ FIXED
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)

    order_id = Column(Integer, ForeignKey("orders.id"))

    atomic_unit_id = Column(Integer, nullable=False)
    name_snapshot = Column(String, nullable=False)

    unit_price = Column(Numeric(12, 2))
    quantity = Column(Integer)
    line_total = Column(Numeric(12, 2))

    fulfillment_status = Column(String(50), default="waiting")
    fulfilled_at = Column(DateTime, nullable=True)
    fulfilled_by_user_id = Column(Integer, nullable=True)

    order = relationship("Order", back_populates="items")