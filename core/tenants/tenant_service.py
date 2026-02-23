# core/tenants/tenant_service.py

from sqlalchemy.orm import Session
from database import SessionLocal

from core.tenants.tenant_model import Tenant, Branch
from core.tenants.schemas import TenantCreate, TenantUpdate, BranchCreate, BranchUpdate
from core.tenants.country_utils import get_country_details
from core.tenants.tenant_id_generator import generate_tenant_code
from core.tenants.branch_code_generator import generate_branch_code

from core.errors.api_error import APIError


class TenantService:

    def db(self) -> Session:
        return SessionLocal()

    # -------------------------------
    # CREATE TENANT + DEFAULT BRANCH
    # -------------------------------
    def create_tenant(self, payload: TenantCreate):
        db = self.db()

        existing = db.query(Tenant).filter(Tenant.name.ilike(payload.name)).first()
        if existing:
            raise APIError("TENANT_ALREADY_EXISTS")

        meta = get_country_details(payload.country_code)

        prefix = payload.country_code.upper()
        tenant_code = generate_tenant_code(db, prefix)

        tenant = Tenant(
            name=payload.name,
            code=tenant_code,
            country_code=payload.country_code,
            currency=payload.override_currency or meta["currency"],
            locale=payload.override_locale or meta["locale"],
            timezone=payload.override_timezone or meta["timezone"],
        )

        db.add(tenant)
        db.flush()

        branch_code = generate_branch_code(db, tenant.id)

        branch = Branch(
            tenant_id=tenant.id,
            name="Head Office",
            branch_code=branch_code,
            is_active=True,
        )

        db.add(branch)
        db.commit()

        db.refresh(tenant)
        db.refresh(branch)

        return tenant  # ✔ FastAPI will serialize via TenantOut

    # -------------------------------
    # FETCH + UPDATE + DELETE
    # -------------------------------
    def get_tenant(self, tenant_id: int):
        db = self.db()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise APIError("TENANT_NOT_FOUND")
        return tenant

    def list_tenants(self):
        db = self.db()
        return db.query(Tenant).all()

    def update_tenant(self, tenant_id: int, payload: TenantUpdate):
        db = self.db()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise APIError("TENANT_NOT_FOUND")

        for field, value in payload.dict(exclude_unset=True).items():
            setattr(tenant, field, value)

        db.commit()
        db.refresh(tenant)
        return tenant

    def delete_tenant(self, tenant_id: int):
        db = self.db()
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise APIError("TENANT_NOT_FOUND")

        db.delete(tenant)
        db.commit()

        return True

    # -------------------------------
    # BRANCH OPERATIONS
    # -------------------------------
    def create_branch(self, payload: BranchCreate):
        db = self.db()

        tenant = db.query(Tenant).filter(Tenant.id == payload.tenant_id).first()
        if not tenant:
            raise APIError("TENANT_NOT_FOUND")

        branch_code = generate_branch_code(db, payload.tenant_id)

        branch = Branch(
            tenant_id=payload.tenant_id,
            name=payload.name,
            branch_code=branch_code,
        )

        db.add(branch)
        db.commit()
        db.refresh(branch)
        return branch

    def get_branches(self, tenant_id: int):
        db = self.db()
        return db.query(Branch).filter(Branch.tenant_id == tenant_id).all()

    def get_branch(self, branch_id: int):
        db = self.db()
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise APIError("BRANCH_NOT_FOUND")
        return branch

    def update_branch(self, branch_id: int, payload: BranchUpdate):
        db = self.db()
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise APIError("BRANCH_NOT_FOUND")

        for field, value in payload.dict(exclude_unset=True).items():
            setattr(branch, field, value)

        db.commit()
        db.refresh(branch)
        return branch

    def delete_branch(self, branch_id: int):
        db = self.db()
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise APIError("BRANCH_NOT_FOUND")

        db.delete(branch)
        db.commit()
        return True
