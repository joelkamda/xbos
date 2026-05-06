# core/users/user_model.py

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime

# Tenant and Branch both live in core.tenants.tenant_model
from core.tenants.tenant_model import Tenant, Branch


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # Login credentials
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    # Optional profile metadata
    full_name = Column(String(100))
    phone = Column(String(30))

    # RBAC role ("staff", "cashier", "manager", "admin")
    role = Column(String(50), default="staff")

    # Multi-tenant FKs
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)

    # State
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # ORM relationships
    tenant = relationship("Tenant", back_populates="users")
    branch = relationship("Branch", back_populates="users")

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"