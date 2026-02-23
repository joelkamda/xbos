from sqlalchemy.orm import Session
from core.tenants.tenant_model import Tenant
from core.errors.api_error import APIError

class TenantRepository:

    @staticmethod
    def find_by_id(db: Session, tenant_id: int):
        return db.query(Tenant).filter(Tenant.id == tenant_id).first()

    @staticmethod
    def find_by_code(db: Session, tenant_code: str):
        return db.query(Tenant).filter(Tenant.code == tenant_code).first()

    @staticmethod
    def list_all(db: Session):
        return db.query(Tenant).all()

    @staticmethod
    def save(db: Session, tenant: Tenant):
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant

    @staticmethod
    def delete(db: Session, tenant_id: int):
        tenant = TenantRepository.find_by_id(db, tenant_id)
        if not tenant:
            raise APIError("TENANT_NOT_FOUND")
        db.delete(tenant)
        db.commit()
