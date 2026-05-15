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
    
class ReconSheet(Base):
    __tablename__ = "recon_sheets"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=False, index=True)

    # day | night | full24
    shift = Column(String(30), nullable=False, default="full24", index=True)

    window_start = Column(DateTime(timezone=True), nullable=False, index=True)
    window_end = Column(DateTime(timezone=True), nullable=False, index=True)

    # cash | mtn | orange | xafpay | bank | ar | ap
    channel = Column(String(32), nullable=False, index=True)

    opening_amount = Column(Numeric(14, 2), nullable=False, default=0)

    income_amount = Column(Numeric(14, 2), nullable=False, default=0)
    expense_amount = Column(Numeric(14, 2), nullable=False, default=0)
    cash_in_amount = Column(Numeric(14, 2), nullable=False, default=0)
    cash_out_amount = Column(Numeric(14, 2), nullable=False, default=0)

    expected_closing_amount = Column(Numeric(14, 2), nullable=False, default=0)
    actual_closing_amount = Column(Numeric(14, 2), nullable=False, default=0)
    variance_amount = Column(Numeric(14, 2), nullable=False, default=0)

    note = Column(String, nullable=True)

    # draft | closed | approved | reopened
    status = Column(String(30), nullable=False, default="closed", index=True)

    closed_by_user_id = Column(Integer, nullable=True, index=True)
    approved_by_user_id = Column(Integer, nullable=True, index=True)

    closed_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    meta = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ux_recon_tenant_branch_shift_window_channel",
            "tenant_id",
            "branch_id",
            "shift",
            "window_start",
            "window_end",
            "channel",
            unique=True,
        ),
        Index(
            "ix_recon_previous_close",
            "tenant_id",
            "branch_id",
            "channel",
            "window_end",
        ),
        Index(
            "ix_recon_window",
            "tenant_id",
            "branch_id",
            "window_start",
            "window_end",
        ),
    )