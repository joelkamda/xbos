from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


class TaxonomyNode(Base):
    """
    Flexible taxonomy node for organizing billable units.

    - Arbitrary depth via parent_id
    - Semantics are hints only
    - Frontend controls rendering
    """

    __tablename__ = "taxonomy_nodes"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    parent_id = Column(
        Integer,
        ForeignKey("taxonomy_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name = Column(String, nullable=False)

    # semantic hint only — never authoritative
    semantic_level = Column(String, nullable=True)

    sort_order = Column(Integer, default=0, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)

    # -------------------------
    # Relationships
    # -------------------------

    parent = relationship(
        "TaxonomyNode",
        remote_side=[id],
        backref="children",
        lazy="selectin",
    )

    billable_units = relationship(
        "BillableUnitTaxonomy",
        back_populates="taxonomy_node",
        cascade="all, delete-orphan",
    )

    # -------------------------
    # Constraints / Indexes
    # -------------------------

    __table_args__ = (
        Index("ix_taxonomy_tenant_parent", "tenant_id", "parent_id"),
        UniqueConstraint(
            "tenant_id",
            "parent_id",
            "name",
            name="uq_taxonomy_node_name_per_parent",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TaxonomyNode id={self.id} "
            f"name={self.name} "
            f"tenant_id={self.tenant_id} "
            f"parent_id={self.parent_id}>"
        )


class BillableUnitTaxonomy(Base):
    """
    Many-to-many mapping between BillableUnits and TaxonomyNodes.

    Taxonomy is navigational, not accounting.
    """

    __tablename__ = "billable_unit_taxonomy"

    billable_unit_id = Column(
        Integer,
        ForeignKey("billable_units.id", ondelete="CASCADE"),
        primary_key=True,
    )

    taxonomy_node_id = Column(
        Integer,
        ForeignKey("taxonomy_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )

    billable_unit = relationship(
        "BillableUnit",
        back_populates="taxonomy_links",
    )

    taxonomy_node = relationship(
        "TaxonomyNode",
        back_populates="billable_units",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<BillableUnitTaxonomy "
            f"billable_unit_id={self.billable_unit_id} "
            f"taxonomy_node_id={self.taxonomy_node_id}>"
        )
