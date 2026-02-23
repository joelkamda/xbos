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

    # --------------------------------------------------------------
    # CREATE / SAVE
    # --------------------------------------------------------------
    @staticmethod
    def save(db: Session, user: User):
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    # --------------------------------------------------------------
    # LISTING
    # --------------------------------------------------------------
    @staticmethod
    def list_by_tenant(db: Session, tenant_id: int):
        return (
            db.query(User)
            .filter(User.tenant_id == tenant_id)
            .all()
        )

    @staticmethod
    def list_by_branch(db: Session, branch_id: int):
        return (
            db.query(User)
            .filter(User.branch_id == branch_id)
            .all()
        )

    # --------------------------------------------------------------
    # DELETE
    # --------------------------------------------------------------
    @staticmethod
    def delete(db: Session, user_id: int):
        user = UserRepository.find_by_id(db, user_id)
        if not user:
            raise APIError("USER_NOT_FOUND")

        db.delete(user)
        db.commit()
        return True
