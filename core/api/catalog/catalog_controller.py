from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.catalog.service import CatalogService
from core.errors.api_error import APIError


class CatalogController:
    """
    HTTP controller for Catalog (Billable Units).

    Responsibilities:
    - Extract tenant context
    - Delegate to CatalogService
    - Format responses
    - NO business logic
    """

    def __init__(self):
        pass

    # -------------------------------------------------
    # Catalog summary (categories + subcategories)
    # -------------------------------------------------

    async def catalog_summary(
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
            rows = CatalogService.catalog_summary(
                db,
                tenant_id=tenant_id,
            )

            categories = {}
            for r in rows:
                categories.setdefault(
                    r.category_id,
                    {
                        "id": r.category_id,
                        "name": r.category_name,
                        "subcategories": [],
                    },
                )["subcategories"].append(
                    {
                        "id": r.subcategory_id,
                        "name": r.subcategory_name,
                    }
                )

            return {
                "categories": list(categories.values())
            }

        except Exception as e:
            print("🔥 CATALOG SUMMARY RAW ERROR:", repr(e))
            raise APIError("CATALOG_SUMMARY_FAILED") from e

    # -------------------------------------------------
    # List by subcategory (POS-optimized)
    # -------------------------------------------------

    async def list_by_subcategory(
        self,
        request: Request,
        subcategory_id: int,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        try:
            units = CatalogService.list_by_subcategory(
                db,
                tenant_id=tenant_id,
                subcategory_id=subcategory_id,
                active_only=True,
            )

            return {
                "items": [
                    {
                        "id": u.id,
                        "name": u.name,
                        "price": float(u.price),
                        "sku": u.sku,
                        "unit_type": u.unit_type,
                    }
                    for u in units
                ]
            }

        except Exception as e:
            raise APIError("CATALOG_SUBCATEGORY_LIST_FAILED") from e

    # -------------------------------------------------
    # List all billable units (admin/backoffice)
    # -------------------------------------------------

    async def list_billable_units(
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
            units = CatalogService.list_all(
                db,
                tenant_id=tenant_id,
                active_only=True,
            )

            return [
                {
                    "id": u.id,
                    "name": u.name,
                    "price": float(u.price),
                    "sku": u.sku,
                    "unit_type": u.unit_type,
                }
                for u in units
            ]

        except Exception as e:
            raise APIError("CATALOG_LIST_FAILED") from e

    # -------------------------------------------------
    # List by taxonomy (generic)
    # -------------------------------------------------

    async def list_by_taxonomy(
        self,
        request: Request,
        taxonomy_node_id: str,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        try:
            units = CatalogService.list_by_taxonomy(
                db,
                tenant_id=tenant_id,
                taxonomy_node_id=taxonomy_node_id,
                active_only=True,
            )

            return [
                {
                    "id": u.id,
                    "name": u.name,
                    "price": float(u.price),
                    "sku": u.sku,
                    "unit_type": u.unit_type,
                }
                for u in units
            ]

        except Exception as e:
            raise APIError("CATALOG_TAXONOMY_LIST_FAILED") from e

    # -------------------------------------------------
    # Search
    # -------------------------------------------------

    async def search(
        self,
        request: Request,
        q: str,
        db: Session,
    ):
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing tenant context",
            )

        if not q:
            return []

        try:
            units = CatalogService.search(
                db,
                tenant_id=tenant_id,
                query=q,
                active_only=True,
            )

            return [
                {
                    "id": u.id,
                    "name": u.name,
                    "price": float(u.price),
                    "sku": u.sku,
                    "unit_type": u.unit_type,
                }
                for u in units
            ]

        except Exception as e:
            raise APIError("CATALOG_SEARCH_FAILED") from e
