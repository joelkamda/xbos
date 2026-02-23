# core/rbac/seeds/seed_roles.py

from sqlalchemy.orm import Session

from core.rbac.roles.role_model import Role
from core.rbac.roles.role_repository import RoleRepository


# ============================================================
# CANONICAL ROLE LIST (TIER-0)
# ============================================================
# Rule:
# - This file ONLY ensures roles exist
# - Permissions are assigned elsewhere (level-based seeding)
# - Safe to run repeatedly
# ============================================================

SYSTEM_ROLES = [
    # --------------------------------------------------------
    # LEVEL 1 (LOW)
    # --------------------------------------------------------
    "cashier",
    "waiter",
    "inventory_clerk",

    # --------------------------------------------------------
    # LEVEL 2 (MEDIUM)
    # --------------------------------------------------------
    "store_manager",
    "branch_manager",

    # --------------------------------------------------------
    # LEVEL 3 (HIGH)
    # --------------------------------------------------------
    "owner",
    "admin",
]


def seed_roles(db: Session) -> dict:
    """
    Seed canonical XBOS roles.

    IMPORTANT:
    - Does NOT assign permissions
    - Does NOT infer levels
    - Does NOT touch existing permissions
    - Pure role existence guarantee
    """

    print("🔍 Seeding core roles (names only)...")

    created = []
    existing = []

    for role_name in SYSTEM_ROLES:
        role = RoleRepository.find_by_name(db, role_name)

        if role:
            existing.append(role_name)
            continue

        new_role = Role(
            name=role_name,
            permissions=[],   # ← permissions assigned later
        )

        db.add(new_role)
        created.append(role_name)

    db.commit()

    print(f"🟢 Roles created: {created}")
    print(f"🟡 Roles already existing: {existing}")

    return {
        "status": "ok",
        "created": created,
        "existing": existing,
        "total": len(SYSTEM_ROLES),
    }
