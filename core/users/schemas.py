# core/users/schemas.py

from pydantic import BaseModel, Field
from typing import Optional


class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: str
    tenant_id: int
    branch_id: int
    is_active: bool

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    full_name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    role: str = Field(default="staff", max_length=50)
    branch_id: Optional[int] = None
    is_active: bool = True


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, min_length=2, max_length=50)
    full_name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    role: Optional[str] = Field(default=None, max_length=50)
    branch_id: Optional[int] = None
    is_active: Optional[bool] = None


class PasswordResetPayload(BaseModel):
    password: str = Field(..., min_length=6)


class UserListResponse(BaseModel):
    items: list[UserOut]
    count: int