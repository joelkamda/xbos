# core/tenants/schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List


# ------------------------------
# BRANCH RESPONSE
# ------------------------------
class BranchOut(BaseModel):
    id: int
    branch_code: str
    name: str
    is_active: bool

    class Config:
        from_attributes = True


# ------------------------------
# TENANT RESPONSE
# ------------------------------
class TenantOut(BaseModel):
    id: int
    code: str
    name: str
    country_code: str
    currency: str
    locale: str
    timezone: str
    branches: List[BranchOut] = []

    class Config:
        from_attributes = True


# ------------------------------
# CREATE REQUESTS
# ------------------------------
class TenantCreate(BaseModel):
    name: str
    country_code: str
    override_locale: Optional[str] = None
    override_timezone: Optional[str] = None
    override_currency: Optional[str] = None


class BranchCreate(BaseModel):
    tenant_id: int
    name: str


# ------------------------------
# UPDATE REQUESTS
# ------------------------------
class TenantUpdate(BaseModel):
    name: Optional[str] = None
    country_code: Optional[str] = None
    currency: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
