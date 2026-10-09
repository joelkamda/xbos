"""Public additive browser-session.v1. Same-origin credential change policy."""
import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from core.auth.auth_service import AuthService
from core.auth.browser_session_contracts import BrowserSessionAccess, BrowserSessionLogout
from core.auth.schemas import LoginSchema
from core.auth.browser_session_service import (
    BrowserSessionDenied, BrowserConcurrentRefresh,
    create_session, continue_session, revoke_session, REFRESH_SECONDS,
)

router = APIRouter(prefix="/browser-session/v1", tags=["XBOS Browser Session v1"])
COOKIE = "__Host-xbos_refresh"
HEADER = "X-XBOS-Browser-Session"


def origin_guard(request: Request):
    origin = request.headers.get("origin")
    allowed = {x.strip() for x in os.getenv("XBOS_BROWSER_ALLOWED_ORIGINS", "").split(",") if x.strip()}
    if not allowed and os.getenv("ENV", "production").lower() == "development":
        allowed = {"http://localhost:5173", "http://127.0.0.1:5173"}
    if not origin or origin not in allowed or request.headers.get(HEADER) != "1":
        raise HTTPException(status_code=403, detail="BROWSER_ORIGIN_DENIED")
    content_type = request.headers.get("content-type", "")
    if request.url.path.endswith("/login") and not content_type.startswith("application/json"):
        raise HTTPException(status_code=415, detail="JSON_REQUIRED")


def set_refresh_cookie(response: Response, token: str, remaining: int):
    response.set_cookie(
        key=COOKIE, value=token, httponly=True, secure=True,
        samesite="lax", path="/", max_age=max(0, min(REFRESH_SECONDS, remaining)),
    )


def clear_refresh_cookie(response: Response):
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")


@router.post("/login", response_model=BrowserSessionAccess)
def browser_login(request: Request, response: Response, payload: LoginSchema, db: Session = Depends(get_db)):
    origin_guard(request)
    tenant_code = request.headers.get("X-Tenant-Code")
    branch_code = request.headers.get("X-Branch-Code")
    if not tenant_code or not branch_code:
        raise HTTPException(status_code=400, detail="LOGIN_CONTEXT_REQUIRED")
    # Existing XBOS password + tenant/branch binding.
    result = AuthService().login(db, payload.username, payload.password, tenant_code, branch_code)
    identity = result["user"]
    row, access, refresh = create_session(db, identity["id"], identity["tenant_id"], identity["branch_id"])
    set_refresh_cookie(response, refresh, REFRESH_SECONDS)
    return {"access_token": access, "token_type": "bearer", "expires_in": 900}


@router.post("/continue", response_model=BrowserSessionAccess)
def browser_continue(request: Request, response: Response, db: Session = Depends(get_db)):
    origin_guard(request)
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="SESSION_COOKIE_REQUIRED")
    try:
        row, access, refresh = continue_session(db, token)
    except BrowserConcurrentRefresh:
        raise HTTPException(status_code=409, detail="CONCURRENT_REFRESH_RETRY")
    except BrowserSessionDenied:
        raise HTTPException(status_code=401, detail="SESSION_INVALID")
    from core.auth.browser_session_service import aware, now_utc
    remaining = int((aware(row.expires_at) - now_utc()).total_seconds())
    set_refresh_cookie(response, refresh, remaining)
    return {"access_token": access, "token_type": "bearer", "expires_in": 900}


@router.post("/logout", response_model=BrowserSessionLogout)
def browser_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    origin_guard(request)
    revoke_session(db, request.cookies.get(COOKIE))
    clear_refresh_cookie(response)
    return {"status": "logged_out"}
