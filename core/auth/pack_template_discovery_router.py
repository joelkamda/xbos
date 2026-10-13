"""Authenticated browser-session v1 read-only PK discovery HTTP adapter.

Identity is loaded from the validated browser session, never caller tenant headers
or middleware-generated fallback context.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from core.auth.auth_service import AuthService
from core.auth.browser_session_service import BrowserSessionDenied, validate_browser_access
from pack_platform.discovery_read_model import read_discovery

router = APIRouter(tags=["XBOS Platform Discovery"])


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code}},
        headers={"Cache-Control": "private, no-store", "Vary": "Authorization"},
    )


@router.get("/platform/v1/pack-template-discovery")
def discover_pack_templates(request: Request, db: Session = Depends(get_db)):
    if request.query_params:
        return _error(403, "TRUST_CONTEXT_UNAVAILABLE")

    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        return _error(401, "UNAUTHENTICATED")
    access_token = authorization[7:].strip()

    # First statement in this transaction precedes every auth and discovery
    # query, making the entire session transaction read-only.
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
    except Exception:
        db.rollback()
        return _error(503, "DISCOVERY_UNAVAILABLE")

    try:
        authority = validate_browser_access(db, access_token)
    except BrowserSessionDenied:
        return _error(401, "UNAUTHENTICATED")
    except Exception:
        return _error(503, "DISCOVERY_UNAVAILABLE")

    if not isinstance(authority, dict) or type(authority.get("user_id")) is not int:
        return _error(403, "TRUST_CONTEXT_UNAVAILABLE")
    tenant_id = authority.get("tenant_id")
    branch_id = authority.get("branch_id")
    if (type(tenant_id) is not int or tenant_id < 1
        or type(branch_id) is not int or branch_id < 1):
        return _error(403, "TENANT_CONTEXT_UNAVAILABLE")

    try:
        identity = AuthService().me(db=db, user_id=authority["user_id"])
    except Exception:
        return _error(403, "TRUST_CONTEXT_UNAVAILABLE")
    if (not isinstance(identity, dict)
        or identity.get("id") != authority["user_id"]
        or identity.get("role") != authority.get("role")):
        return _error(403, "TRUST_CONTEXT_UNAVAILABLE")
    if identity.get("tenant_id") != tenant_id or identity.get("branch_id") != branch_id:
        return _error(403, "TENANT_CONTEXT_UNAVAILABLE")

    try:
        payload = read_discovery(db, tenant_id)
    except Exception:
        return _error(503, "DISCOVERY_UNAVAILABLE")

    return JSONResponse(
        status_code=200,
        content=payload,
        headers={"Cache-Control": "private, no-store", "Vary": "Authorization"},
    )
