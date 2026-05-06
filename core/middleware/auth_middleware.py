# core/middleware/auth_middleware.py

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import os

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

        env = os.getenv("ENV", "development").lower()
        auth_header = headers.get("authorization")

        print("\n========== AUTH MIDDLEWARE ==========")
        print("🔥 RAW PATH:", path)
        print("🔥 METHOD:", method)
        print("🔥 ENV:", env)
        print("🔥 HAS AUTH HEADER:", bool(auth_header))

        # =====================================================
        # 1) PUBLIC / BYPASS ROUTES
        # =====================================================
        bypass = (
            path.startswith("/kernel/auth/")
            or path.startswith("/auth/")
            or path == "/kernel/health"
            or path == "/kernel/db-check"
            or path == "/health"
            or path == "/docs"
            or path.startswith("/docs/")
            or path == "/redoc"
            or path.startswith("/redoc/")
            or path == "/openapi.json"
            or path.startswith("/static/")
            or method == "OPTIONS"
        )

        print("🔥 FINAL BYPASS =", bypass)

        if bypass:
            print("🔥 AUTH BYPASSED — public/docs/health route")
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

        print("🔥 JWT PAYLOAD:", payload)

        # =====================================================
        # 4) VALIDATE TOKEN TYPE
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

        print("🔥 AUTH CONTEXT INJECTED:", request.state.user)

        return await call_next(request)