from typing import List, Optional

from sqlalchemy.orm import Session, aliased
from sqlalchemy import select, or_, and_

from core.domain.catalog.models import BillableUnit
from core.domain.taxonomy.models import (
    BillableUnitTaxonomy,
    TaxonomyNode,
)


class BillableUnitRepository:
    """
    Data-access layer for BillableUnit.

    Responsibilities:
    - Fetch billable units
    - Enforce tenant isolation
    - Apply simple filters (active, taxonomy, search)
    - NO business logic
    """

    # -------------------------
    # Basic fetches
    # -------------------------

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        billable_unit_id: int,
    ) -> Optional[BillableUnit]:
        stmt = (
            select(BillableUnit)
            .where(BillableUnit.id == billable_unit_id)
            .where(BillableUnit.tenant_id == tenant_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_all(
        db: Session,
        *,
        tenant_id: int,
        active_only: bool = True,
    ) -> List[BillableUnit]:
        stmt = select(BillableUnit).where(
            BillableUnit.tenant_id == tenant_id
        )

        if active_only:
            stmt = stmt.where(BillableUnit.is_active.is_(True))

        stmt = stmt.order_by(BillableUnit.name.asc())

        return list(db.execute(stmt).scalars().all())

    # -------------------------
    # Taxonomy filtering
    # -------------------------

    @staticmethod
    def list_by_taxonomy(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_node_id: int,
        active_only: bool = True,
    ) -> List[BillableUnit]:
        stmt = (
            select(BillableUnit)
            .join(
                BillableUnitTaxonomy,
                BillableUnitTaxonomy.billable_unit_id == BillableUnit.id,
            )
            .join(
                TaxonomyNode,
                TaxonomyNode.id == BillableUnitTaxonomy.taxonomy_node_id,
            )
            .where(BillableUnit.tenant_id == tenant_id)
            .where(TaxonomyNode.id == taxonomy_node_id)
            .where(TaxonomyNode.tenant_id == tenant_id)
        )

        if active_only:
            stmt = stmt.where(BillableUnit.is_active.is_(True))

        stmt = stmt.order_by(BillableUnit.name.asc())

        return list(db.execute(stmt).scalars().all())

    # -------------------------
    # 🔥 CATALOG SUMMARY (FIX)
    # -------------------------

    @staticmethod
    def catalog_summary(
        db: Session,
        *,
        tenant_id: int,
    ):
        """
        Returns category → subcategory pairs for POS navigation.
        Explicit self-join to avoid SQLAlchemy ambiguity.
        """

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
                ),
                isouter=True,
            )
            .where(
                Category.tenant_id == tenant_id,
                Category.semantic_level == "category",
                Category.is_active.is_(True),
            )
            .order_by(Category.sort_order, Subcategory.sort_order)
        )

        return db.execute(stmt).all()

    # -------------------------
    # Search
    # -------------------------

    @staticmethod
    def search(
        db: Session,
        *,
        tenant_id: int,
        query: str,
        active_only: bool = True,
        limit: int = 50,
    ) -> List[BillableUnit]:
        q = f"%{query}%"

        stmt = (
            select(BillableUnit)
            .where(BillableUnit.tenant_id == tenant_id)
            .where(
                or_(
                    BillableUnit.name.ilike(q),
                    BillableUnit.sku.ilike(q),
                )
            )
        )

        if active_only:
            stmt = stmt.where(BillableUnit.is_active.is_(True))

        stmt = stmt.order_by(BillableUnit.name.asc()).limit(limit)

        return list(db.execute(stmt).scalars().all())
