from typing import List, Optional

from sqlalchemy.orm import Session, aliased
from sqlalchemy import select, and_

from core.domain.taxonomy.models import (
    TaxonomyNode,
    BillableUnitTaxonomy,
)


class TaxonomyRepository:
    """
    Data-access layer for taxonomy.

    Responsibilities:
    - Fetch taxonomy nodes
    - Traverse taxonomy trees
    - Resolve billable-unit mappings
    - Enforce tenant isolation
    - NO business logic
    """

    # -------------------------------------------------
    # TaxonomyNode
    # -------------------------------------------------

    @staticmethod
    def get_by_id(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_node_id: int,
    ) -> Optional[TaxonomyNode]:
        stmt = (
            select(TaxonomyNode)
            .where(TaxonomyNode.id == taxonomy_node_id)
            .where(TaxonomyNode.tenant_id == tenant_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def list_roots(
        db: Session,
        *,
        tenant_id: int,
        active_only: bool = True,
    ) -> List[TaxonomyNode]:
        stmt = (
            select(TaxonomyNode)
            .where(TaxonomyNode.tenant_id == tenant_id)
            .where(TaxonomyNode.parent_id.is_(None))
        )

        if active_only:
            stmt = stmt.where(TaxonomyNode.is_active.is_(True))

        stmt = stmt.order_by(TaxonomyNode.sort_order.asc())

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_children(
        db: Session,
        *,
        tenant_id: int,
        parent_id: int,
        active_only: bool = True,
    ) -> List[TaxonomyNode]:
        stmt = (
            select(TaxonomyNode)
            .where(TaxonomyNode.tenant_id == tenant_id)
            .where(TaxonomyNode.parent_id == parent_id)
        )

        if active_only:
            stmt = stmt.where(TaxonomyNode.is_active.is_(True))

        stmt = stmt.order_by(TaxonomyNode.sort_order.asc())

        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_all(
        db: Session,
        *,
        tenant_id: int,
        active_only: bool = True,
    ) -> List[TaxonomyNode]:
        stmt = select(TaxonomyNode).where(
            TaxonomyNode.tenant_id == tenant_id
        )

        if active_only:
            stmt = stmt.where(TaxonomyNode.is_active.is_(True))

        stmt = stmt.order_by(
            TaxonomyNode.parent_id.asc(),
            TaxonomyNode.sort_order.asc(),
        )

        return list(db.execute(stmt).scalars().all())

    # -------------------------------------------------
    # 🔥 Catalog summary (Category → Subcategory)
    # -------------------------------------------------

    @staticmethod
    def catalog_summary(
        db: Session,
        *,
        tenant_id: int,
    ):
        """
        Returns flattened category → subcategory rows for POS navigation.
        Uses explicit self-join with aliases to avoid SQLAlchemy ambiguity.
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
            .order_by(
                Category.sort_order.asc(),
                Subcategory.sort_order.asc(),
            )
        )

        return db.execute(stmt).all()

    # -------------------------------------------------
    # BillableUnit ↔ Taxonomy mapping
    # -------------------------------------------------

    @staticmethod
    def list_mappings_for_node(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_node_id: int,
    ) -> List[BillableUnitTaxonomy]:
        stmt = (
            select(BillableUnitTaxonomy)
            .join(
                TaxonomyNode,
                TaxonomyNode.id == BillableUnitTaxonomy.taxonomy_node_id,
            )
            .where(BillableUnitTaxonomy.taxonomy_node_id == taxonomy_node_id)
            .where(TaxonomyNode.tenant_id == tenant_id)
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def list_mappings_for_unit(
        db: Session,
        *,
        tenant_id: int,
        billable_unit_id: int,
    ) -> List[BillableUnitTaxonomy]:
        stmt = (
            select(BillableUnitTaxonomy)
            .join(
                TaxonomyNode,
                TaxonomyNode.id == BillableUnitTaxonomy.taxonomy_node_id,
            )
            .where(BillableUnitTaxonomy.billable_unit_id == billable_unit_id)
            .where(TaxonomyNode.tenant_id == tenant_id)
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def create_mapping(
        db: Session,
        *,
        mapping: BillableUnitTaxonomy,
    ) -> BillableUnitTaxonomy:
        db.add(mapping)
        return mapping

    @staticmethod
    def delete_mapping(
        db: Session,
        *,
        tenant_id: int,
        billable_unit_id: int,
        taxonomy_node_id: int,
    ) -> None:
        stmt = (
            select(BillableUnitTaxonomy)
            .join(
                TaxonomyNode,
                TaxonomyNode.id == BillableUnitTaxonomy.taxonomy_node_id,
            )
            .where(BillableUnitTaxonomy.billable_unit_id == billable_unit_id)
            .where(BillableUnitTaxonomy.taxonomy_node_id == taxonomy_node_id)
            .where(TaxonomyNode.tenant_id == tenant_id)
        )

        mapping = db.execute(stmt).scalar_one_or_none()
        if mapping:
            db.delete(mapping)
