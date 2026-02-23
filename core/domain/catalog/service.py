from typing import List, Optional
from sqlalchemy.orm import Session

from core.domain.catalog.models import BillableUnit
from core.domain.catalog.repository import BillableUnitRepository
from core.domain.taxonomy.repository import TaxonomyRepository


class CatalogService:
    """
    Domain service for catalog access.

    Responsibilities:
    - Fetch billable units for POS
    - Apply tenant scoping
    - Orchestrate taxonomy-based filtering
    - NO pricing logic
    - NO inventory logic
    """

    # -------------------------------------------------
    # Basic fetches
    # -------------------------------------------------

    @staticmethod
    def get_billable_unit(
        db: Session,
        *,
        tenant_id: int,
        billable_unit_id: int,
    ) -> Optional[BillableUnit]:
        return BillableUnitRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            billable_unit_id=billable_unit_id,
        )

    @staticmethod
    def list_all(
        db: Session,
        *,
        tenant_id: int,
        active_only: bool = True,
    ) -> List[BillableUnit]:
        return BillableUnitRepository.list_all(
            db,
            tenant_id=tenant_id,
            active_only=active_only,
        )

    # -------------------------------------------------
    # ✅ Catalog summary (DELEGATED – FIXED)
    # -------------------------------------------------

    @staticmethod
    def catalog_summary(
        db: Session,
        *,
        tenant_id: int,
    ):
        """
        Returns flattened rows:
        category_id, category_name, subcategory_id, subcategory_name

        Delegated to TaxonomyRepository to avoid self-join ambiguity.
        """
        return TaxonomyRepository.catalog_summary(
            db,
            tenant_id=tenant_id,
        )

    # -------------------------------------------------
    # List by subcategory (POS-optimized)
    # -------------------------------------------------

    @staticmethod
    def list_by_subcategory(
        db: Session,
        *,
        tenant_id: int,
        subcategory_id: int,
        active_only: bool = True,
    ) -> List[BillableUnit]:
        return BillableUnitRepository.list_by_taxonomy(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=subcategory_id,
            active_only=active_only,
        )

    # -------------------------------------------------
    # Taxonomy-based access (generic)
    # -------------------------------------------------

    @staticmethod
    def list_by_taxonomy(
        db: Session,
        *,
        tenant_id: int,
        taxonomy_node_id: int,
        active_only: bool = True,
    ) -> List[BillableUnit]:
        node = TaxonomyRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=taxonomy_node_id,
        )
        if not node:
            return []

        return BillableUnitRepository.list_by_taxonomy(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=taxonomy_node_id,
            active_only=active_only,
        )

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
    ) -> List[BillableUnit]:
        if not query or not query.strip():
            return []

        return BillableUnitRepository.search(
            db,
            tenant_id=tenant_id,
            query=query,
            active_only=active_only,
            limit=limit,
        )
