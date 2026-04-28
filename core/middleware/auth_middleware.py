from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException
import os

from core.security.jwt_service import JWTService


class AuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        path = request.url.path.lower()
        method = request.method.upper()
        headers = {k.lower(): v for k, v in request.headers.items()}

        # 🔥 Define missing variables
        env = os.getenv("ENV", "development").lower()
        auth_header = headers.get("authorization")

        print("\n========== AUTH MIDDLEWARE ==========")
        print("🔥 RAW PATH:", path)
        print("🔥 METHOD:", method)
        print("🔥 HEADERS:", headers)

        # =====================================================
        # 1️⃣ PUBLIC / BYPASS ROUTES
        # =====================================================
        bypass = (
            path.startswith("/kernel/auth/") or
            path.startswith("/auth/") or
            path == "/kernel/health" or
            path == "/kernel/db-check" or
            method == "OPTIONS"  # ✅ FIXED
        )

        print("🔥 FINAL BYPASS =", bypass)

        if bypass:
            print("🔥 AUTH BYPASSED — public route")
            return await call_next(request)

        # =====================================================
        # 2️⃣ DEV MODE — AUTO-INJECT USER
        # =====================================================
        if env == "development" and not auth_header:
            request.state.user = {
                "user_id": 1,
                "tenant_id": 2,
                "branch_id": 1,
                "role": "cashier",
                "permissions": [
                    "catalog.view",
                    "sale.create",
                    "sale.view",
                    "payments.receive",
                    "payments.view",
                    "order.create",
                    "order.view",
                ],
            }

            print("🔥 DEV AUTH CONTEXT INJECTED:", request.state.user)
            return await call_next(request)

        # =====================================================
        # 3️⃣ REQUIRE AUTHORIZATION HEADER (PROD)
        # =====================================================
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")

        token = auth_header.replace("Bearer ", "").strip()

        # =====================================================
        # 4️⃣ DECODE TOKEN
        # =====================================================
        jwt = JWTService()

        try:
            payload = jwt.decode_token(token)
        except Exception as e:
            raise HTTPException(status_code=401, detail=str(e))

        print("🔥 JWT PAYLOAD:", payload)

        # =====================================================
        # 5️⃣ VALIDATE REQUIRED FIELDS
        # =====================================================
        required_keys = ["sub", "tenant_id", "branch_id", "role"]

        for key in required_keys:
            if key not in payload:
                raise HTTPException(
                    status_code=401,
                    detail=f"Token missing required field: {key}"
                )

        permissions = payload.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = []

        # =====================================================
        # 6️⃣ INJECT AUTH CONTEXT
        # =====================================================
        request.state.user = {
            "user_id": int(payload["sub"]),
            "tenant_id": int(payload["tenant_id"]),
            "branch_id": int(payload["branch_id"]),
            "role": payload["role"],
            "permissions": permissions,
        }

        print("🔥 AUTH CONTEXT INJECTED:", request.state.user)

        return await call_next(request)
