from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    Numeric,
    ForeignKey,
    Index,
    UniqueConstraint,
    JSON,
)

from sqlalchemy.orm import relationship

from database import Base


class TaxonomyNode(Base):
    """
    Flexible taxonomy node for organizing system entities.

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

    # 🔥 ADD THIS (missing in ORM but exists in DB)
    taxonomy_type = Column(String, nullable=True)

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

    atomic_units = relationship(
        "AtomicUnitTaxonomy",
        back_populates="taxonomy_node",
        cascade="all, delete-orphan",
        lazy="selectin",
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

    def __repr__(self):
        return (
            f"<TaxonomyNode id={self.id} "
            f"name={self.name} "
            f"tenant_id={self.tenant_id} "
            f"parent_id={self.parent_id}>"
        )


class AtomicUnit(Base):
    """
    Canonical operational entity in XBOS.

    Represents the smallest operational unit that can participate
    in system activity such as:

    - Sale line item
    - Inventory item
    - Medical service
    - Expense entry
    - Adjustment
    - Fee or discount

    Atomic units are domain-neutral and linked to taxonomy
    for classification.
    """

    __tablename__ = "atomic_units"

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

    # Optional base price
    unit_price = Column(
        Numeric(12, 2),
        nullable=True,
    )

    # Semantic hint only
    # Examples: product, service, expense, adjustment
    unit_type = Column(String, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    # Flexible extension point for domain-specific attributes
    meta = Column(JSON, nullable=True)

    # -------------------------
    # Relationships
    # -------------------------

    taxonomy_links = relationship(
        "AtomicUnitTaxonomy",
        back_populates="atomic_unit",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # -------------------------
    # Indexes / Constraints
    # -------------------------

    __table_args__ = (
        Index(
            "ix_atomic_unit_tenant_active",
            "tenant_id",
            "is_active",
        ),
        UniqueConstraint(
            "tenant_id",
            "sku",
            name="uq_atomic_unit_sku_per_tenant",
        ),
    )

    def __repr__(self):
        return (
            f"<AtomicUnit id={self.id} "
            f"name={self.name} "
            f"unit_price={self.unit_price} "
            f"tenant_id={self.tenant_id}>"
        )


class AtomicUnitTaxonomy(Base):
    """
    Many-to-many mapping between AtomicUnits and TaxonomyNodes.

    Taxonomy is navigational, not accounting.
    """

    __tablename__ = "atomic_unit_taxonomy"

    atomic_unit_id = Column(
        Integer,
        ForeignKey("atomic_units.id", ondelete="CASCADE"),
        primary_key=True,
    )

    taxonomy_node_id = Column(
        Integer,
        ForeignKey("taxonomy_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # -------------------------
    # Relationships
    # -------------------------

    atomic_unit = relationship(
        "AtomicUnit",
        back_populates="taxonomy_links",
    )

    taxonomy_node = relationship(
        "TaxonomyNode",
        back_populates="atomic_units",
        lazy="selectin",
    )

    # -------------------------
    # Indexes
    # -------------------------

    __table_args__ = (
        Index(
            "ix_atomic_unit_taxonomy_unit",
            "atomic_unit_id",
        ),
        Index(
            "ix_atomic_unit_taxonomy_node",
            "taxonomy_node_id",
        ),
    )

    def __repr__(self):
        return (
            f"<AtomicUnitTaxonomy "
            f"atomic_unit_id={self.atomic_unit_id} "
            f"taxonomy_node_id={self.taxonomy_node_id}>"
        )