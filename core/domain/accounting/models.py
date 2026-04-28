from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, ForeignKey, Index, JSON
)
from sqlalchemy.sql import func
from database import Base


class TreasuryLog(Base):
    __tablename__ = "treasury_logs"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=False, index=True)

    # credit | debit
    direction = Column(String(8), nullable=False, index=True)

    # SALE_REVENUE, PAYMENT_RECEIVED, DISCOUNT_APPLIED, etc.
    event_type = Column(String(32), nullable=False, index=True)

    # cash | mtn | orange | xafpay | ...
    channel = Column(String(32), nullable=True, index=True)

    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(8), nullable=False, default="XAF")

    # links to any object in system (sale, payment_attempt, debt, etc.)
    reference_type = Column(String(32), nullable=True)
    reference_id = Column(Integer, nullable=True, index=True)

    # unified classification link (taxonomy node)
    taxonomy_node_id = Column(
        Integer,
        ForeignKey("taxonomy_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # the key to scaling + preventing duplicates forever
    idempotency_key = Column(String(128), nullable=False)

    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    meta = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_tlog_tenant_branch_time", "tenant_id", "branch_id", "occurred_at"),
        Index("ix_tlog_tenant_event_time", "tenant_id", "event_type", "occurred_at"),
        Index("ix_tlog_tenant_tax_time", "tenant_id", "taxonomy_node_id", "occurred_at"),
        Index("ux_tlog_tenant_idem", "tenant_id", "idempotency_key", unique=True),
        Index("ix_treasury_reference", "reference_type", "reference_id"),
    )