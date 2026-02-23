# core/middleware/tenant_middleware.py

import os
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal
from core.tenants.tenant_model import Tenant


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Resolves tenant context.

    Priority:
    1️⃣ request.state.user (JWT / DEV injection)
    2️⃣ X-Tenant-Code header
    3️⃣ DEV fallback (CM001)
    """

    async def dispatch(self, request: Request, call_next):

        path = request.url.path.lower()
        method = request.method.upper()
        headers = {k.lower(): v for k, v in request.headers.items()}

        # =====================================================
        # BYPASS ROUTES
        # =====================================================
        if (
            path.startswith("/kernel/auth/")
            or path.startswith("/auth/")
            or path in ("/kernel/health", "/kernel/db-check")
            or method == "OPTIONS"
        ):
            return await call_next(request)

        # =====================================================
        # 1️⃣ If user already injected → trust it
        # =====================================================
        user = getattr(request.state, "user", None)
        if user and user.get("tenant_id"):
            request.state.tenant_id = user["tenant_id"]
            request.state.tenant = None  # Lazy-load only if needed
            return await call_next(request)

        # =====================================================
        # 2️⃣ Resolve from header
        # =====================================================
        tenant_code = headers.get("x-tenant-code")
        env = os.getenv("ENV", "development").lower()

        if not tenant_code:
            if env == "development":
                tenant_code = os.getenv("DEV_TENANT_CODE", "CM001")
            else:
                raise HTTPException(status_code=400, detail="MISSING_TENANT_HEADER")

        # =====================================================
        # 3️⃣ Lookup Tenant in DB
        # =====================================================
        db: Session = SessionLocal()
        try:
            tenant = (
                db.query(Tenant)
                .filter(Tenant.code == tenant_code)
                .first()
            )
        finally:
            db.close()

        if not tenant:
            raise HTTPException(status_code=404, detail="TENANT_NOT_FOUND")

        request.state.tenant = tenant
        request.state.tenant_id = tenant.id

        return await call_next(request)
