# core/auth/schemas.py

from pydantic import BaseModel
from typing import Optional


# ---------------------------------------------------------
# LOGIN REQUEST (BODY)
# ---------------------------------------------------------
# Tenant and Branch come from HTTP headers:
#   X-Tenant-Code
#   X-Branch-Code
#
# Login body only contains username + password.
class LoginSchema(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------
# USER BLOCK INSIDE AUTH RESPONSES
# ---------------------------------------------------------
class UserIdentity(BaseModel):
    id: int
    username: str

    # Profile metadata
    full_name: Optional[str] = None
    phone: Optional[str] = None

    # RBAC
    role: Optional[str] = None
    permissions: list[str] = []

    # Tenant / branch context
    tenant_id: int
    branch_id: Optional[int] = None
    tenant_code: Optional[str] = None
    branch_code: Optional[str] = None


# ---------------------------------------------------------
# TOKEN RESPONSE
# Returned by:
#   POST /kernel/auth/login
#   POST /kernel/auth/refresh
# ---------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserIdentity] = None