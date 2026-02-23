# core/tenants/branch_repository.py

from sqlalchemy.orm import Session
from core.errors.api_error import APIError

# IMPORTANT:
# Branch model now lives inside tenant_model.py
from core.tenants.tenant_model import Branch


class BranchRepository:
    """
    Repository for Branch model.
    Fully dependency-injected version — NO internal SessionLocal().
    """

    # --------------------------------------------------------------
    # LOOKUPS
    # --------------------------------------------------------------
    @staticmethod
    def find_by_id(db: Session, branch_id: int):
        return (
            db.query(Branch)
            .filter(Branch.id == branch_id)
            .first()
        )

    @staticmethod
    def find_by_code(db: Session, branch_code: str):
        return (
            db.query(Branch)
            .filter(Branch.branch_code == branch_code)
            .first()
        )

    @staticmethod
    def list_by_tenant(db: Session, tenant_id: int):
        return (
            db.query(Branch)
            .filter(Branch.tenant_id == tenant_id)
            .all()
        )

    @staticmethod
    def list_active_by_tenant(db: Session, tenant_id: int):
        return (
            db.query(Branch)
            .filter(
                Branch.tenant_id == tenant_id,
                Branch.is_active == True
            )
            .all()
        )

    @staticmethod
    def list_all(db: Session):
        return db.query(Branch).all()

    # --------------------------------------------------------------
    # CREATE / UPDATE
    # --------------------------------------------------------------
    @staticmethod
    def save(db: Session, branch: Branch):
        db.add(branch)
        db.commit()
        db.refresh(branch)
        return branch

    # --------------------------------------------------------------
    # DELETE / ARCHIVE
    # --------------------------------------------------------------
    @staticmethod
    def delete(db: Session, branch_id: int):
        branch = BranchRepository.find_by_id(db, branch_id)
        if not branch:
            raise APIError("BRANCH_NOT_FOUND")

        db.delete(branch)
        db.commit()
        return True

    @staticmethod
    def deactivate(db: Session, branch_id: int):
        """
        Safer option than permanent delete.
        """
        branch = BranchRepository.find_by_id(db, branch_id)
        if not branch:
            raise APIError("BRANCH_NOT_FOUND")

        branch.is_active = False
        db.commit()
        return branch
