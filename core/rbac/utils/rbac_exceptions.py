# core/rbac/utils/rbac_exceptions.py

from fastapi import HTTPException, status


class RBACException(HTTPException):
    """
    Base class for all RBAC-related errors.
    Provides standardized HTTP status codes + messages.
    """

    def __init__(self, message: str, code: int = status.HTTP_403_FORBIDDEN):
        super().__init__(status_code=code, detail=message)


# -------------------------------------------------------------
# COMMON RBAC ERRORS
# -------------------------------------------------------------
class PermissionDenied(RBACException):
    """
    Raised when a user lacks a required permission.
    """
    def __init__(self, permission: str):
        message = f"PERMISSION_DENIED: Missing permission '{permission}'"
        super().__init__(message, status.HTTP_403_FORBIDDEN)


class RoleNotFound(RBACException):
    """
    Raised when a role referenced in token/db does not exist.
    """
    def __init__(self, role: str):
        message = f"ROLE_NOT_FOUND: '{role}'"
        super().__init__(message, status.HTTP_403_FORBIDDEN)


class RoleAlreadyExists(RBACException):
    """
    Raised when attempting to create a role that already exists.
    Required by role_repository and role_service.
    """
    def __init__(self, role: str):
        message = f"ROLE_ALREADY_EXISTS: '{role}'"
        super().__init__(message, status.HTTP_400_BAD_REQUEST)


class InvalidRBACConfiguration(RBACException):
    """
    Raised when permission registry, role packs, or role definitions
    are malformed or refer to missing permissions.
    """
    def __init__(self, issue: str):
        message = f"RBAC_CONFIGURATION_ERROR: {issue}"
        super().__init__(message, status.HTTP_500_INTERNAL_SERVER_ERROR)


class NoRBACContext(RBACException):
    """
    Raised when middleware could not load user or permissions
    before enforcing RBAC.
    """
    def __init__(self):
        super().__init__(
            "RBAC_CONTEXT_MISSING",
            status.HTTP_401_UNAUTHORIZED
        )


class InvalidPermission(RBACException):
    """
    Raised when a permission code is not part of the system registry.
    """
    def __init__(self, permission: str):
        message = f"INVALID_PERMISSION_CODE: '{permission}'"
        super().__init__(message, status.HTTP_400_BAD_REQUEST)
