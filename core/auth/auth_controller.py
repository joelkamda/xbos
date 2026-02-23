# core/auth/auth_controller.py

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from core.auth.auth_service import AuthService
from core.auth.schemas import LoginSchema, TokenResponse
from core.errors.api_error import APIError

auth_router = APIRouter(tags=["Auth"])
service = AuthService()


@auth_router.post("/login", response_model=TokenResponse)
def login(request: Request, payload: LoginSchema, db: Session = Depends(get_db)):
    """
    XBOS login endpoint.
    When middleware bypasses (auth routes), tenant/branch must be taken from headers.
    """

    # ----------------------------------------------------------
    # 1. Try to read tenant/branch from middleware first
    # ----------------------------------------------------------
    tenant = getattr(request.state, "tenant", None)
    branch = getattr(request.state, "branch", None)

    # ----------------------------------------------------------
    # 2. But if middleware bypassed, fall back to headers
    # ----------------------------------------------------------
    if tenant is None:
        tenant_code = request.headers.get("X-Tenant-Code")
        if not tenant_code:
            raise APIError("MISSING_TENANT_HEADER")
    else:
        tenant_code = tenant.code

    if branch is None:
        branch_code = request.headers.get("X-Branch-Code")
        if not branch_code:
            raise APIError("MISSING_BRANCH_HEADER")
    else:
        branch_code = branch.code

    # ----------------------------------------------------------
    # 3. Perform login using final values
    # ----------------------------------------------------------
    return service.login(
        db=db,
        username=payload.username,
        password=payload.password,
        tenant_code=tenant_code,
        branch_code=branch_code,
    )



@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, db: Session = Depends(get_db)):
    """
    Refresh access token using
    X-Refresh-Token + middleware-resolved tenant/branch.
    """
    refresh_token = request.headers.get("X-Refresh-Token")
    if not refresh_token:
        raise APIError("MISSING_REFRESH_TOKEN")

    tenant = getattr(request.state, "tenant", None)
    branch = getattr(request.state, "branch", None)

    if tenant is None or branch is None:
        raise APIError("TENANT_OR_BRANCH_CONTEXT_MISSING")

    return service.refresh(
        db=db,
        refresh_token=refresh_token,
        tenant_code=tenant.code,
        branch_code=branch.code,
    )
