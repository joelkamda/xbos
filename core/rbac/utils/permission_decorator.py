# core/rbac/utils/permission_decorator.py

from fastapi import Request, HTTPException
from functools import wraps


def require_permissions(*required_permissions):
    """
    Enforces RBAC permissions at the FastAPI route level.

    Example:
        @require_permissions("sale.view")
        @require_permissions("inventory.edit", "inventory.view")
    """

    required_permissions = set(required_permissions)

    def decorator(endpoint_func):

        @wraps(endpoint_func)
        async def wrapper(*args, **kwargs):

            # ------------------------------------------
            # Extract request object from args/kwargs
            # ------------------------------------------
            request: Request = None

            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if request is None:
                request = kwargs.get("request")

            if request is None:
                raise RuntimeError(
                    "RBAC ERROR: endpoint must include `request: Request` parameter"
                )

            # ------------------------------------------
            # Extract user RBAC context from middleware
            # ------------------------------------------
            user = getattr(request.state, "user", None)

            if not user:
                raise HTTPException(
                    status_code=403,
                    detail="RBAC_NOT_INITIALIZED: No user context"
                )

            user_permissions = user.get("permissions", [])

            if not isinstance(user_permissions, list):
                user_permissions = []

            # Debug:
            print(f"🔐 RBAC CHECK → required={required_permissions}")
            print(f"🔐 User permissions: {user_permissions}")

            # ------------------------------------------
            # Permission check (ANY allowed)
            # ------------------------------------------
            if required_permissions.intersection(user_permissions):
                return await endpoint_func(*args, **kwargs)

            # ------------------------------------------
            # Reject access if no required permission is found
            # ------------------------------------------
            raise HTTPException(
                status_code=403,
                detail=f"PERMISSION_DENIED: missing any of {list(required_permissions)}"
            )

        return wrapper

    return decorator
