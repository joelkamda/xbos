from sqlalchemy.orm import Session

from core.rbac.permissions.permission_levels import (
    PERMISSION_LEVELS,
    LEVEL_ORDER,
)
from core.rbac.roles.role_levels import ROLE_DEFAULT_LEVEL
from core.rbac.roles.role_repository import RoleRepository
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY


def seed_role_packs(db: Session) -> None:
    """
    Assign permissions to roles based on LEVEL inheritance.
    """

    print("🔍 Seeding role permission packs...")

    all_permissions = PERMISSION_REGISTRY.ALL

    for role_name, role_level in ROLE_DEFAULT_LEVEL.items():
        role = RoleRepository.find_by_name(db, role_name)

        if not role:
            print(f"⚠️  Role not found, skipping: {role_name}")
            continue

        max_level = LEVEL_ORDER[role_level]

        granted_permissions = []

        for perm in all_permissions:
            perm_level = PERMISSION_LEVELS.get(perm)

            if not perm_level:
                print(f"⚠️  Permission missing level: {perm}")
                continue

            if LEVEL_ORDER[perm_level] <= max_level:
                granted_permissions.append(perm)

        RoleRepository.set_permissions(
            db,
            role=role,
            permissions=granted_permissions,
        )

        print(
            f"✅ Role '{role_name}' ({role_level}) "
            f"→ {len(granted_permissions)} permissions"
        )

    db.commit()
    print("🎯 Role permission packs seeded successfully")
