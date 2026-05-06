# core/auth/auth_controller.py

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from core.auth.auth_service import AuthService
from core.auth.schemas import LoginSchema, TokenResponse, UserIdentity
from core.errors.api_error import APIError

auth_router = APIRouter(tags=["Auth"])
service = AuthService()


def _branch_code(branch):
    """
    Branch model has historically used either:
    - branch_code
    - code

    Keep this defensive so auth does not break during model evolution.
    """
    if not branch:
        return None

    return (
        getattr(branch, "branch_code", None)
        or getattr(branch, "code", None)
    )


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        raise APIError("MISSING_AUTHORIZATION_HEADER")

    if not auth_header.startswith("Bearer "):
        raise APIError("INVALID_AUTHORIZATION_HEADER")

    token = auth_header.replace("Bearer ", "").strip()

    if not token:
        raise APIError("MISSING_BEARER_TOKEN")

    return token


@auth_router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    payload: LoginSchema,
    db: Session = Depends(get_db),
):
    """
    XBOS login endpoint.

    Auth routes may be bypassed by AuthMiddleware, so tenant/branch context
    can come from either middleware state or HTTP headers.

    Expected headers:
      X-Tenant-Code
      X-Branch-Code
    """

    # ----------------------------------------------------------
    # 1. Try middleware-resolved tenant/branch first
    # ----------------------------------------------------------
    tenant = getattr(request.state, "tenant", None)
    branch = getattr(request.state, "branch", None)

    # ----------------------------------------------------------
    # 2. Fallback to headers
    # ----------------------------------------------------------
    if tenant is None:
        tenant_code = request.headers.get("X-Tenant-Code")
        if not tenant_code:
            raise APIError("MISSING_TENANT_HEADER")
    else:
        tenant_code = getattr(tenant, "code", None)

    if not tenant_code:
        raise APIError("MISSING_TENANT_HEADER")

    if branch is None:
        branch_code = request.headers.get("X-Branch-Code")
        if not branch_code:
            raise APIError("MISSING_BRANCH_HEADER")
    else:
        branch_code = _branch_code(branch)

    if not branch_code:
        raise APIError("MISSING_BRANCH_HEADER")

    # ----------------------------------------------------------
    # 3. Perform login
    # ----------------------------------------------------------
    return service.login(
        db=db,
        username=payload.username,
        password=payload.password,
        tenant_code=tenant_code,
        branch_code=branch_code,
    )


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Refresh access token.

    Refresh token is intentionally lightweight and only carries user identity.
    AuthService reloads the user, tenant, branch, role, and permissions from DB.
    """

    refresh_token = request.headers.get("X-Refresh-Token")

    if not refresh_token:
        raise APIError("MISSING_REFRESH_TOKEN")

    return service.refresh(
        db=db,
        refresh_token=refresh_token,
    )


@auth_router.get("/me", response_model=UserIdentity)
def me(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return the current authenticated user identity.

    Important:
    /kernel/auth/* routes may be bypassed by AuthMiddleware, so this endpoint
    safely decodes the bearer token itself instead of depending only on
    request.state.user.
    """

    # ----------------------------------------------------------
    # 1. Prefer middleware context if available
    # ----------------------------------------------------------
    ctx = getattr(request.state, "user", None)

    if isinstance(ctx, dict) and ctx.get("user_id"):
        return service.me(
            db=db,
            user_id=int(ctx["user_id"]),
        )

    # ----------------------------------------------------------
    # 2. Fallback: decode Authorization bearer token directly
    # ----------------------------------------------------------
    token = _extract_bearer_token(request)

    payload = service.jwt_service.decode_token(token)

    if payload.get("type") != "access":
        raise APIError("INVALID_ACCESS_TOKEN")

    user_id = payload.get("sub")

    if not user_id:
        raise APIError("INVALID_ACCESS_TOKEN")

    return service.me(
        db=db,
        user_id=int(user_id),
    )