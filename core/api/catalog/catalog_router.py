from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.orm import Session

from core.api.catalog.catalog_controller import CatalogController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Catalog"])
controller = CatalogController()

# -------------------------------------------------
# Catalog summary (categories + subcategories)
# -------------------------------------------------

@router.get("/summary")
@require_permissions("catalog.view")
async def catalog_summary(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.catalog_summary(
        request=request,
        db=db,
    )


# -------------------------------------------------
# List billable units by subcategory (POS use)
# -------------------------------------------------

@router.get("/billable-units")
@require_permissions("catalog.view")
async def list_billable_units_by_subcategory(
    request: Request,
    subcategory_id: int = Query(...),
    db: Session = Depends(get_db),
):
    return await controller.list_by_subcategory(
        request=request,
        subcategory_id=subcategory_id,
        db=db,
    )


# -------------------------------------------------
# List all billable units (admin / backoffice)
# -------------------------------------------------

@router.get("/")
@require_permissions("catalog.view")
async def list_catalog(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.list_billable_units(
        request=request,
        db=db,
    )


# -------------------------------------------------
# List by taxonomy node (generic)
# -------------------------------------------------

@router.get("/taxonomy/{taxonomy_node_id}")
@require_permissions("catalog.view")
async def list_by_taxonomy(
    request: Request,
    taxonomy_node_id: int,
    db: Session = Depends(get_db),
):
    return await controller.list_by_taxonomy(
        request=request,
        taxonomy_node_id=taxonomy_node_id,
        db=db,
    )


# -------------------------------------------------
# Search catalog
# -------------------------------------------------

@router.get("/search")
@require_permissions("catalog.view")
async def search_catalog(
    request: Request,
    q: str,
    db: Session = Depends(get_db),
):
    return await controller.search(
        request=request,
        q=q,
        db=db,
    )
