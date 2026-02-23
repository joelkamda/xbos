from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base   # ✅ FIXED import


# -------------------------------------------------
# InventoryItem (cached state)
# -------------------------------------------------

class InventoryItem(Base):
    """
    Cached inventory state for a BillableUnit at a specific branch.

    IMPORTANT:
    - quantity_on_hand is a CACHE
    - authoritative truth is InventoryMovement
    - quantity_on_hand MUST ONLY change inside the same transaction
      that inserts an InventoryMovement
    """

    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(
        Integer,
        nullable=False,
        index=True,
    )

    branch_id = Column(
        Integer,
        nullable=False,
        index=True,
    )

    billable_unit_id = Column(
        Integer,
        ForeignKey("billable_units.id"),
        nullable=False,
        index=True,
    )

    quantity_on_hand = Column(
        Integer,
        nullable=False,
        default=0,
    )

    reorder_level = Column(
        Integer,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -------------------------
    # Relationships
    # -------------------------

    billable_unit = relationship(
        "BillableUnit",
        lazy="joined",
    )

    movements = relationship(
        "InventoryMovement",
        back_populates="inventory_item",
        lazy="select",
        cascade="all, delete-orphan",
    )

    # -------------------------
    # Indexes / Constraints
    # -------------------------

    __table_args__ = (
        Index(
            "uq_inventory_item_branch_unit",
            "branch_id",
            "billable_unit_id",
            unique=True,
        ),
        Index(
            "ix_inventory_item_tenant_branch",
            "tenant_id",
            "branch_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<InventoryItem id={self.id} "
            f"billable_unit_id={self.billable_unit_id} "
            f"branch_id={self.branch_id} "
            f"qty={self.quantity_on_hand}>"
        )


# -------------------------------------------------
# InventoryMovement (ledger)
# -------------------------------------------------

class InventoryMovement(Base):
    """
    Authoritative ledger entry for inventory changes.

    Rules:
    - Inventory is NEVER updated without a movement
    - Sale movements are created ONLY after payment success
    - quantity_delta can be positive or negative
    - movement_type and source are validated in service layer
    """

    __tablename__ = "inventory_movements"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(
        Integer,
        nullable=False,
        index=True,
    )

    branch_id = Column(
        Integer,
        nullable=False,
        index=True,
    )

    inventory_item_id = Column(
        Integer,
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    billable_unit_id = Column(
        Integer,
        ForeignKey("billable_units.id"),
        nullable=False,
        index=True,
    )

    quantity_delta = Column(
        Integer,
        nullable=False,
    )

    # Stored as STRING; validated by service layer
    movement_type = Column(
        String,
        nullable=False,
        index=True,
    )

    source = Column(
        String,
        nullable=False,
        default="system",
    )

    # Reference to originating entity (e.g. sale_id)
    reference_type = Column(
        String,
        nullable=True,
    )

    reference_id = Column(
        Integer,
        nullable=True,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -------------------------
    # Relationships
    # -------------------------

    inventory_item = relationship(
        "InventoryItem",
        back_populates="movements",
    )

    billable_unit = relationship(
        "BillableUnit",
        lazy="joined",
    )

    # -------------------------
    # Indexes
    # -------------------------

    __table_args__ = (
        Index(
            "ix_inventory_movement_branch_unit_time",
            "branch_id",
            "billable_unit_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<InventoryMovement id={self.id} "
            f"type={self.movement_type} "
            f"delta={self.quantity_delta} "
            f"billable_unit_id={self.billable_unit_id}>"
        )


# -------------------------------------------------
# Explicit exports (CRITICAL for Alembic)
# -------------------------------------------------

__all__ = [
    "InventoryItem",
    "InventoryMovement",
]
