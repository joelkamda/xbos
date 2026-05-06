# core/users/user_repository.py

from sqlalchemy.orm import Session
from core.users.user_model import User
from core.errors.api_error import APIError


class UserRepository:
    """
    Repository for User model.
    Fully dependency-injected — no internal SessionLocal().
    """

    # --------------------------------------------------------------
    # FIND OPERATIONS
    # --------------------------------------------------------------
    @staticmethod
    def find_by_username(db: Session, username: str):
        return (
            db.query(User)
            .filter(User.username == username)
            .first()
        )

    @staticmethod
    def find_by_id(db: Session, user_id: int):
        return (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

    @staticmethod
    def username_exists(db: Session, username: str, exclude_user_id: int | None = None) -> bool:
        query = db.query(User).filter(User.username == username)

        if exclude_user_id is not None:
            query = query.filter(User.id != exclude_user_id)

        return db.query(query.exists()).scalar()

    # --------------------------------------------------------------
    # CREATE / SAVE
    # --------------------------------------------------------------
    @staticmethod
    def save(db: Session, user: User):
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def create(
        db: Session,
        *,
        username: str,
        password_hash: str,
        role: str,
        tenant_id: int,
        branch_id: int,
        full_name: str | None = None,
        phone: str | None = None,
        is_active: bool = True,
    ):
        user = User(
            username=username,
            password_hash=password_hash,
            full_name=full_name,
            phone=phone,
            role=role,
            tenant_id=tenant_id,
            branch_id=branch_id,
            is_active=is_active,
        )

        return UserRepository.save(db, user)

    # --------------------------------------------------------------
    # LISTING
    # --------------------------------------------------------------
    @staticmethod
    def list_by_tenant(db: Session, tenant_id: int):
        return (
            db.query(User)
            .filter(User.tenant_id == tenant_id)
            .order_by(User.id.asc())
            .all()
        )

    @staticmethod
    def list_by_branch(db: Session, branch_id: int):
        return (
            db.query(User)
            .filter(User.branch_id == branch_id)
            .order_by(User.id.asc())
            .all()
        )

    @staticmethod
    def list_by_tenant_branch(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int | None = None,
    ):
        query = db.query(User).filter(User.tenant_id == tenant_id)

        if branch_id is not None:
            query = query.filter(User.branch_id == branch_id)

        return query.order_by(User.id.asc()).all()

    # --------------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------------
    @staticmethod
    def update(db: Session, user_id: int, **updates):
        user = UserRepository.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        allowed_fields = {
            "username",
            "full_name",
            "phone",
            "role",
            "tenant_id",
            "branch_id",
            "is_active",
        }

        for key, value in updates.items():
            if key not in allowed_fields:
                continue

            if value is None and key in {"username", "role", "tenant_id", "branch_id"}:
                continue

            setattr(user, key, value)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def set_active(db: Session, user_id: int, is_active: bool):
        user = UserRepository.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        user.is_active = bool(is_active)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def reset_password_hash(db: Session, user_id: int, password_hash: str):
        user = UserRepository.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        user.password_hash = password_hash

        db.commit()
        db.refresh(user)
        return user

    # --------------------------------------------------------------
    # DELETE
    # --------------------------------------------------------------
    @staticmethod
    def delete(db: Session, user_id: int):
        """
        Hard delete is kept for internal maintenance only.

        The user-management UI should use deactivate instead:
            set_active(..., False)
        """
        user = UserRepository.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        db.delete(user)
        db.commit()
        return True