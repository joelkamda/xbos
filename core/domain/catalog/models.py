from sqlalchemy import (
    Column,
    String,
    Boolean,
    Numeric,
    Integer,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class BillableUnit(Base):
    """
    Canonical sellable entity in XBOS.

    Represents ANYTHING that can appear in a sale:
    - Physical products
    - Menu items
    - Medications
    - Services

    No product/service distinction at DB level.
    """

    __tablename__ = "billable_units"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String, nullable=False)

    # Optional human / machine identifier
    sku = Column(String, nullable=True)

    # Tenant-wide base price
    price = Column(
        Numeric(12, 2),
        nullable=False,
    )

    # Semantic hint only (never authoritative)
    unit_type = Column(String, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    # -------------------------
    # Relationships
    # -------------------------

    taxonomy_links = relationship(
        "BillableUnitTaxonomy",
        back_populates="billable_unit",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # -------------------------
    # Indexes / Constraints
    # -------------------------

    __table_args__ = (
        Index(
            "ix_billable_unit_tenant_active",
            "tenant_id",
            "is_active",
        ),
        UniqueConstraint(
            "tenant_id",
            "sku",
            name="uq_billable_unit_sku_per_tenant",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BillableUnit id={self.id} "
            f"name={self.name} "
            f"price={self.price} "
            f"tenant_id={self.tenant_id}>"
        )
