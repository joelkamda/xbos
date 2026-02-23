# core/auth/schemas.py

from pydantic import BaseModel


# ---------------------------------------------------------
# LOGIN REQUEST (BODY)
# ---------------------------------------------------------
# Tenant and Branch now come EXCLUSIVELY from HTTP headers:
#   X-Tenant-Code
#   X-Branch-Code
#
# So the login body only contains username + password.
class LoginSchema(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------
# USER BLOCK INSIDE TOKEN RESPONSE
# ---------------------------------------------------------
class UserIdentity(BaseModel):
    id: int
    username: str
    role: str | None = None
    tenant_id: int
    branch_id: int | None = None


# ---------------------------------------------------------
# TOKEN RESPONSE (returned by /login and /refresh)
# ---------------------------------------------------------
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: UserIdentity | None = None
