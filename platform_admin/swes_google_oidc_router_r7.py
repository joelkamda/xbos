"""Candidate internal browser adapter. NOT registered in startup or deployed.

Login proof only, never first-admin enrollment. Require external owner subject
pin/authority and canonical PC5 issuer integration in a separately qualified cutover.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from platform_admin.swes_google_oidc_r7 import (
    OIDCConfig,
    OIDCHold,
    begin,
    finish,
)
from platform_admin.swes_google_oidc_sql_r7 import SQLChallengeStore

router = APIRouter(prefix="/internal/swes/pa/oidc", tags=["TEST-only OIDC"])
COOKIE = "__Host-swes-pa-oidc-state"


def _config() -> OIDCConfig:
    if os.getenv("SWES_OIDC_ENABLED") != "true":
        raise OIDCHold("HOLD_OIDC_NOT_ADMITTED")
    return OIDCConfig(
        os.environ.get("SWES_OIDC_CLIENT_ID", ""),
        os.environ.get("SWES_OIDC_CLIENT_SECRET", ""),
        os.environ.get("SWES_OIDC_REDIRECT_URI", ""),
        os.environ.get("SWES_OIDC_OWNER_SUBJECT_SHA256") or None,
    )


def _store() -> SQLChallengeStore:
    # Reject absent or malformed challenge-sealing keys before importing any
    # application DB configuration. Never expose a DATABASE_URL or key error.
    from cryptography.fernet import Fernet
    key = os.environ.get("SWES_OIDC_CHALLENGE_FERNET_KEY")
    if not key:
        raise OIDCHold("HOLD_CHALLENGE_SEAL_KEY_ABSENT")
    try:
        Fernet(key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise OIDCHold("HOLD_CHALLENGE_SEAL_KEY_INVALID") from exc
    from platform_admin.swes_oidc_writer_r11 import create_restricted_oidc_engine
    # There is no shared database.engine or DATABASE_URL fallback. This engine
    # authenticates a separate restricted LOGIN and verifies every connection.
    restricted_engine = create_restricted_oidc_engine()
    return SQLChallengeStore(restricted_engine, fernet_key=key)


@router.get("/start")
def oidc_start():
    try:
        url, state = begin(_config(), _store(), now=datetime.now(timezone.utc))
    except OIDCHold as exc:
        raise HTTPException(status_code=503, detail=exc.code) from None
    except Exception:  # noqa: BLE001 - fail-closed HTTP trust boundary
        raise HTTPException(status_code=503, detail="HOLD_OIDC_RUNTIME_UNAVAILABLE") from None
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(COOKIE, state, secure=True, httponly=True,
                        samesite="lax", max_age=300, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback")
def oidc_callback(request: Request, code: str = "", state: str = ""):
    try:
        config = _config()
        with httpx.Client() as http:
            identity = finish(
                config, _store(), state=state,
                browser_state=request.cookies.get(COOKIE, ""),
                code=code, now=datetime.now(timezone.utc), http=http
            )
        # A Render environment Boolean is not an independent CEO approval
        # authority. Keep the public login callback explicitly non-enrolling.
        # A separate owner-bound admission with real audit provenance must
        # execute canonical PC5 commands after the completed human ceremony.
        response = JSONResponse({
            "status": "GOOGLE_OIDC_AUTHENTICATED_ONLY",
            "tenant_id": identity.tenant_id,
            "issuer": identity.issuer,
            "subject_sha256": identity.subject_sha256,
            "owner_binding_verified": False,
            "pc5_session_created": False,
            "administrative_permission_granted": False,
            "assurance_level": identity.assurance_level,
        })
    except OIDCHold as exc:
        response = JSONResponse({"status": "HOLD", "code": exc.code}, status_code=403)
    except Exception:  # noqa: BLE001 - fail-closed HTTP trust boundary
        response = JSONResponse({"status": "HOLD", "code": "HOLD_OIDC_RUNTIME_UNAVAILABLE"},
                                status_code=503)
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
