# core/middleware/branch_middleware.py

import os
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal
from core.tenants.tenant_model import Branch


class BranchMiddleware(BaseHTTPMiddleware):
    """
    Resolves branch context.

    Priority:
    1️⃣ request.state.user (JWT / DEV injection)
    2️⃣ X-Branch-Code header
    3️⃣ DEV fallback (first active branch)
    """

    async def dispatch(self, request: Request, call_next):

        path = request.url.path.lower()
        method = request.method.upper()
        headers = {k.lower(): v for k, v in request.headers.items()}

        # =====================================================
        # BYPASS ROUTES
        # =====================================================
        if (
            path == "/kernel/integrations/xafpay-v2/events"
            or path.startswith("/kernel/auth/")
            or path.startswith("/auth/")
            or path in ("/kernel/health", "/kernel/db-check")
            or path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/openapi.json")
            or method == "OPTIONS"
        ):
            return await call_next(request)

        # =====================================================
        # 1️⃣ Tenant must exist
        # =====================================================
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is None:
            raise HTTPException(status_code=400, detail="TENANT_CONTEXT_MISSING")

        # =====================================================
        # 2️⃣ If user already injected branch → trust it
        # =====================================================
        user = getattr(request.state, "user", None)
        if user and user.get("branch_id"):
            request.state.branch_id = user["branch_id"]
            request.state.branch = None  # Lazy-load if needed
            return await call_next(request)

        # =====================================================
        # 3️⃣ Resolve branch from header / dev fallback
        # =====================================================
        branch_code = headers.get("x-branch-code")
        env = os.getenv("ENV", "development").lower()

        db: Session = SessionLocal()
        try:
            if branch_code:
                branch = (
                    db.query(Branch)
                    .filter(
                        Branch.branch_code == branch_code,
                        Branch.tenant_id == tenant_id,
                    )
                    .first()
                )

                if not branch:
                    raise HTTPException(status_code=404, detail="BRANCH_NOT_FOUND")

            elif env == "development":
                branch = (
                    db.query(Branch)
                    .filter(
                        Branch.tenant_id == tenant_id,
                        Branch.is_active == True,
                    )
                    .order_by(Branch.id.asc())
                    .first()
                )

                if not branch:
                    raise HTTPException(
                        status_code=404,
                        detail="NO_ACTIVE_BRANCH_FOR_TENANT",
                    )

            else:
                raise HTTPException(status_code=400, detail="MISSING_BRANCH_HEADER")

        finally:
            db.close()

        request.state.branch = branch
        request.state.branch_id = branch.id

        return await call_next(request)
