# core/users/user_controller.py

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from core.errors.api_error import APIError
from core.rbac.utils.permission_decorator import require_permissions
from core.users.schemas import (
    UserCreate,
    UserUpdate,
    PasswordResetPayload,
)
from core.users.user_service import UserService


router = APIRouter(tags=["Users"])
service = UserService()


def current_user_from_request(request: Request) -> dict:
    ctx = getattr(request.state, "user", None)

    if not ctx or not isinstance(ctx, dict):
        raise APIError("AUTH_CONTEXT_MISSING")

    if not ctx.get("user_id") or not ctx.get("tenant_id") or not ctx.get("branch_id"):
        raise APIError("AUTH_CONTEXT_INCOMPLETE")

    return ctx


@router.get("/")
@require_permissions("user.view")
async def list_users(
    request: Request,
    db: Session = Depends(get_db),
    branch_id: int | None = None,
):
    """
    List users for the current tenant.

    Optional query param:
      ?branch_id=1

    If branch_id is omitted, returns all users in the current tenant.
    """
    ctx = current_user_from_request(request)

    return service.list_users(
        db,
        tenant_id=int(ctx["tenant_id"]),
        branch_id=branch_id,
    )


@router.post("/")
@require_permissions("user.create")
async def create_user(
    request: Request,
    payload: UserCreate,
    db: Session = Depends(get_db),
):
    """
    Create a user under the current tenant.

    If branch_id is omitted, defaults to current user's branch.
    """
    ctx = current_user_from_request(request)

    return service.create_user(
        db,
        current_user=ctx,
        payload=payload,
    )


@router.patch("/{user_id}")
@require_permissions("user.edit")
async def update_user(
    user_id: int,
    request: Request,
    payload: UserUpdate,
    db: Session = Depends(get_db),
):
    """
    Update profile, role, branch, username, or active state.
    """
    ctx = current_user_from_request(request)

    return service.update_user(
        db,
        current_user=ctx,
        user_id=user_id,
        payload=payload,
    )


@router.patch("/{user_id}/activate")
@require_permissions("user.edit")
async def activate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Reactivate a disabled user.
    """
    ctx = current_user_from_request(request)

    return service.set_active(
        db,
        current_user=ctx,
        user_id=user_id,
        is_active=True,
    )


@router.patch("/{user_id}/deactivate")
@require_permissions("user.disable")
async def deactivate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Disable a user without deleting audit history.
    """
    ctx = current_user_from_request(request)

    return service.set_active(
        db,
        current_user=ctx,
        user_id=user_id,
        is_active=False,
    )


@router.post("/{user_id}/reset-password")
@require_permissions("user.reset_password")
async def reset_user_password(
    user_id: int,
    request: Request,
    payload: PasswordResetPayload,
    db: Session = Depends(get_db),
):
    """
    Reset a user's password.
    """
    ctx = current_user_from_request(request)

    return service.reset_password(
        db,
        current_user=ctx,
        user_id=user_id,
        new_password=payload.password,
    )