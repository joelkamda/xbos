from typing import List, Optional

from sqlalchemy.orm import Session, aliased
from sqlalchemy import select, or_, and_

from core.domain.taxonomy.models import (
    AtomicUnitTaxonomy,
    TaxonomyNode,
    AtomicUnit,
)


class AtomicUnitRepository:
    """
    Data-access layer for AtomicUnit.

    Responsibilities:
    - Fetch atomic units
    - Enforce tenant isolation
    - Apply simple filters (active, taxonomy, search)
    - NO business logic
    """

    # -------------------------------------------------
    # Basic fetches
    # -------------------------------------------------

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: int,
    ) -> Optional[AtomicUnit]:

        stmt = (
            select(AtomicUnit)
            .where(
                AtomicUnit.id == atomic_unit_id,
                AtomicUnit.tenant_id == tenant_id,
            )
        )

        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_all(
        db: Session,
        *,
        tenant_id: int,
        active_only: bool = True,
    ) -> List[AtomicUnit]:

        stmt = select(AtomicUnit).where(
            AtomicUnit.tenant_id == tenant_id
        )

        if active_only:
            stmt = stmt.where(AtomicUnit.is_active.is_(True))

        stmt = stmt.order_by(AtomicUnit.name.asc())

        return list(db.execute(stmt).scalars().all())

    # -------------------------------------------------
    # Taxonomy filtering
    # -------------------------------------------------

    @staticmethod
    def list_by_taxonomy(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_node_id: int,
        active_only: bool = True,
    ) -> List[AtomicUnit]:
        """
        Returns atomic units mapped to a specific taxonomy node.
        """

        stmt = (
            select(AtomicUnit)
            .join(
                AtomicUnitTaxonomy,
                AtomicUnitTaxonomy.atomic_unit_id == AtomicUnit.id,
            )
            .where(
                AtomicUnit.tenant_id == tenant_id,
                AtomicUnitTaxonomy.taxonomy_node_id == taxonomy_node_id,
            )
        )

        if active_only:
            stmt = stmt.where(AtomicUnit.is_active.is_(True))

        stmt = stmt.order_by(AtomicUnit.name.asc())

        return list(db.execute(stmt).scalars().all())

    # -------------------------------------------------
    # POS Catalog Navigation
    # -------------------------------------------------

    @staticmethod
    def catalog_summary(
        db: Session,
        *,
        tenant_id: int,
    ):
        """
        Returns category → subcategory pairs used by the POS UI.

        Only categories under the COMMERCE → Inventory domain
        are returned. This prevents FINANCE or other taxonomy
        domains from leaking into the POS menu.
        """

        # ---------------------------------
        # Resolve Inventory domain safely
        # ---------------------------------

        inventory_domain_id = db.execute(
            select(TaxonomyNode.id).where(
                TaxonomyNode.tenant_id == tenant_id,
                TaxonomyNode.taxonomy_type == "COMMERCE",
                TaxonomyNode.semantic_level == "domain",
                TaxonomyNode.name == "Inventory",
                TaxonomyNode.is_active.is_(True),
            )
        ).scalar_one_or_none()

        # If Inventory domain not found → return empty
        if not inventory_domain_id:
            return []

        Category = aliased(TaxonomyNode)
        Subcategory = aliased(TaxonomyNode)

        stmt = (
            select(
                Category.id.label("category_id"),
                Category.name.label("category_name"),
                Subcategory.id.label("subcategory_id"),
                Subcategory.name.label("subcategory_name"),
            )
            .select_from(Category)
            .join(
                Subcategory,
                and_(
                    Subcategory.parent_id == Category.id,
                    Subcategory.semantic_level == "subcategory",
                    Subcategory.tenant_id == tenant_id,
                    Subcategory.is_active.is_(True),
                ),
                isouter=True,
            )
            .where(
                Category.tenant_id == tenant_id,
                Category.parent_id == inventory_domain_id,
                Category.semantic_level == "category",
                Category.is_active.is_(True),
            )
            .order_by(
                Category.sort_order.asc(),
                Subcategory.sort_order.asc(),
            )
        )

        return db.execute(stmt).all()

    # -------------------------------------------------
    # Search
    # -------------------------------------------------

    @staticmethod
    def search(
        db: Session,
        *,
        tenant_id: int,
        query: str,
        active_only: bool = True,
        limit: int = 50,
    ) -> List[AtomicUnit]:

        q = f"%{query}%"

        stmt = (
            select(AtomicUnit)
            .where(
                AtomicUnit.tenant_id == tenant_id,
                or_(
                    AtomicUnit.name.ilike(q),
                    AtomicUnit.sku.ilike(q),
                ),
            )
        )

        if active_only:
            stmt = stmt.where(AtomicUnit.is_active.is_(True))

        stmt = stmt.order_by(AtomicUnit.name.asc()).limit(limit)

        return list(db.execute(stmt).scalars().all())