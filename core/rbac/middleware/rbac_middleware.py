from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError
from core.rbac.utils.rbac_exceptions import PermissionDenied
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY
from core.rbac.roles.role_repository import RoleRepository
from core.security.jwt_service import JWTService
from database import SessionLocal


class RBACMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.lower()
        method = request.method

        # ---------------------------------------------------------
        # PUBLIC / AUTH ROUTES ARE ALWAYS ALLOWED
        # ---------------------------------------------------------
        if (
            path.startswith("/kernel/auth/") or
            path == "/kernel/health" or
            method == "OPTIONS"
        ):
            return await call_next(request)

        # ---------------------------------------------------------
        # USER MUST BE PRESENT (from AuthMiddleware)
        # ---------------------------------------------------------
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="UNAUTHENTICATED")

        # ---------------------------------------------------------
        # EXTRACT PERMISSIONS DIRECTLY FROM JWT
        # (this supports I + R)
        # ---------------------------------------------------------
        permissions = getattr(request.state, "permissions", None)

        # If missing, fall back to user.role (older mode)
        if permissions is None:
            db = SessionLocal()
            role = RoleRepository.find_by_name(db, user.role)
            db.close()

            if not role:
                raise HTTPException(403, "ROLE_NOT_FOUND")

            permissions = role.permissions

        # Attach to request for downstream policies
        request.state.permissions = permissions

        # Admin is the canonical superuser; do not require enumerating every
        # newly introduced leaf permission in role/JWT projections.
        if str(user.get("role", "")).strip().lower() == "admin":
            return await call_next(request)

        # ---------------------------------------------------------
        # ENFORCEMENT USING PERMISSION REGISTRY
        # ---------------------------------------------------------
        required_perm = PERMISSION_REGISTRY.resolve(path, method)

        if required_perm is None:
            # No permission rule defined → route is public
            return await call_next(request)

        # Check if user has permission
        if required_perm not in permissions:
            raise PermissionDenied(required_perm)

        return await call_next(request)
