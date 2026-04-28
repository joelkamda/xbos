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

from database import Base


# -------------------------------------------------
# InventoryItem (cached state)
# -------------------------------------------------

class InventoryItem(Base):
    """
    Cached inventory state for an AtomicUnit at a specific branch.

    IMPORTANT RULES
    ----------------
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

    atomic_unit_id = Column(
        Integer,
        ForeignKey("atomic_units.id"),
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

    atomic_unit = relationship(
        "AtomicUnit",
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

        # one inventory record per unit per branch
        Index(
            "uq_inventory_item_branch_unit",
            "branch_id",
            "atomic_unit_id",
            unique=True,
        ),

        # tenant + branch lookup
        Index(
            "ix_inventory_item_tenant_branch",
            "tenant_id",
            "branch_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<InventoryItem id={self.id} "
            f"atomic_unit_id={self.atomic_unit_id} "
            f"branch_id={self.branch_id} "
            f"qty={self.quantity_on_hand}>"
        )


# -------------------------------------------------
# InventoryMovement (ledger)
# -------------------------------------------------

class InventoryMovement(Base):
    """
    Authoritative ledger entry for inventory changes.

    RULES
    ------
    - Inventory is NEVER updated without a movement
    - Sale movements are created ONLY after payment success
    - quantity_delta can be positive or negative
    - movement_type validated in service layer
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

    atomic_unit_id = Column(
        Integer,
        ForeignKey("atomic_units.id"),
        nullable=False,
        index=True,
    )

    quantity_delta = Column(
        Integer,
        nullable=False,
    )

    # validated by service layer
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

    # reference to originating entity
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

    atomic_unit = relationship(
        "AtomicUnit",
        lazy="joined",
    )

    # -------------------------
    # Indexes
    # -------------------------

    __table_args__ = (
        Index(
            "ix_inventory_movement_branch_unit_time",
            "branch_id",
            "atomic_unit_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<InventoryMovement id={self.id} "
            f"type={self.movement_type} "
            f"delta={self.quantity_delta} "
            f"atomic_unit_id={self.atomic_unit_id}>"
        )


# -------------------------------------------------
# Explicit exports (important for Alembic)
# -------------------------------------------------

__all__ = [
    "InventoryItem",
    "InventoryMovement",
]