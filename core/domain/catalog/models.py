from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    Index,
    DateTime,
)

from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base


class InventoryItem(Base):
    """
    Cached inventory state for an AtomicUnit at a specific branch.

    IMPORTANT:
    - quantity_on_hand is a CACHE
    - InventoryMovements are the source of truth
    """

    __tablename__ = "inventory_items"

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

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # -------------------------
    # Relationships
    # -------------------------

    atomic_unit = relationship(
        "AtomicUnit",
        lazy="joined",
    )

    # -------------------------
    # Indexes
    # -------------------------

    __table_args__ = (
        Index(
            "uq_inventory_item_branch_unit",
            "branch_id",
            "atomic_unit_id",
            unique=True,
        ),
    )

    def __repr__(self):
        return (
            f"<InventoryItem id={self.id} "
            f"atomic_unit_id={self.atomic_unit_id} "
            f"branch_id={self.branch_id} "
            f"qty={self.quantity_on_hand}>"
        )


class InventoryMovement(Base):
    """
    Ledger of all inventory movements.

    Source of truth for inventory quantities.
    """

    __tablename__ = "inventory_movements"

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

    inventory_item_id = Column(
        Integer,
        ForeignKey("inventory_items.id"),
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

    movement_type = Column(
        Integer,
        nullable=False,
    )

    reference_id = Column(
        Integer,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    atomic_unit = relationship(
        "AtomicUnit",
        lazy="joined",
    )

    __table_args__ = (
        Index(
            "ix_inventory_movement_branch_unit_time",
            "branch_id",
            "atomic_unit_id",
            "created_at",
        ),
    )

    def __repr__(self):
        return (
            f"<InventoryMovement id={self.id} "
            f"atomic_unit_id={self.atomic_unit_id} "
            f"delta={self.quantity_delta}>"
        )