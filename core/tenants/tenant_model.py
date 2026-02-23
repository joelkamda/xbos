# core/tenants/tenant_model.py

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

    # Country metadata
    country_code = Column(String(2), nullable=False)
    country_name = Column(String, nullable=True)

    currency = Column(String(3), nullable=False)
    locale = Column(String, nullable=False)
    timezone = Column(String, nullable=False)

    settings = Column(JSON, default={})
    extra_metadata = Column(JSON, default={})

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # RELATIONSHIPS
    branches = relationship("Branch", back_populates="tenant", cascade="all, delete")
    users = relationship("User", back_populates="tenant", cascade="all, delete")

    def __repr__(self):
        return f"<Tenant {self.code} - {self.name}>"


class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    branch_code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    city = Column(String, nullable=True)
    address = Column(String, nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # RELATIONSHIPS
    tenant = relationship("Tenant", back_populates="branches")
    users = relationship("User", back_populates="branch", cascade="all, delete")

    def __repr__(self):
        return f"<Branch {self.branch_code} - {self.name}>"
