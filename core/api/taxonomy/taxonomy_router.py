from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from core.api.taxonomy.taxonomy_controller import TaxonomyController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Taxonomy"])
controller = TaxonomyController()


# -------------------------------------------------
# List root taxonomy nodes
# -------------------------------------------------

@router.get("/")
@require_permissions("taxonomy.view")
async def list_taxonomy_roots(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.list_roots(
        request=request,
        db=db,
    )


# -------------------------------------------------
# List children of a taxonomy node
# -------------------------------------------------

@router.get("/{parent_id}/children")
@require_permissions("taxonomy.view")
async def list_taxonomy_children(
    request: Request,
    parent_id: str,
    db: Session = Depends(get_db),
):
    return await controller.list_children(
        request=request,
        parent_id=parent_id,
        db=db,
    )


# -------------------------------------------------
# List full taxonomy (flat)
# -------------------------------------------------

@router.get("/all")
@require_permissions("taxonomy.view")
async def list_all_taxonomy(
    request: Request,
    db: Session = Depends(get_db),
):
    return await controller.list_all(
        request=request,
        db=db,
    )
