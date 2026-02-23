from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.taxonomy.service import TaxonomyService
from core.errors.api_error import APIError


class TaxonomyController:
    """
    HTTP controller for Taxonomy.

    Responsibilities:
    - Extract tenant context
    - Delegate to TaxonomyService
    - Return navigation-friendly structures
    - NO business logic
    """

    def __init__(self):
        pass

    # -------------------------------------------------
    # List root taxonomy nodes
    # -------------------------------------------------

    async def list_roots(
        self,
        request: Request,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        try:
            nodes = TaxonomyService.list_root_nodes(
                db,
                tenant_id=tenant_id,
                active_only=True,
            )

            return [
                {
                    "id": n.id,
                    "name": n.name,
                    "parent_id": n.parent_id,
                    "level": n.level,
                    "sort_order": n.sort_order,
                }
                for n in nodes
            ]

        except Exception as e:
            raise ApiError(
                message="Failed to list taxonomy roots",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # List children of a taxonomy node
    # -------------------------------------------------

    async def list_children(
        self,
        request: Request,
        parent_id: str,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        try:
            nodes = TaxonomyService.list_children(
                db,
                tenant_id=tenant_id,
                parent_id=parent_id,
                active_only=True,
            )

            return [
                {
                    "id": n.id,
                    "name": n.name,
                    "parent_id": n.parent_id,
                    "level": n.level,
                    "sort_order": n.sort_order,
                }
                for n in nodes
            ]

        except Exception as e:
            raise ApiError(
                message="Failed to list taxonomy children",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    # -------------------------------------------------
    # List full taxonomy tree (flat)
    # -------------------------------------------------

    async def list_all(
        self,
        request: Request,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        try:
            nodes = TaxonomyService.list_all_nodes(
                db,
                tenant_id=tenant_id,
                active_only=True,
            )

            return [
                {
                    "id": n.id,
                    "name": n.name,
                    "parent_id": n.parent_id,
                    "level": n.level,
                    "sort_order": n.sort_order,
                }
                for n in nodes
            ]

        except Exception as e:
            raise ApiError(
                message="Failed to list taxonomy nodes",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e
