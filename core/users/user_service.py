# core/users/user_service.py

from sqlalchemy.orm import Session

from core.auth.password_service import PasswordService
from core.errors.api_error import APIError
from core.rbac.roles.role_repository import RoleRepository
from core.users.user_repository import UserRepository


class UserService:
    """
    Service layer for XBOS user lifecycle management.

    Responsibilities:
    - List users within the authenticated tenant/branch context
    - Create users with hashed passwords
    - Update user profile / role / branch
    - Activate / deactivate users
    - Reset passwords
    """

    def __init__(self):
        self.password_service = PasswordService()
        self.users = UserRepository()

    # --------------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------------
    def serialize_user(self, user):
        return {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "phone": user.phone,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "branch_id": user.branch_id,
            "is_active": bool(user.is_active),
        }

    # --------------------------------------------------------------
    # LIST USERS
    # --------------------------------------------------------------
    def list_users(
        self,
        db: Session,
        *,
        tenant_id: int,
        branch_id: int | None = None,
    ):
        users = self.users.list_by_tenant_branch(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
        )

        items = [self.serialize_user(user) for user in users]

        return {
            "items": items,
            "count": len(items),
        }

    # --------------------------------------------------------------
    # CREATE USER
    # --------------------------------------------------------------
    def create_user(
        self,
        db: Session,
        *,
        current_user: dict,
        payload,
    ):
        tenant_id = int(current_user["tenant_id"])

        username = payload.username.strip()

        if self.users.username_exists(db, username):
            raise APIError("USERNAME_ALREADY_EXISTS")

        role_name = str(payload.role or "staff").strip()

        if not role_name:
            raise APIError("ROLE_REQUIRED")

        role = RoleRepository.find_by_name(db, role_name)

        if not role:
            raise APIError("ROLE_NOT_FOUND")

        branch_id = payload.branch_id or int(current_user["branch_id"])

        password_hash = self.password_service.hash(payload.password)

        user = self.users.create(
            db,
            username=username,
            password_hash=password_hash,
            full_name=payload.full_name,
            phone=payload.phone,
            role=role_name,
            tenant_id=tenant_id,
            branch_id=branch_id,
            is_active=payload.is_active,
        )

        return self.serialize_user(user)

    # --------------------------------------------------------------
    # UPDATE USER
    # --------------------------------------------------------------
    def update_user(
        self,
        db: Session,
        *,
        current_user: dict,
        user_id: int,
        payload,
    ):
        user = self.users.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        tenant_id = int(current_user["tenant_id"])

        if user.tenant_id != tenant_id:
            raise APIError("USER_TENANT_MISMATCH")

        updates = {}

        if payload.username is not None:
            username = payload.username.strip()

            if self.users.username_exists(db, username, exclude_user_id=user_id):
                raise APIError("USERNAME_ALREADY_EXISTS")

            updates["username"] = username

        if payload.full_name is not None:
            updates["full_name"] = payload.full_name

        if payload.phone is not None:
            updates["phone"] = payload.phone

        if payload.role is not None:
            role_name = str(payload.role).strip()

            if not role_name:
                raise APIError("ROLE_REQUIRED")

            role = RoleRepository.find_by_name(db, role_name)

            if not role:
                raise APIError("ROLE_NOT_FOUND")

            updates["role"] = role_name

        if payload.branch_id is not None:
            updates["branch_id"] = payload.branch_id

        if payload.is_active is not None:
            updates["is_active"] = bool(payload.is_active)

        updated = self.users.update(
            db,
            user_id,
            **updates,
        )

        return self.serialize_user(updated)

    # --------------------------------------------------------------
    # ACTIVATE / DEACTIVATE
    # --------------------------------------------------------------
    def set_active(
        self,
        db: Session,
        *,
        current_user: dict,
        user_id: int,
        is_active: bool,
    ):
        user = self.users.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        tenant_id = int(current_user["tenant_id"])

        if user.tenant_id != tenant_id:
            raise APIError("USER_TENANT_MISMATCH")

        # Safety: avoid locking yourself out.
        if int(current_user["user_id"]) == int(user_id) and not is_active:
            raise APIError("CANNOT_DISABLE_SELF")

        updated = self.users.set_active(
            db,
            user_id=user_id,
            is_active=is_active,
        )

        return self.serialize_user(updated)

    # --------------------------------------------------------------
    # RESET PASSWORD
    # --------------------------------------------------------------
    def reset_password(
        self,
        db: Session,
        *,
        current_user: dict,
        user_id: int,
        new_password: str,
    ):
        user = self.users.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        tenant_id = int(current_user["tenant_id"])

        if user.tenant_id != tenant_id:
            raise APIError("USER_TENANT_MISMATCH")

        password_hash = self.password_service.hash(new_password)

        updated = self.users.reset_password_hash(
            db,
            user_id=user_id,
            password_hash=password_hash,
        )

        return self.serialize_user(updated)