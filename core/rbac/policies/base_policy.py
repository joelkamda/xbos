# core/rbac/policies/base_policy.py

class BasePolicy:
    def __init__(self, user):
        self.user = user

    def can(self, permission: str) -> bool:
        return permission in (self.user.role.permissions or [])
