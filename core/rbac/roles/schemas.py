# core/rbac/roles/schemas.py

from pydantic import BaseModel
from typing import Optional


class RoleOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    permissions: list[str] = []
    permission_count: int = 0

    class Config:
        from_attributes = True


class RoleListResponse(BaseModel):
    items: list[RoleOut]
    count: int