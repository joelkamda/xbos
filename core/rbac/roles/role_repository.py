# core/rbac/roles/role_repository.py

from sqlalchemy.orm import Session
from core.rbac.roles.role_model import Role
from core.rbac.utils.rbac_exceptions import RoleNotFound, RoleAlreadyExists
from core.rbac.permissions.permission_registry import is_valid_permission


class RoleRepository:

    # ---------------------------------------------------------
    # LOOKUPS
    # ---------------------------------------------------------
    @staticmethod
    def find_by_name(db: Session, name: str) -> Role | None:
        return db.query(Role).filter(Role.name == name).first()

    @staticmethod
    def find_by_id(db: Session, role_id: int) -> Role | None:
        return db.query(Role).filter(Role.id == role_id).first()

    @staticmethod
    def list_all(db: Session):
        return db.query(Role).order_by(Role.name.asc()).all()

    # ---------------------------------------------------------
    # CREATE — with validation
    # ---------------------------------------------------------
    @staticmethod
    def create(db: Session, name: str, permissions: list, description: str | None = None):
        # Ensure uniqueness
        if RoleRepository.find_by_name(db, name):
            raise RoleAlreadyExists(f"Role '{name}' already exists")

        # Validate permissions
        for p in permissions:
            if not is_valid_permission(p):
                raise ValueError(f"Invalid permission code: {p}")

        role = Role(name=name, permissions=permissions, description=description)

        db.add(role)
        db.commit()
        db.refresh(role)
        return role

    # ---------------------------------------------------------
    # UPDATE — name, permissions, description
    # ---------------------------------------------------------
    @staticmethod
    def update(db: Session, role_id: int, **updates):
        role = RoleRepository.find_by_id(db, role_id)
        if not role:
            raise RoleNotFound(f"Role ID {role_id} not found")

        if "name" in updates:
            role.name = updates["name"]

        if "permissions" in updates:
            for p in updates["permissions"]:
                if not is_valid_permission(p):
                    raise ValueError(f"Invalid permission code: {p}")
            role.permissions = updates["permissions"]

        if "description" in updates:
            role.description = updates["description"]

        db.commit()
        db.refresh(role)
        return role

    # ---------------------------------------------------------
    # DELETE
    # ---------------------------------------------------------
    @staticmethod
    def delete(db: Session, role_id: int):
        role = RoleRepository.find_by_id(db, role_id)
        if not role:
            raise RoleNotFound(f"Role ID {role_id} not found")

        db.delete(role)
        db.commit()
        return True

    # ---------------------------------------------------------
    # SAVE (AUTO-UPSERT) — REQUIRED BY STARTUP SEEDING
    # ---------------------------------------------------------
    @staticmethod
    def save(db: Session, role: Role):
        """
        Idempotent save:
        - If role exists in session, updates it
        - If new role, inserts it
        Used during RBAC seeding.
        """
        db.add(role)
        db.commit()
        db.refresh(role)
        return role
