# core/middleware/auth_middleware.py

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse

from core.security.jwt_service import JWTService


class AuthMiddleware(BaseHTTPMiddleware):
    """
    XBOS authentication middleware.

    Responsibilities:
    - Allow public routes: login, refresh, health, docs, OpenAPI, OPTIONS.
    - Require Authorization: Bearer <token> for protected routes.
    - Decode JWT access token.
    - Inject normalized auth context into request.state.

    IMPORTANT:
    - No fake development cashier injection.
    - Real login must be used in development and production.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.lower()
        method = request.method.upper()
        headers = {k.lower(): v for k, v in request.headers.items()}

        auth_header = headers.get("authorization")

        # =====================================================
        # 1) PUBLIC / BYPASS ROUTES
        # =====================================================
        bypass = (
            path.startswith("/kernel/browser-session/v1/")
            or path.startswith("/kernel/auth/")
            or path.startswith("/auth/")
            or path.startswith("/internal/customer-channel/v1")
            or path == "/kernel/health"
            or path == "/kernel/db-check"
            or path == "/kernel/integrations/xafpay-v2/events"
            or path == "/health"
            or path == "/docs"
            or path.startswith("/docs/")
            or path == "/redoc"
            or path.startswith("/redoc/")
            or path == "/openapi.json"
            or path.startswith("/static/")
            or method == "OPTIONS"
        )

        if bypass:
            return await call_next(request)

        # Exact C2 discovery path delegates authentication to the route's
        # server-validated browser-session v1 authority. Legacy middleware
        # JWT acceptance and legacy error envelopes are not applicable here.
        if path == "/kernel/platform/v1/pack-template-discovery":
            return await call_next(request)

        # =====================================================
        # 2) REQUIRE AUTHORIZATION HEADER
        # =====================================================
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization header"},
            )

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid Authorization header"},
            )

        token = auth_header.replace("Bearer ", "").strip()

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing bearer token"},
            )

        # =====================================================
        # 3) DECODE TOKEN
        # =====================================================
        jwt = JWTService()

        try:
            payload = jwt.decode_token(token)
        except Exception as e:
            return JSONResponse(
                status_code=401,
                content={"detail": str(e)},
            )

        # Browser token claims are never the authorization source. Re-read
        # current session, user, tenant, branch, role and permissions each request.
        if payload.get("type") == "browser_access":
            from database import SessionLocal
            from core.auth.browser_session_service import (
                BrowserSessionDenied, validate_browser_access,
            )
            db = SessionLocal()
            try:
                authority = validate_browser_access(db, token)
            except BrowserSessionDenied:
                return JSONResponse(status_code=401, content={"detail": "BROWSER_SESSION_INVALID"})
            finally:
                db.close()
            request.state.user = authority
            request.state.user_id = authority["user_id"]
            request.state.tenant_id = authority["tenant_id"]
            request.state.branch_id = authority["branch_id"]
            request.state.role = authority["role"]
            request.state.permissions = authority["permissions"]
            return await call_next(request)

        # =====================================================
        # 4) VALIDATE LEGACY TOKEN TYPE
        # =====================================================
        if payload.get("type") != "access":
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token type"},
            )

        # =====================================================
        # 5) VALIDATE REQUIRED FIELDS
        # =====================================================
        required_keys = ["sub", "tenant_id", "branch_id", "role"]

        for key in required_keys:
            if key not in payload:
                return JSONResponse(
                    status_code=401,
                    content={"detail": f"Token missing required field: {key}"},
                )

        try:
            user_id = int(payload["sub"])
            tenant_id = int(payload["tenant_id"])
            branch_id = int(payload["branch_id"])
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token identity fields"},
            )

        role = str(payload.get("role") or "").strip()

        if not role:
            return JSONResponse(
                status_code=401,
                content={"detail": "Token missing role"},
            )

        permissions = payload.get("permissions", [])

        if not isinstance(permissions, list):
            permissions = []

        permissions = sorted(set(str(p).strip() for p in permissions if p))

        # =====================================================
        # 6) INJECT NORMALIZED AUTH CONTEXT
        # =====================================================
        request.state.user = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "role": role,
            "permissions": permissions,
        }

        # Convenience aliases for controllers, decorators, and future middleware.
        request.state.user_id = user_id
        request.state.tenant_id = tenant_id
        request.state.branch_id = branch_id
        request.state.role = role
        request.state.permissions = permissions

        return await call_next(request)