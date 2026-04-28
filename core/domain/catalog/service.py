from typing import List, Optional
from sqlalchemy.orm import Session

from core.domain.taxonomy.models import AtomicUnit
from core.domain.catalog.repository import AtomicUnitRepository
from core.domain.taxonomy.repository import TaxonomyRepository


class CatalogService:
    """
    Domain service for catalog access.

    Responsibilities:
    - Fetch atomic units for POS
    - Apply tenant scoping
    - Orchestrate taxonomy-based filtering
    - NO pricing logic
    - NO inventory logic
    """

    # -------------------------------------------------
    # Basic fetches
    # -------------------------------------------------

    @staticmethod
    def get_atomic_unit(
        db: Session,
        *,
        tenant_id: int,
        atomic_unit_id: int,
    ) -> Optional[AtomicUnit]:
        """
        Fetch a single atomic unit by ID.
        """
        return AtomicUnitRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            atomic_unit_id=atomic_unit_id,
        )

    @staticmethod
    def list_all(
        db: Session,
        *,
        tenant_id: int,
        active_only: bool = True,
    ) -> List[AtomicUnit]:
        """
        List all atomic units for a tenant.
        """
        return AtomicUnitRepository.list_all(
            db,
            tenant_id=tenant_id,
            active_only=active_only,
        )

    # -------------------------------------------------
    # Catalog summary (POS navigation)
    # -------------------------------------------------

    @staticmethod
    def catalog_summary(
        db: Session,
        *,
        tenant_id: int,
    ):
        """
        Returns flattened POS navigation rows:

        category_id
        category_name
        subcategory_id
        subcategory_name

        Delegates to AtomicUnitRepository so POS
        remains isolated from full taxonomy traversal.
        """
        return AtomicUnitRepository.catalog_summary(
            db,
            tenant_id=tenant_id,
        )

    # -------------------------------------------------
    # List by subcategory (POS optimized)
    # -------------------------------------------------

    @staticmethod
    def list_by_subcategory(
        db: Session,
        *,
        tenant_id: int,
        subcategory_id: int,
        active_only: bool = True,
    ) -> List[AtomicUnit]:
        """
        Return atomic units belonging to a specific
        POS subcategory.
        """

        # Ensure subcategory exists
        node = TaxonomyRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=subcategory_id,
        )

        if not node:
            return []

        return AtomicUnitRepository.list_by_taxonomy(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=subcategory_id,
            active_only=active_only,
        )

    # -------------------------------------------------
    # Generic taxonomy access
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
        Return atomic units mapped to any taxonomy node.
        Used by advanced catalog tooling.
        """

        node = TaxonomyRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=taxonomy_node_id,
        )

        if not node:
            return []

        return AtomicUnitRepository.list_by_taxonomy(
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
    ) -> List[AtomicUnit]:
        """
        Search atomic units by name or SKU.
        """

        if not query or not query.strip():
            return []

        return AtomicUnitRepository.search(
            db,
            tenant_id=tenant_id,
            query=query,
            active_only=active_only,
            limit=limit,
        )