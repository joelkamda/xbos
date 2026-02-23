# core/rbac/roles/role_service.py

from sqlalchemy.orm import Session

from core.rbac.roles.role_repository import RoleRepository
from core.rbac.roles.role_model import Role
from core.rbac.utils.rbac_exceptions import (
    RoleAlreadyExists,
    RoleNotFound,
    InvalidPermission,
)
from core.rbac.permissions.permission_registry import is_valid_permission


class RoleService:
    """
    High-level service layer for managing roles.
    (Used by admin endpoints, seeds, system setup, automation scripts)
    """

    # ---------------------------------------------------------
    # CREATE ROLE
    # ---------------------------------------------------------
    def create_role(self, db: Session, name: str, permissions: list[str], description=None):
        # validate all permission codes
        for p in permissions:
            if not is_valid_permission(p):
                raise InvalidPermission(f"Invalid permission: {p}")

        # uniqueness check handled in repo
        return RoleRepository.create(db, name=name, permissions=permissions, description=description)

    # ---------------------------------------------------------
    # UPDATE ROLE
    # ---------------------------------------------------------
    def update_role(self, db: Session, role_id: int, name: str = None,
                    permissions: list[str] = None, description=None):

        if permissions is not None:
            for p in permissions:
                if not is_valid_permission(p):
                    raise InvalidPermission(f"Invalid permission: {p}")

        return RoleRepository.update(
            db,
            role_id=role_id,
            name=name,
            permissions=permissions,
            description=description
        )

    # ---------------------------------------------------------
    # ADD PERMISSIONS TO EXISTING ROLE
    # ---------------------------------------------------------
    def add_permissions(self, db: Session, role_id: int, permissions_to_add: list[str]):
        role = RoleRepository.find_by_id(db, role_id)
        if not role:
            raise RoleNotFound(f"Role ID {role_id} not found")

        for p in permissions_to_add:
            if not is_valid_permission(p):
                raise InvalidPermission(f"Invalid permission: {p}")

        # merge unique additions
        merged = set(role.permissions or [])
        merged.update(permissions_to_add)

        return RoleRepository.update(db, role_id, permissions=list(merged))

    # ---------------------------------------------------------
    # REMOVE PERMISSIONS FROM ROLE
    # ---------------------------------------------------------
    def remove_permissions(self, db: Session, role_id: int, permissions_to_remove: list[str]):
        role = RoleRepository.find_by_id(db, role_id)
        if not role:
            raise RoleNotFound(f"Role ID {role_id} not found")

        remaining = [p for p in role.permissions if p not in permissions_to_remove]

        return RoleRepository.update(db, role_id, permissions=remaining)

    # ---------------------------------------------------------
    # DELETE ROLE
    # ---------------------------------------------------------
    def delete_role(self, db: Session, role_id: int):
        return RoleRepository.delete(db, role_id)

    # ---------------------------------------------------------
    # FETCH ROLE
    # ---------------------------------------------------------
    def get_role(self, db: Session, role_id: int):
        role = RoleRepository.find_by_id(db, role_id)
        if not role:
            raise RoleNotFound(f"Role ID {role_id} not found")
        return role

    # ---------------------------------------------------------
    # LIST ALL ROLES
    # ---------------------------------------------------------
    def list_roles(self, db: Session):
        return RoleRepository.list_all(db)
