# core/rbac/roles/role_controller.py

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from core.errors.api_error import APIError
from core.rbac.roles.role_repository import RoleRepository
from core.rbac.utils.permission_decorator import require_permissions


router = APIRouter(tags=["Roles"])


def serialize_role(role):
    permissions = role.permissions or []

    if not isinstance(permissions, list):
        permissions = []

    permissions = sorted(set(str(p).strip() for p in permissions if p))

    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "permissions": permissions,
        "permission_count": len(permissions),
    }


@router.get("/")
@require_permissions("rbac.role.view")
async def list_roles(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    List all system roles.

    V1 is read-only:
    - Admin UI can use this for role dropdowns.
    - Role editing comes later after custom-role strategy is finalized.
    """

    roles = RoleRepository.list_all(db)

    items = [serialize_role(role) for role in roles]

    return {
        "items": items,
        "count": len(items),
    }


@router.get("/{role_id}")
@require_permissions("rbac.role.view")
async def get_role(
    role_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get one role with its permissions.
    """

    role = RoleRepository.find_by_id(db, role_id)

    if not role:
        raise APIError("ROLE_NOT_FOUND")

    return serialize_role(role)