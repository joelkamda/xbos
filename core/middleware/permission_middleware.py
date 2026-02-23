from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException


ROLE_PERMISSIONS = {
    "admin": ["*"],
    "manager": ["read", "write"],
    "cashier": ["read"],
    "viewer": ["read"]
}


class PermissionMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        # Allow public routes
        if request.url.path.startswith("/kernel/auth/") or request.url.path == "/kernel/health":
            return await call_next(request)

        role = getattr(request.state, "role", None)
        if not role:
            raise HTTPException(403, "No role found on user")

        # Simple: determine if write or read
        method = request.method.lower()

        if method in ["post", "put", "patch", "delete"]:
            required = "write"
        else:
            required = "read"

        allowed = ROLE_PERMISSIONS.get(role, [])

        if "*" in allowed or required in allowed:
            return await call_next(request)

        raise HTTPException(403, f"Role '{role}' not allowed to perform '{required}' operations")
