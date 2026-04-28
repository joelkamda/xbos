from typing import List, Optional

from sqlalchemy.orm import Session

from core.domain.taxonomy.models import (
    TaxonomyNode,
    AtomicUnitTaxonomy,
)
from core.domain.taxonomy.repository import TaxonomyRepository


class TaxonomyService:
    """
    Domain service for taxonomy.

    Responsibilities:
    - Orchestrate taxonomy reads/writes
    - Enforce tenant scoping
    - Apply basic integrity checks
    - NO business logic beyond taxonomy itself
    """

    # -------------------------------------------------
    # TaxonomyNode
    # -------------------------------------------------

    @staticmethod
    def get_node(
        db: Session,
        *,
        tenant_id: str,
        taxonomy_node_id: str,
    ) -> Optional[TaxonomyNode]:
        """
        Fetch a taxonomy node by ID.
        """
        return TaxonomyRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            taxonomy_node_id=taxonomy_node_id,
        )

    @staticmethod
    def list_root_nodes(
        db: Session,
        *,
        tenant_id: str,
        active_only: bool = True,
    ) -> List[TaxonomyNode]:
        """
        List top-level taxonomy nodes for a tenant.
        """
        return TaxonomyRepository.list_roots(
            db,
            tenant_id=tenant_id,
            active_only=active_only,
        )

    @staticmethod
    def list_children(
        db: Session,
        *,
        tenant_id: str,
        parent_id: str,
        active_only: bool = True,
    ) -> List[TaxonomyNode]:
        """
        List direct children of a taxonomy node.
        """
        return TaxonomyRepository.list_children(
            db,
            tenant_id=tenant_id,
            parent_id=parent_id,
            active_only=active_only,
        )

    @staticmethod
    def list_all_nodes(
        db: Session,
        *,
        tenant_id: str,
        active_only: bool = True,
    ) -> List[TaxonomyNode]:
        """
        List all taxonomy nodes for a tenant.
        """
        return TaxonomyRepository.list_all(
            db,
            tenant_id=tenant_id,
            active_only=active_only,
        )

    # -------------------------------------------------
    # AtomicUnit ↔ Taxonomy mapping
    # -------------------------------------------------

    @staticmethod
    def attach_atomic_unit(
        db: Session,
        *,
        atomic_unit_id: str,
        taxonomy_node_id: str,
    ) -> AtomicUnitTaxonomy:
        """
        Attach a AtomicUnit to a TaxonomyNode.

        NOTE:
        - Does not validate existence of AtomicUnit
        - Controller / higher service should validate if needed
        """
        mapping = AtomicUnitTaxonomy(
            atomic_unit_id=atomic_unit_id,
            taxonomy_node_id=taxonomy_node_id,
        )

        return TaxonomyRepository.create_mapping(
            db,
            mapping=mapping,
        )

    @staticmethod
    def detach_atomic_unit(
        db: Session,
        *,
        atomic_unit_id: str,
        taxonomy_node_id: str,
    ) -> None:
        """
        Detach a AtomicUnit from a TaxonomyNode.
        """
        TaxonomyRepository.delete_mapping(
            db,
            atomic_unit_id=atomic_unit_id,
            taxonomy_node_id=taxonomy_node_id,
        )
