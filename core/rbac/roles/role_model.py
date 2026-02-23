# core/rbac/roles/role_model.py

from sqlalchemy import Column, Integer, String, JSON, DateTime
from sqlalchemy.sql import func
from database import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    
    # Unique name of the role (e.g., 'cashier', 'manager', 'kyc_agent')
    name = Column(String, unique=True, nullable=False)

    # Optional description for admin panels (highly recommended)
    description = Column(String, nullable=True)

    # List of permission codes (e.g., ["SALE_CREATE", "PAY_SEND"])
    permissions = Column(JSON, default=list)  # stored as array/json

    # Optional: If a business wants tenant-specific role definitions:
    # tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    def __repr__(self):
        return f"<Role {self.name} permissions={len(self.permissions or [])}>"
