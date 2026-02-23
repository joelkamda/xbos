from core.rbac.permissions.permission_levels import (
    PERMISSION_LEVELS,
    LEVEL_ORDER,
)
from core.rbac.roles.role_levels import ROLE_DEFAULT_LEVEL


def resolve_permissions_for_role(role: str, overrides=None):
    overrides = overrides or []

    role_level = ROLE_DEFAULT_LEVEL.get(role)
    if not role_level:
        return []

    max_level = LEVEL_ORDER[role_level]

    perms = [
        perm
        for perm, level in PERMISSION_LEVELS.items()
        if LEVEL_ORDER[level] <= max_level
    ]

    return sorted(set(perms + overrides))
