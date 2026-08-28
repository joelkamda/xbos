# core/rbac/utils/permission_decorator.py

import functools
import inspect
from fastapi import Request, HTTPException, status


def _find_request(args, kwargs) -> Request:
    """
    Find the FastAPI Request object from decorated endpoint args/kwargs.

    Supports:
      async def route(request: Request, ...)
      def route(request: Request, ...)
      def route(..., request: Request, ...)
    """

    request = kwargs.get("request")

    if isinstance(request, Request):
        return request

    for arg in args:
        if isinstance(arg, Request):
            return arg

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="RBAC decorator could not locate Request object. Endpoint must include request: Request.",
    )


def _check_permissions(request: Request, required_permissions: tuple[str, ...]):
    """
    Validate authenticated user permissions.

    AuthMiddleware now provides both:
      request.state.user["permissions"]
      request.state.permissions
    """

    user = getattr(request.state, "user", None)

    if not user or not isinstance(user, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="RBAC_NOT_INITIALIZED: No user context.",
        )

    permissions = getattr(request.state, "permissions", None)

    if permissions is None:
        permissions = user.get("permissions", [])

    if not isinstance(permissions, list):
        permissions = []

    permission_set = set(str(p).strip() for p in permissions if p)

    print(f"🔐 RBAC CHECK → required={list(required_permissions)}")
    print(f"🔐 RBAC USER → role={user.get('role')} permissions_count={len(permission_set)}")

    # Future super-admin wildcard support.
    if "*" in permission_set:
        return True

    # The canonical admin role is the platform superuser and retains all
    # ordinary application permissions, including newly added leaf codes.
    if str(user.get("role", "")).strip().lower() == "admin":
        return True

    # If decorator has no required permissions, only authentication is required.
    if not required_permissions:
        return True

    # ANY permission match.
    if any(permission in permission_set for permission in required_permissions):
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "PERMISSION_DENIED",
            "required_any": list(required_permissions),
            "user_permissions_count": len(permission_set),
        },
    )


def require_permissions(*required_permissions: str):
    """
    Route-level RBAC decorator.

    Usage:
      @require_permissions("sale.view")
      @require_permissions("order.create", "sale.create")

    Multiple permissions use ANY logic:
      user needs at least one of the listed permissions.

    Supports both sync and async FastAPI endpoints.
    """

    required_permissions = tuple(str(p).strip() for p in required_permissions if p)

    def decorator(endpoint_func):
        is_async = inspect.iscoroutinefunction(endpoint_func)

        @functools.wraps(endpoint_func)
        async def wrapper(*args, **kwargs):
            request = _find_request(args, kwargs)
            _check_permissions(request, required_permissions)

            if is_async:
                return await endpoint_func(*args, **kwargs)

            return endpoint_func(*args, **kwargs)

        return wrapper

    return decorator
