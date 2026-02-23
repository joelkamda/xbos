# core/rbac/seeds/seed_role_permissions.py

from sqlalchemy.orm import Session

from core.rbac.roles.role_repository import RoleRepository
from core.rbac.permissions.permission_levels import (
    PERMISSION_LEVELS,
    LEVEL_ORDER,
)
from core.rbac.roles.role_levels import ROLE_DEFAULT_LEVEL


def seed_role_permissions(db: Session) -> dict:
    """
    Assign permissions to roles based strictly on LEVELS.

    Rules:
    - Level 1 roles → LOW permissions
    - Level 2 roles → LOW + MEDIUM permissions
    - Level 3 roles → LOW + MEDIUM + HIGH permissions
    - Idempotent
    """

    print("🔐 Seeding role permissions by LEVEL...")

    updated = []

    for role_name, role_level in ROLE_DEFAULT_LEVEL.items():

        role = RoleRepository.find_by_name(db, role_name)
        if not role:
            print(f"⚠️ Role '{role_name}' missing — skipping")
            continue

        role_level_rank = LEVEL_ORDER[role_level]

        allowed_permissions = [
            perm
            for perm, perm_level in PERMISSION_LEVELS.items()
            if LEVEL_ORDER[perm_level] <= role_level_rank
        ]

        role.permissions = sorted(set(allowed_permissions))
        updated.append(role_name)

        print(
            f"🟢 {role_name} ({role_level}) → {len(role.permissions)} permissions"
        )

    db.commit()

    return {
        "status": "ok",
        "roles_updated": updated,
        "total": len(updated),
    }
