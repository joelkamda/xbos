# core/auth/auth_service.py

from core.auth.password_service import PasswordService
from core.security.jwt_service import JWTService
from core.users.user_repository import UserRepository
from core.tenants.tenant_repository import TenantRepository
from core.tenants.branch_repository import BranchRepository
from core.errors.api_error import APIError

# RBAC imports
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY

# DB-backed role permissions
from core.rbac.roles.role_repository import RoleRepository

# Level system fallback
from core.rbac.config import USE_PERMISSION_LEVELS
from core.rbac.permissions.permission_resolver import resolve_permissions_for_role

# Legacy role packs fallback
from core.rbac.roles.role_packs import ROLE_PACKS


class AuthService:
    def __init__(self):
        self.password_service = PasswordService()
        self.jwt_service = JWTService()
        self.users = UserRepository()

    # -------------------------------------------------------------------
    # EFFECTIVE PERMISSION RESOLUTION
    # -------------------------------------------------------------------
    def resolve_effective_permissions(self, db, role_name: str) -> list[str]:
        """
        Resolve permissions for a role.

        Priority:
        1. DB role.permissions JSON
        2. Level-based resolver
        3. Legacy ROLE_PACKS fallback

        This keeps XBOS future-ready:
        - Today: seeded DB roles work.
        - Later: admin-customized role permissions can work.
        - Fallback: old level/pack logic still protects the system.
        """

        role_name = str(role_name or "").strip()

        if not role_name:
            return []

        permissions: list[str] = []

        # ---------------------------------------------------------------
        # 1. DB role permissions first
        # ---------------------------------------------------------------
        db_role = RoleRepository.find_by_name(db, role_name)

        if db_role and isinstance(db_role.permissions, list) and db_role.permissions:
            permissions = db_role.permissions
            print(f"🔐 DB ROLE PERMS for '{role_name}': {permissions}")

        # ---------------------------------------------------------------
        # 2. Fallback to level-based resolver
        # ---------------------------------------------------------------
        elif USE_PERMISSION_LEVELS:
            permissions = resolve_permissions_for_role(role_name)
            print(f"🔐 LEVEL-BASED PERMS for '{role_name}': {permissions}")

        # ---------------------------------------------------------------
        # 3. Final fallback to legacy role packs
        # ---------------------------------------------------------------
        else:
            permissions = ROLE_PACKS.get(role_name, [])
            print(f"🔐 PACK-BASED PERMS for '{role_name}': {permissions}")

        if not isinstance(permissions, list):
            permissions = []

        # ---------------------------------------------------------------
        # Normalize + validate
        # ---------------------------------------------------------------
        normalized = sorted(set(str(p).strip() for p in permissions if p))

        return PERMISSION_REGISTRY.validate_permissions(normalized)

    # -------------------------------------------------------------------
    # USER RESPONSE BUILDER
    # -------------------------------------------------------------------
    def build_user_identity(self, *, user, tenant=None, branch=None, permissions=None):
        """
        Standard user identity payload returned to frontend.

        Used by:
        - login()
        - future /auth/me
        """

        return {
            "id": user.id,
            "username": user.username,
            "full_name": getattr(user, "full_name", None),
            "phone": getattr(user, "phone", None),
            "role": user.role,
            "tenant_id": user.tenant_id,
            "branch_id": user.branch_id,
            "tenant_code": getattr(tenant, "code", None) if tenant else None,
            "branch_code": (
                getattr(branch, "branch_code", None)
                or getattr(branch, "code", None)
                if branch
                else None
            ),
            "permissions": permissions or [],
        }

    # -------------------------------------------------------------------
    # MULTI-TENANT LOGIN + RBAC PERMISSION EXTRACTION
    # -------------------------------------------------------------------
    def login(self, db, username: str, password: str, tenant_code: str, branch_code: str):
        # ---------------------------------------------------------------
        # 1. Tenant validation
        # ---------------------------------------------------------------
        tenant = TenantRepository.find_by_code(db, tenant_code)

        if not tenant:
            raise APIError("TENANT_NOT_FOUND")

        # ---------------------------------------------------------------
        # 2. Branch validation
        # ---------------------------------------------------------------
        branch = BranchRepository.find_by_code(db, branch_code)

        if not branch or branch.tenant_id != tenant.id:
            raise APIError("BRANCH_NOT_FOUND")

        # ---------------------------------------------------------------
        # 3. User lookup
        # ---------------------------------------------------------------
        user = self.users.find_by_username(db, username)

        if not user:
            raise APIError("INVALID_CREDENTIALS")

        # ---------------------------------------------------------------
        # 4. Password validation
        # ---------------------------------------------------------------
        if not self.password_service.verify(password, user.password_hash):
            raise APIError("INVALID_CREDENTIALS")

        # ---------------------------------------------------------------
        # 5. Active check
        # ---------------------------------------------------------------
        if not user.is_active:
            raise APIError("USER_DISABLED")

        # ---------------------------------------------------------------
        # 6. Tenant / branch match
        # ---------------------------------------------------------------
        if user.tenant_id != tenant.id:
            raise APIError("USER_TENANT_MISMATCH")

        if user.branch_id != branch.id:
            raise APIError("USER_BRANCH_MISMATCH")

        # ---------------------------------------------------------------
        # 7. Permissions
        # ---------------------------------------------------------------
        role_permissions = self.resolve_effective_permissions(
            db=db,
            role_name=user.role,
        )

        # User-level overrides are intentionally future-safe.
        # No DB user_permissions table exists yet.
        custom_permissions: list[str] = []

        merged_permissions = sorted(set(role_permissions + custom_permissions))
        merged_permissions = PERMISSION_REGISTRY.validate_permissions(
            merged_permissions
        )

        # ---------------------------------------------------------------
        # 8. Token creation
        # ---------------------------------------------------------------
        access_token = self.jwt_service.create_access_token(
            user.id,
            tenant_id=user.tenant_id,
            branch_id=user.branch_id,
            role=user.role,
            permissions=merged_permissions,
            expires_minutes=60,
        )

        refresh_token = self.jwt_service.create_refresh_token(
            user.id,
            expires_days=30,
        )

        # ---------------------------------------------------------------
        # 9. Response
        # ---------------------------------------------------------------
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": self.build_user_identity(
                user=user,
                tenant=tenant,
                branch=branch,
                permissions=merged_permissions,
            ),
        }

    # -------------------------------------------------------------------
    # REFRESH TOKEN
    # -------------------------------------------------------------------
    def refresh(self, db, refresh_token: str):
        payload = self.jwt_service.decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise APIError("INVALID_REFRESH_TOKEN")

        user_id = int(payload["sub"])

        user = self.users.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        if not user.is_active:
            raise APIError("USER_DISABLED")

        merged_permissions = self.resolve_effective_permissions(
            db=db,
            role_name=user.role,
        )

        new_access_token = self.jwt_service.create_access_token(
            user.id,
            tenant_id=user.tenant_id,
            branch_id=user.branch_id,
            role=user.role,
            permissions=merged_permissions,
            expires_minutes=60,
        )

        return {
            "access_token": new_access_token,
            "token_type": "bearer",
        }

    # -------------------------------------------------------------------
    # CURRENT USER IDENTITY FOR /auth/me
    # -------------------------------------------------------------------
    def me(self, db, user_id: int):
        """
        Return the current authenticated user identity.

        This is intended for:
        GET /kernel/auth/me

        It reloads the user and permissions from DB so a refreshed page gets
        the latest role permissions.
        """

        user = self.users.find_by_id(db, user_id)

        if not user:
            raise APIError("USER_NOT_FOUND")

        if not user.is_active:
            raise APIError("USER_DISABLED")

        tenant = TenantRepository.find_by_id(db, user.tenant_id)
        branch = BranchRepository.find_by_id(db, user.branch_id)

        permissions = self.resolve_effective_permissions(
            db=db,
            role_name=user.role,
        )

        return self.build_user_identity(
            user=user,
            tenant=tenant,
            branch=branch,
            permissions=permissions,
        )